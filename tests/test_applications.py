"""Application CRUD, search, filtering, sorting and pagination."""
import pytest


class TestCreate:
    def test_returns_201_with_defaults(self, client, application_payload):
        response = client.post("/applications", json=application_payload)
        assert response.status_code == 201
        body = response.json()
        assert body["company"] == "Acme Corp"
        assert body["status"] == "applied"
        assert body["salary_currency"] == "USD"
        assert body["id"]

    def test_persists_the_newer_fields(self, client, application_payload):
        response = client.post(
            "/applications",
            json={
                **application_payload,
                "next_action": "Send take-home",
                "next_action_date": "2026-08-20",
                "job_description": "Own the regression suite.",
            },
        )
        body = response.json()
        assert body["next_action"] == "Send take-home"
        assert body["next_action_date"] == "2026-08-20"
        assert body["job_description"] == "Own the regression suite."

    # date_applied is deliberately absent: it became optional in KAN-31 so a
    # job can be tracked before it is applied for. See TestUndated below.
    @pytest.mark.parametrize("missing", ["company", "role_title"])
    def test_required_fields_are_enforced(self, client, application_payload, missing):
        payload = {k: v for k, v in application_payload.items() if k != missing}
        assert client.post("/applications", json=payload).status_code == 422

    def test_unknown_status_rejected(self, client, application_payload):
        response = client.post(
            "/applications", json={**application_payload, "status": "napping"}
        )
        assert response.status_code == 422


class TestUndated:
    """Jobs tracked before they are applied for (KAN-31).

    The two halves have to hold together: a record with no date needs a status
    that explains why, and `interested` is meaningless while every record must
    carry a date.
    """

    def test_creates_without_a_date(self, client):
        response = client.post(
            "/applications", json={"company": "Acme Corp", "role_title": "SDET"}
        )
        assert response.status_code == 201
        body = response.json()
        assert body["date_applied"] is None
        assert body["status"] == "interested"

    def test_an_explicit_status_survives_a_missing_date(self, client):
        """Only an *absent* status is reinterpreted. Someone who says `applied`
        without a date has said something odd but has said it deliberately."""
        response = client.post(
            "/applications",
            json={"company": "Acme Corp", "role_title": "SDET", "status": "applied"},
        )
        assert response.json()["status"] == "applied"

    def test_a_dated_record_still_defaults_to_applied(
        self, client, application_payload
    ):
        """The common case is unchanged — the new rule keys off the missing
        date, not off the status being absent."""
        response = client.post("/applications", json=application_payload)
        assert response.json()["status"] == "applied"

    def test_round_trips_through_detail_and_list(self, client):
        created = client.post(
            "/applications", json={"company": "Acme Corp", "role_title": "SDET"}
        ).json()

        detail = client.get(f"/applications/{created['id']}").json()
        assert detail["date_applied"] is None
        assert detail["status"] == "interested"

        row = client.get("/applications").json()["items"][0]
        assert row["date_applied"] is None
        assert row["status"] == "interested"

    def test_gains_a_date_when_the_application_goes_out(self, client):
        created = client.post(
            "/applications", json={"company": "Acme Corp", "role_title": "SDET"}
        ).json()

        patched = client.patch(
            f"/applications/{created['id']}",
            json={"date_applied": "2026-08-21", "status": "applied"},
        ).json()
        assert patched["date_applied"] == "2026-08-21"
        assert patched["status"] == "applied"

    def test_a_date_can_be_cleared_again(self, client, make_application):
        """Correcting a record entered by mistake, without deleting it —
        applications are never deleted (§4.1)."""
        created = make_application()
        patched = client.patch(
            f"/applications/{created['id']}", json={"date_applied": None}
        ).json()
        assert patched["date_applied"] is None

    def test_interested_is_filterable(self, client, make_application):
        make_application()
        client.post("/applications", json={"company": "Zeta", "role_title": "SDET"})

        body = client.get("/applications?status=interested").json()
        assert body["total"] == 1
        assert body["items"][0]["company"] == "Zeta"


class TestRead:
    def test_detail_includes_contacts(self, client, make_application):
        created = make_application()
        body = client.get(f"/applications/{created['id']}").json()
        assert body["contacts"] == []

    def test_missing_application_returns_404(self, client):
        assert client.get("/applications/999999").status_code == 404

    def test_list_omits_contacts(self, client, make_application):
        """Contacts are deliberately excluded from list rows — including them
        would mean one query per application on every list request."""
        make_application()
        row = client.get("/applications").json()["items"][0]
        assert "contacts" not in row


class TestUpdate:
    def test_patch_changes_only_supplied_fields(self, client, make_application):
        created = make_application(location="Remote")
        response = client.patch(
            f"/applications/{created['id']}", json={"status": "interview"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "interview"
        assert response.json()["location"] == "Remote"

    def test_any_status_transition_is_allowed(self, client, make_application):
        """Free assignment is a decision, not an oversight — see
        REQUIREMENTS.md §3. This test exists so that reversing it is a
        deliberate act rather than an accident."""
        created = make_application(status="rejected")
        response = client.patch(
            f"/applications/{created['id']}", json={"status": "interview"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "interview"

    def test_missing_application_returns_404(self, client):
        assert client.patch("/applications/999999", json={}).status_code == 404


class TestNoDelete:
    def test_there_is_no_delete_route(self, client, make_application):
        """Applications are archived, never deleted — see REQUIREMENTS.md §4.1.
        This asserts the route is genuinely absent rather than merely unused."""
        created = make_application()
        response = client.delete(f"/applications/{created['id']}")
        assert response.status_code == 405
        assert client.get(f"/applications/{created['id']}").status_code == 200


class TestSearch:
    @pytest.fixture(autouse=True)
    def _seed(self, make_application):
        make_application(company="Northwind", location="Austin, TX", source="LinkedIn")
        make_application(
            company="Globex", location="Remote", source="referral", notes="Met at a expo"
        )

    @pytest.mark.parametrize(
        "term,expected",
        [
            ("Northwind", "Northwind"),  # company
            ("Austin", "Northwind"),  # location
            ("referral", "Globex"),  # source
            ("expo", "Globex"),  # notes
        ],
    )
    def test_search_covers_every_intended_field(self, client, term, expected):
        body = client.get(f"/applications?search={term}").json()
        assert body["total"] == 1
        assert body["items"][0]["company"] == expected

    def test_search_is_case_insensitive(self, client):
        assert client.get("/applications?search=northwind").json()["total"] == 1

    def test_no_match_returns_empty(self, client):
        body = client.get("/applications?search=zzzznope").json()
        assert body["total"] == 0
        assert body["items"] == []


class TestFilterAndSort:
    @pytest.fixture(autouse=True)
    def _seed(self, make_application):
        make_application(company="Charlie", status="offer", date_applied="2026-03-01")
        make_application(company="Alpha", status="applied", date_applied="2026-01-01")
        make_application(company="Bravo", status="applied", date_applied="2026-02-01")

    def test_status_filter(self, client):
        body = client.get("/applications?status=applied").json()
        assert body["total"] == 2
        assert {i["company"] for i in body["items"]} == {"Alpha", "Bravo"}

    def test_default_sort_is_newest_first(self, client):
        items = client.get("/applications").json()["items"]
        assert [i["company"] for i in items] == ["Charlie", "Bravo", "Alpha"]

    def test_sort_ascending_by_company(self, client):
        items = client.get(
            "/applications?sort_by=company&sort_dir=asc"
        ).json()["items"]
        assert [i["company"] for i in items] == ["Alpha", "Bravo", "Charlie"]

    @pytest.mark.parametrize(
        "column", ["company", "role_title", "location", "source", "status",
                   "date_applied", "next_action_date", "salary_min", "salary_max",
                   "created_at"]
    )
    def test_permitted_sort_columns(self, client, column):
        assert client.get(f"/applications?sort_by={column}").status_code == 200

    @pytest.mark.parametrize("column", ["notes", "id", "job_description", "; DROP"])
    def test_rejected_sort_columns(self, client, column):
        """crud.list_applications resolves the column with getattr, so this
        pattern is the only guard against an arbitrary attribute lookup."""
        assert client.get(f"/applications?sort_by={column}").status_code == 422

    def test_invalid_sort_direction_rejected(self, client):
        assert client.get("/applications?sort_dir=sideways").status_code == 422

    def test_filter_and_sort_combine(self, client):
        items = client.get(
            "/applications?status=applied&sort_by=company&sort_dir=desc"
        ).json()["items"]
        assert [i["company"] for i in items] == ["Bravo", "Alpha"]


class TestNullSortOrder:
    """A NULL sorts as though it were greater than every real value (KAN-31).

    This is a decision, not the dialect's default. It is what puts jobs you
    have not applied to at the *top* of the default view — inherited behaviour
    dropped them at the bottom, which past 50 rows means below a "Load more"
    button and effectively out of sight.

    These tests are the only thing pinning it. Nothing else fails if the
    ordering silently reverts.
    """

    @pytest.fixture(autouse=True)
    def _seed(self, client, make_application):
        make_application(company="Dated older", date_applied="2026-01-01")
        make_application(company="Dated newer", date_applied="2026-06-01")
        client.post(
            "/applications", json={"company": "Undated", "role_title": "SDET"}
        )

    def _companies(self, client, query=""):
        return [i["company"] for i in client.get(f"/applications{query}").json()["items"]]

    def test_undated_leads_the_default_view(self, client):
        """The default sort is date_applied descending — the view the user
        actually opens."""
        assert self._companies(client) == ["Undated", "Dated newer", "Dated older"]

    def test_ascending_puts_it_last(self, client):
        """Reversing the direction reverses the whole list. Nothing is pinned:
        NULL is the largest value, so oldest-first leaves it at the end."""
        assert self._companies(client, "?sort_by=date_applied&sort_dir=asc") == [
            "Dated older",
            "Dated newer",
            "Undated",
        ]

    def test_the_rule_is_not_special_cased_to_dates(self, client, make_application):
        """One rule for every sortable column, so an empty Location or Source
        behaves the same way. Ascending puts empties last, which is the
        conventional expectation and was previously reversed."""
        make_application(company="Has a location", location="Austin, TX")

        ascending = self._companies(client, "?sort_by=location&sort_dir=asc")
        assert ascending[0] == "Has a location"
        assert self._companies(client, "?sort_by=location&sort_dir=desc")[0] != (
            "Has a location"
        )

    def test_the_count_is_unaffected(self, client):
        """Ordering must not leak into the WHERE clause — the undated record is
        moved, not filtered out."""
        assert client.get("/applications").json()["total"] == 3


class TestPagination:
    @pytest.fixture(autouse=True)
    def _seed(self, make_application):
        for n in range(1, 26):
            make_application(company=f"Company {n:02d}", date_applied="2026-01-01")

    def test_total_ignores_skip_and_limit(self, client):
        """The count must reflect the whole result set, not the page — this is
        what made the original pagination bug visible rather than silent."""
        body = client.get("/applications?skip=10&limit=5").json()
        assert body["total"] == 25
        assert len(body["items"]) == 5

    def test_paging_covers_every_record_exactly_once(self, client):
        seen = []
        for skip in range(0, 25, 10):
            page = client.get(f"/applications?skip={skip}&limit=10").json()["items"]
            seen.extend(i["company"] for i in page)
        assert len(seen) == 25
        assert len(set(seen)) == 25

    def test_skip_beyond_the_end_returns_empty(self, client):
        body = client.get("/applications?skip=100&limit=10").json()
        assert body["items"] == []
        assert body["total"] == 25

    def test_total_reflects_the_filter(self, client, make_application):
        make_application(company="Filtered", status="offer")
        body = client.get("/applications?status=offer&limit=2").json()
        assert body["total"] == 1


def test_health_endpoint(client):
    assert client.get("/health").json() == {"status": "ok"}
