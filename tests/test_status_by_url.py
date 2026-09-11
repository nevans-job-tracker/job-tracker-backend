"""The manual close-posting extension must update exactly one intended record."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import crud, models


URL = "https://www.indeed.com/viewjob?jk=AbC123"
ENDPOINT = "/applications/by-url/status"


def close(client, url=URL):
    return client.patch(ENDPOINT, json={"job_link": url, "status": "posting_closed"})


def history(client, app_id):
    response = client.get(f"/applications/{app_id}/history")
    assert response.status_code == 200
    return response.json()


def test_close_preserves_record_and_records_one_transition(client, make_application):
    created = make_application(
        job_link=URL, status="interested", date_applied=None, next_action="Apply",
        next_action_date="2026-09-20", notes="Keep these notes", is_favorite=True,
        salary_min=100000, salary_max=120000, job_description="Original posting",
    )
    contact = client.post(
        f"/applications/{created['id']}/contacts", json={"name": "Recruiter"}
    )
    assert contact.status_code == 201
    before = client.get(f"/applications/{created['id']}").json()
    result = close(client)
    assert result.status_code == 200, result.text
    assert result.json() == {
        "id": created["id"], "company": created["company"],
        "role_title": created["role_title"], "job_link": URL,
        "status": "posting_closed", "changed": True,
    }
    after = client.get(f"/applications/{created['id']}").json()
    assert after["status"] == "posting_closed"
    for key in before.keys() - {"status", "updated_at"}:
        assert after[key] == before[key], key
    changes = history(client, created["id"])
    assert len(changes) == 2
    assert changes[-1]["from_status"] == "interested"
    assert changes[-1]["to_status"] == "posting_closed"
    repeated = close(client)
    assert repeated.status_code == 200
    assert repeated.json()["changed"] is False
    assert history(client, created["id"]) == changes


@pytest.mark.parametrize("status", [s.value for s in models.ApplicationStatus])
def test_any_existing_status_can_be_closed(client, make_application, status):
    created = make_application(job_link=URL, status=status)
    result = close(client)
    assert result.status_code == 200
    assert result.json()["changed"] is (status != "posting_closed")
    assert len(history(client, created["id"])) == (1 if status == "posting_closed" else 2)


def test_missing_url_does_not_create_or_change_an_application(client, make_application):
    created = make_application(job_link=None)
    assert close(client).status_code == 404
    assert client.get("/applications?activity=all&show=all").json()["total"] == 1
    assert client.get(f"/applications/{created['id']}").json() == created
    assert len(history(client, created["id"])) == 1


@pytest.mark.parametrize("archive_duplicate", [False, True])
def test_ambiguous_url_never_selects_first_match(client, make_application, archive_duplicate):
    first = make_application(job_link=URL)
    second = make_application(job_link=URL, company="Another company")
    if archive_duplicate:
        client.post(f"/applications/{second['id']}/archive")
    result = close(client)
    assert result.status_code == 409
    assert f"#{first['id']}" in result.json()["detail"]
    assert f"#{second['id']}" in result.json()["detail"]
    for row in [first, second]:
        assert client.get(f"/applications/{row['id']}").json()["status"] == row["status"]
        assert len(history(client, row["id"])) == 1


def test_archived_match_stays_archived_and_unchanged(client, make_application):
    created = make_application(job_link=URL)
    before = client.post(f"/applications/{created['id']}/archive").json()
    result = close(client)
    assert result.status_code == 409
    assert "archived" in result.json()["detail"]
    assert client.get(f"/applications/{created['id']}").json() == before
    assert len(history(client, created["id"])) == 1


@pytest.mark.parametrize("url", [
    URL.lower(), URL + "&utm_source=tracker", URL + "#details",
    "https://www.indeed.com/viewjob/?jk=AbC123",
    "http://www.indeed.com/viewjob?jk=AbC123",
    "https://www.indeed.com/ViewJob?jk=AbC123",
    "https://www.indeed.com/viewjob?jk=AbC1234",
])
def test_url_variations_do_not_match(client, make_application, url):
    created = make_application(job_link=URL)
    assert close(client, url).status_code == 404
    assert client.get(f"/applications/{created['id']}").json()["status"] == created["status"]


def test_python_equality_rejects_loose_database_candidates():
    # Simulate a case-insensitive/trailing-space-insensitive DB collation.
    exact = SimpleNamespace(id=2, job_link=URL)
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [
        SimpleNamespace(id=1, job_link=URL.lower()), exact,
        SimpleNamespace(id=3, job_link=URL + " "),
    ]
    assert crud.find_applications_by_exact_url(db, URL) == [exact]


@pytest.mark.parametrize("payload", [
    {}, {"job_link": URL}, {"status": "posting_closed"},
    {"job_link": None, "status": "posting_closed"},
    {"job_link": "", "status": "posting_closed"},
    {"job_link": "   ", "status": "posting_closed"},
    {"job_link": "javascript:alert(1)", "status": "posting_closed"},
    {"job_link": "file:///posting.html", "status": "posting_closed"},
    {"job_link": "/relative/path", "status": "posting_closed"},
    {"job_link": "https://example.com/" + "x" * 1024, "status": "posting_closed"},
    {"job_link": URL, "status": "rejected"},
    {"job_link": URL, "status": None},
    {"job_link": URL, "status": "posting_closed", "notes": "Unexpected edit"},
])
def test_invalid_payload_cannot_write(client, make_application, payload):
    created = make_application(job_link=URL)
    assert client.patch(ENDPOINT, json=payload).status_code == 422
    assert client.get(f"/applications/{created['id']}").json() == created
    assert len(history(client, created["id"])) == 1
