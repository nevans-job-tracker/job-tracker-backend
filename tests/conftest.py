"""Shared test fixtures.

The DATABASE_URL override must be set before app.config is imported, because
Settings is instantiated at import time and everything downstream — the engine,
and Alembic's env.py — reads the URL from it. Importing the app inside the
fixtures below keeps that order correct no matter which test module runs first.
"""
import os
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

TEST_DB = Path(tempfile.gettempdir()) / "job_tracker_test.sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

if TEST_DB.exists():
    TEST_DB.unlink()

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Build the schema the same way production does — by migrating.

    This deliberately does *not* call Base.metadata.create_all, even though
    that would be marginally faster. create_all builds the schema from the
    models, so it would pass whether or not the migrations actually work,
    leaving the one mechanism that runs in production untested. Migrating here
    means a revision that does not apply cleanly fails the suite instead of
    failing a deploy.

    Alembic reads the URL from the same Settings the app does, so the
    DATABASE_URL set above sends it at the throwaway SQLite file rather than
    any real database.

    Tearing down with `downgrade base` rather than drop_all exercises the
    downgrade path too, which is otherwise never run.
    """
    config = Config(str(ALEMBIC_INI))
    command.upgrade(config, "head")
    yield
    command.downgrade(config, "base")


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
