"""Contacts, which hang off an application and are scoped to it."""
import pytest

CONTACT = {
    "name": "Dana Wu",
    "title": "Sr. Quality Engineer",
    "phone": "+1 555-0142 x231",
    "email": "dana@acme.example",
    "notes": "Mentioned the team is splitting in Q4.",
}


@pytest.fixture
def application(make_application):
    return make_application()


@pytest.fixture
def contact(client, application):
    response = client.post(f"/applications/{application['id']}/contacts", json=CONTACT)
    assert response.status_code == 201, response.text
    return response.json()


class TestCreate:
    def test_all_fields_persist(self, contact, application):
        for field, value in CONTACT.items():
            assert contact[field] == value
        assert contact["application_id"] == application["id"]

    def test_only_name_is_required(self, client, application):
        response = client.post(
            f"/applications/{application['id']}/contacts", json={"name": "Sam Ortiz"}
        )
        assert response.status_code == 201
        assert response.json()["title"] is None

    def test_name_is_required(self, client, application):
        response = client.post(
            f"/applications/{application['id']}/contacts", json={"title": "HR"}
        )
        assert response.status_code == 422

    def test_missing_application_returns_404(self, client):
        response = client.post("/applications/999999/contacts", json={"name": "Ghost"})
        assert response.status_code == 404

    def test_several_contacts_per_application(self, client, application, contact):
        client.post(
            f"/applications/{application['id']}/contacts", json={"name": "Sam Ortiz"}
        )
        body = client.get(f"/applications/{application['id']}").json()
        assert [c["name"] for c in body["contacts"]] == ["Dana Wu", "Sam Ortiz"]


class TestRead:
    def test_listed_under_their_application(self, client, application, contact):
        body = client.get(f"/applications/{application['id']}/contacts").json()
        assert len(body) == 1
        assert body[0]["name"] == "Dana Wu"

    def test_embedded_in_the_detail_response(self, client, application, contact):
        body = client.get(f"/applications/{application['id']}").json()
        assert body["contacts"][0]["name"] == "Dana Wu"

    def test_missing_application_returns_404(self, client):
        assert client.get("/applications/999999/contacts").status_code == 404


class TestUpdate:
    def test_patch_changes_only_supplied_fields(self, client, application, contact):
        response = client.patch(
            f"/applications/{application['id']}/contacts/{contact['id']}",
            json={"title": "QA Manager"},
        )
        assert response.status_code == 200
        assert response.json()["title"] == "QA Manager"
        assert response.json()["name"] == "Dana Wu"

    def test_missing_contact_returns_404(self, client, application):
        response = client.patch(
            f"/applications/{application['id']}/contacts/999999", json={"name": "X"}
        )
        assert response.status_code == 404


class TestDelete:
    def test_removes_the_contact(self, client, application, contact):
        response = client.delete(
            f"/applications/{application['id']}/contacts/{contact['id']}"
        )
        assert response.status_code == 204
        assert client.get(f"/applications/{application['id']}/contacts").json() == []

    def test_missing_contact_returns_404(self, client, application):
        response = client.delete(f"/applications/{application['id']}/contacts/999999")
        assert response.status_code == 404


class TestScoping:
    """A contact must not be reachable through another application's URL, even
    with a valid contact id."""

    @pytest.fixture
    def other_application(self, make_application):
        return make_application(company="Other Inc")

    def test_read_is_scoped(self, client, other_application, contact):
        body = client.get(f"/applications/{other_application['id']}/contacts").json()
        assert body == []

    def test_patch_through_wrong_application_returns_404(
        self, client, other_application, contact
    ):
        response = client.patch(
            f"/applications/{other_application['id']}/contacts/{contact['id']}",
            json={"name": "Hijacked"},
        )
        assert response.status_code == 404

    def test_delete_through_wrong_application_returns_404(
        self, client, other_application, contact
    ):
        response = client.delete(
            f"/applications/{other_application['id']}/contacts/{contact['id']}"
        )
        assert response.status_code == 404

    def test_the_contact_survives_those_attempts(self, client, application, contact):
        body = client.get(f"/applications/{application['id']}/contacts").json()
        assert body[0]["name"] == "Dana Wu"


def test_archiving_an_application_keeps_its_contacts(client, application, contact):
    """Applications are archived rather than deleted, so contacts stay attached
    and unarchiving restores the whole record. This replaces what used to be a
    cascade-delete test."""
    client.post(f"/applications/{application['id']}/archive")

    body = client.get(f"/applications/{application['id']}").json()
    assert [c["name"] for c in body["contacts"]] == ["Dana Wu"]
