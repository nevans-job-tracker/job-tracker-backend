"""Archiving, which replaces deletion entirely (KAN-13).

Archive records whether an application should still be in view; `status`
records what happened to it. The two are independent axes and both filters
apply at once — see REQUIREMENTS.md §4.1.
"""
import pytest


@pytest.fixture
def archived(client, make_application):
    created = make_application(company="Archived Co")
    response = client.post(f"/applications/{created['id']}/archive")
    assert response.status_code == 200, response.text
    return response.json()


class TestArchiving:
    def test_new_applications_are_active(self, make_application):
        assert make_application()["archived_at"] is None

    def test_archiving_stamps_the_time(self, archived):
        assert archived["archived_at"] is not None

    def test_unarchiving_clears_it(self, client, archived):
        response = client.post(f"/applications/{archived['id']}/unarchive")
        assert response.status_code == 200
        assert response.json()["archived_at"] is None

    def test_archiving_is_idempotent(self, client, archived):
        response = client.post(f"/applications/{archived['id']}/archive")
        assert response.status_code == 200
        assert response.json()["archived_at"] is not None

    def test_unarchiving_an_active_record_is_harmless(self, client, make_application):
        created = make_application()
        response = client.post(f"/applications/{created['id']}/unarchive")
        assert response.status_code == 200
        assert response.json()["archived_at"] is None

    @pytest.mark.parametrize("action", ["archive", "unarchive"])
    def test_missing_application_returns_404(self, client, action):
        assert client.post(f"/applications/999999/{action}").status_code == 404

    def test_the_record_survives_archiving(self, client, archived):
        """Nothing is purged — the whole record remains readable."""
        body = client.get(f"/applications/{archived['id']}").json()
        assert body["company"] == "Archived Co"
        assert body["archived_at"] is not None

    def test_contacts_survive_archiving(self, client, make_application):
        created = make_application()
        client.post(f"/applications/{created['id']}/contacts", json={"name": "Dana Wu"})
        client.post(f"/applications/{created['id']}/archive")

        body = client.get(f"/applications/{created['id']}").json()
        assert [c["name"] for c in body["contacts"]] == ["Dana Wu"]

    def test_archived_records_remain_editable(self, client, archived):
        response = client.patch(
            f"/applications/{archived['id']}", json={"status": "offer"}
        )
        assert response.status_code == 200
        assert response.json()["archived_at"] is not None

    def test_archived_at_cannot_be_set_through_patch(self, client, make_application):
        """It is set only through the archive endpoints, so it can't be edited
        alongside ordinary fields."""
        created = make_application()
        client.patch(
            f"/applications/{created['id']}", json={"archived_at": "2026-01-01T00:00:00"}
        )
        assert client.get(f"/applications/{created['id']}").json()["archived_at"] is None


class TestListFiltering:
    @pytest.fixture(autouse=True)
    def _seed(self, client, make_application):
        make_application(company="Active One", status="applied")
        make_application(company="Active Two", status="offer")
        gone = make_application(company="Archived One", status="applied")
        client.post(f"/applications/{gone['id']}/archive")

    def _companies(self, client, query=""):
        body = client.get(f"/applications{query}").json()
        return {item["company"] for item in body["items"]}, body["total"]

    def test_defaults_to_active_only(self, client):
        companies, total = self._companies(client)
        assert companies == {"Active One", "Active Two"}
        assert total == 2

    def test_archived_only(self, client):
        companies, total = self._companies(client, "?show=archived")
        assert companies == {"Archived One"}
        assert total == 1

    def test_all(self, client):
        companies, total = self._companies(client, "?show=all")
        assert len(companies) == 3
        assert total == 3

    def test_rejects_an_unknown_value(self, client):
        assert client.get("/applications?show=everything").status_code == 422

    def test_combines_with_the_status_filter(self, client):
        """Both axes apply at once: applied + archived is a real combination."""
        companies, total = self._companies(client, "?show=archived&status=applied")
        assert companies == {"Archived One"}
        assert total == 1

        companies, total = self._companies(client, "?show=active&status=applied")
        assert companies == {"Active One"}

    def test_combines_with_search(self, client):
        companies, _ = self._companies(client, "?show=all&search=Archived")
        assert companies == {"Archived One"}

    def test_total_reflects_the_archive_filter(self, client):
        """The count must match what the filter returns, not the whole table —
        otherwise the list reports more rows than it can show."""
        body = client.get("/applications?show=active&limit=1").json()
        assert body["total"] == 2
        assert len(body["items"]) == 1

    def test_unarchiving_returns_a_record_to_the_default_view(
        self, client, make_application
    ):
        gone = make_application(company="Coming Back")
        client.post(f"/applications/{gone['id']}/archive")
        assert "Coming Back" not in self._companies(client)[0]

        client.post(f"/applications/{gone['id']}/unarchive")
        assert "Coming Back" in self._companies(client)[0]
