"""Server-side field rules (KAN-9).

These exist because the browser form is not a guard: anything calling the API
directly — including /docs — bypasses it entirely.
"""
import pytest


class TestSalaryRange:
    def test_rejects_an_inverted_range_on_create(self, client, application_payload):
        response = client.post(
            "/applications",
            json={**application_payload, "salary_min": 120000, "salary_max": 90000},
        )
        assert response.status_code == 422
        assert "salary" in response.json()["detail"].lower()

    def test_accepts_a_valid_range(self, client, application_payload):
        response = client.post(
            "/applications",
            json={**application_payload, "salary_min": 90000, "salary_max": 120000},
        )
        assert response.status_code == 201

    def test_accepts_equal_bounds(self, client, application_payload):
        response = client.post(
            "/applications",
            json={**application_payload, "salary_min": 100000, "salary_max": 100000},
        )
        assert response.status_code == 201

    @pytest.mark.parametrize(
        "salary", [{"salary_min": 90000}, {"salary_max": 90000}, {}]
    )
    def test_a_single_bound_is_fine(self, client, application_payload, salary):
        response = client.post("/applications", json={**application_payload, **salary})
        assert response.status_code == 201

    def test_rejects_an_inverted_range_on_update(self, client, make_application):
        created = make_application(salary_min=90000, salary_max=120000)
        response = client.patch(
            f"/applications/{created['id']}", json={"salary_min": 150000}
        )
        assert response.status_code == 422

    def test_checks_the_merged_result_not_just_the_request(
        self, client, make_application
    ):
        """A PATCH supplying only salary_max can still invert the pair against
        the stored salary_min, so the rule has to run on the merged values."""
        created = make_application(salary_min=100000, salary_max=120000)
        response = client.patch(
            f"/applications/{created['id']}", json={"salary_max": 50000}
        )
        assert response.status_code == 422

    def test_an_invalid_update_changes_nothing(self, client, make_application):
        created = make_application(salary_min=90000, salary_max=120000)
        client.patch(f"/applications/{created['id']}", json={"salary_min": 150000})

        stored = client.get(f"/applications/{created['id']}").json()
        assert stored["salary_min"] == "90000.00"

    def test_clearing_a_bound_is_allowed(self, client, make_application):
        created = make_application(salary_min=90000, salary_max=120000)
        response = client.patch(
            f"/applications/{created['id']}", json={"salary_max": None}
        )
        assert response.status_code == 200
        assert response.json()["salary_max"] is None


class TestJobLink:
    @pytest.mark.parametrize(
        "link",
        [
            "https://example.com/jobs/1",
            "http://example.com",
            "https://sub.example.co.uk/path?query=1",
        ],
    )
    def test_accepts_http_urls(self, client, application_payload, link):
        response = client.post(
            "/applications", json={**application_payload, "job_link": link}
        )
        assert response.status_code == 201
        assert response.json()["job_link"] == link

    @pytest.mark.parametrize(
        "link", ["not a url", "example.com", "javascript:alert(1)", "/relative/path"]
    )
    def test_rejects_everything_else(self, client, application_payload, link):
        response = client.post(
            "/applications", json={**application_payload, "job_link": link}
        )
        assert response.status_code == 422

    def test_stores_the_url_exactly_as_entered(self, client, application_payload):
        """pydantic's HttpUrl normalises — appending a trailing slash, among
        other things. A pasted link should come back unchanged."""
        response = client.post(
            "/applications",
            json={**application_payload, "job_link": "https://example.com"},
        )
        assert response.json()["job_link"] == "https://example.com"

    def test_null_and_empty_are_accepted_as_absent(self, client, application_payload):
        for value in (None, ""):
            response = client.post(
                "/applications", json={**application_payload, "job_link": value}
            )
            assert response.status_code == 201
            assert response.json()["job_link"] is None

    def test_validated_on_update_too(self, client, make_application):
        created = make_application()
        response = client.patch(
            f"/applications/{created['id']}", json={"job_link": "nope"}
        )
        assert response.status_code == 422


class TestDateApplied:
    def test_a_future_date_is_accepted(self, client, application_payload):
        """Decided: warn, don't reject — logging an application about to be
        submitted is legitimate. The warning is presented in the UI."""
        response = client.post(
            "/applications", json={**application_payload, "date_applied": "2099-01-01"}
        )
        assert response.status_code == 201

    def test_a_malformed_date_is_rejected(self, client, application_payload):
        response = client.post(
            "/applications", json={**application_payload, "date_applied": "not-a-date"}
        )
        assert response.status_code == 422

    def test_an_explicit_null_is_treated_as_absent(self, client):
        """The form sends `null` rather than omitting the key, so the two must
        behave identically — an explicit null still yields `interested`."""
        response = client.post(
            "/applications",
            json={"company": "Acme Corp", "role_title": "SDET", "date_applied": None},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "interested"


class TestErrorShape:
    def test_our_own_rules_return_a_plain_string_detail(
        self, client, application_payload
    ):
        """The frontend renders `detail` directly, so a readable sentence beats
        a nested structure for rules we raise ourselves."""
        response = client.post(
            "/applications",
            json={**application_payload, "salary_min": 5, "salary_max": 1},
        )
        assert isinstance(response.json()["detail"], str)

    def test_schema_failures_identify_the_field(self, client, application_payload):
        response = client.post(
            "/applications", json={**application_payload, "job_link": "nope"}
        )
        detail = response.json()["detail"]
        assert isinstance(detail, list)
        assert any("job_link" in str(item.get("loc", "")) for item in detail)


class TestPayPeriod:
    """KAN-50 — what the salary figures actually measure."""

    def test_defaults_to_annual(self, client, application_payload):
        # NOT NULL with a default: every pay figure is one period or the
        # other, so there is no honest "unset" to represent.
        response = client.post("/applications", json=application_payload)
        assert response.status_code == 201
        assert response.json()["pay_period"] == "annual"

    def test_accepts_hourly(self, client, application_payload):
        response = client.post(
            "/applications",
            json={**application_payload, "pay_period": "hourly",
                  "salary_min": 86, "salary_max": 86},
        )
        assert response.status_code == 201
        assert response.json()["pay_period"] == "hourly"

    def test_rejects_a_period_that_is_not_one(self, client, application_payload):
        response = client.post(
            "/applications", json={**application_payload, "pay_period": "weekly"}
        )
        assert response.status_code == 422

    def test_can_be_switched_on_an_existing_record(self, client, application_payload):
        created = client.post("/applications", json=application_payload).json()
        response = client.patch(
            f"/applications/{created['id']}", json={"pay_period": "hourly"}
        )
        assert response.status_code == 200
        assert response.json()["pay_period"] == "hourly"


class TestEmploymentType:
    """KAN-51 — permanent, fixed-term, or unpaid."""

    def test_defaults_to_blank(self, client, application_payload):
        # Unlike pay_period this is nullable and undefaulted: plenty of
        # postings do not say, and full_time would invent a fact.
        response = client.post("/applications", json=application_payload)
        assert response.json()["employment_type"] is None

    @pytest.mark.parametrize(
        "value",
        ["full_time", "part_time", "contract", "contract_to_hire", "volunteer"],
    )
    def test_accepts_every_declared_type(self, client, application_payload, value):
        payload = {**application_payload, "employment_type": value}
        response = client.post("/applications", json=payload)
        assert response.status_code == 201
        assert response.json()["employment_type"] == value

    def test_rejects_a_type_that_is_not_one(self, client, application_payload):
        response = client.post(
            "/applications",
            json={**application_payload, "employment_type": "freelance"},
        )
        assert response.status_code == 422


class TestContractTerm:
    """KAN-51 — the term is only meaningful on a contract."""

    @pytest.mark.parametrize("kind", ["contract", "contract_to_hire"])
    def test_accepted_alongside_a_contract(self, client, application_payload, kind):
        response = client.post(
            "/applications",
            json={**application_payload, "employment_type": kind,
                  "contract_term_months": 6},
        )
        assert response.status_code == 201
        assert response.json()["contract_term_months"] == 6

    def test_rejected_without_an_employment_type(self, client, application_payload):
        response = client.post(
            "/applications",
            json={**application_payload, "contract_term_months": 6},
        )
        assert response.status_code == 422
        assert "contract" in response.json()["detail"].lower()

    def test_rejected_on_a_full_time_role(self, client, application_payload):
        response = client.post(
            "/applications",
            json={**application_payload, "employment_type": "full_time",
                  "contract_term_months": 6},
        )
        assert response.status_code == 422

    def test_rejected_when_the_stored_type_is_changed_out_from_under_it(
        self, client, application_payload
    ):
        # The reason the rule lives in the route and reads the *merged*
        # result. This PATCH carries no term at all, so a check against the
        # request body alone would pass and leave a term nothing explains.
        created = client.post(
            "/applications",
            json={**application_payload, "employment_type": "contract",
                  "contract_term_months": 6},
        ).json()

        response = client.patch(
            f"/applications/{created['id']}", json={"employment_type": "full_time"}
        )
        assert response.status_code == 422
        assert client.get(f"/applications/{created['id']}").json()[
            "contract_term_months"
        ] == 6

    def test_clearing_both_together_is_allowed(self, client, application_payload):
        created = client.post(
            "/applications",
            json={**application_payload, "employment_type": "contract",
                  "contract_term_months": 6},
        ).json()

        response = client.patch(
            f"/applications/{created['id']}",
            json={"employment_type": "full_time", "contract_term_months": None},
        )
        assert response.status_code == 200
        assert response.json()["contract_term_months"] is None

    def test_rejects_a_negative_term(self, client, application_payload):
        response = client.post(
            "/applications",
            json={**application_payload, "employment_type": "contract",
                  "contract_term_months": -3},
        )
        assert response.status_code == 422


class TestEmploymentTypeSorting:
    def test_is_an_accepted_sort_key(self, client):
        assert client.get("/applications?sort_by=employment_type").status_code == 200

    def test_the_whitelist_still_rejects_anything_else(self, client):
        # The whitelist is a security boundary, not a convenience — crud
        # resolves the column with getattr.
        assert client.get("/applications?sort_by=notes").status_code == 422


class TestWeeklyHours:
    """KAN-51 — postings state a commitment as a range ("10-40 hrs/week")."""

    def test_records_a_range(self, client, application_payload):
        response = client.post(
            "/applications",
            json={**application_payload, "employment_type": "contract",
                  "hours_per_week_min": 10, "hours_per_week_max": 40},
        )
        assert response.status_code == 201
        body = response.json()
        assert (body["hours_per_week_min"], body["hours_per_week_max"]) == (10, 40)

    def test_a_fixed_commitment_sets_both_ends(self, client, application_payload):
        response = client.post(
            "/applications",
            json={**application_payload, "hours_per_week_min": 40,
                  "hours_per_week_max": 40},
        )
        assert response.status_code == 201

    def test_rejects_an_inverted_range(self, client, application_payload):
        response = client.post(
            "/applications",
            json={**application_payload, "hours_per_week_min": 40,
                  "hours_per_week_max": 10},
        )
        assert response.status_code == 422
        assert "hours per week" in response.json()["detail"].lower()

    def test_rejects_an_inversion_created_by_a_patch(self, client, application_payload):
        # Same reason the salary rule reads the merged record: this PATCH
        # carries only the max, so checking the body alone would let it through.
        created = client.post(
            "/applications",
            json={**application_payload, "hours_per_week_min": 20,
                  "hours_per_week_max": 40},
        ).json()

        response = client.patch(
            f"/applications/{created['id']}", json={"hours_per_week_max": 5}
        )
        assert response.status_code == 422

    def test_rejects_negative_hours(self, client, application_payload):
        response = client.post(
            "/applications", json={**application_payload, "hours_per_week_min": -1}
        )
        assert response.status_code == 422

    def test_is_not_tied_to_an_employment_type(self, client, application_payload):
        # 20 hours a week means the same on a part-time role as on a contract,
        # so unlike contract_term_months this carries no pairing rule.
        response = client.post(
            "/applications",
            json={**application_payload, "employment_type": "part_time",
                  "hours_per_week_min": 20, "hours_per_week_max": 25},
        )
        assert response.status_code == 201
