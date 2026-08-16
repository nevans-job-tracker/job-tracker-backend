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
