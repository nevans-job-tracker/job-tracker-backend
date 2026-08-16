"""Shared test fixtures.

The DATABASE_URL override must be set before app.config is imported, because
Settings is instantiated at import time and app.main calls create_all() on the
resulting engine. Importing the app inside the fixtures below keeps that order
correct no matter which test module runs first.
"""
import os
import tempfile
from pathlib import Path

import pytest

TEST_DB = Path(tempfile.gettempdir()) / "job_tracker_test.sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

if TEST_DB.exists():
    TEST_DB.unlink()

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    """Every test starts from an empty database, so tests can't depend on
    ordering or leak rows into each other."""
    yield
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def application_payload():
    return {
        "company": "Acme Corp",
        "role_title": "Senior QA Engineer",
        "date_applied": "2026-08-01",
    }


@pytest.fixture
def make_application(client, application_payload):
    """Creates an application and returns the response body."""

    def _make(**overrides):
        response = client.post(
            "/applications", json={**application_payload, **overrides}
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _make
