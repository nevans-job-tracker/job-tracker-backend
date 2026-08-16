"""Direct checks on the crud layer for paths the HTTP routes no longer reach.

The routes verify existence before delegating, so crud's own "not found" guards
are unreachable through the API. They still matter to anything calling crud
directly, so they are exercised here.
"""
from app import crud, schemas
from app.database import SessionLocal


def _session():
    return SessionLocal()


def test_get_application_returns_none_when_missing():
    with _session() as db:
        assert crud.get_application(db, 999999) is None


def test_update_application_returns_none_when_missing():
    with _session() as db:
        result = crud.update_application(
            db, 999999, schemas.ApplicationUpdate(company="Nowhere")
        )
    assert result is None


def test_set_archived_returns_none_when_missing():
    with _session() as db:
        assert crud.set_archived(db, 999999, True) is None


def test_update_contact_returns_none_when_missing():
    with _session() as db:
        result = crud.update_contact(
            db, 999999, 999999, schemas.ContactUpdate(name="Nobody")
        )
    assert result is None


def test_delete_contact_returns_false_when_missing():
    with _session() as db:
        assert crud.delete_contact(db, 999999, 999999) is False


def test_get_contact_is_scoped_to_its_application(client, make_application):
    """The same guard the API relies on, checked at the source: a real contact
    id must not resolve under a different application."""
    owner = make_application()
    other = make_application(company="Other Inc")
    created = client.post(
        f"/applications/{owner['id']}/contacts", json={"name": "Dana Wu"}
    ).json()

    with _session() as db:
        assert crud.get_contact(db, owner["id"], created["id"]) is not None
        assert crud.get_contact(db, other["id"], created["id"]) is None
