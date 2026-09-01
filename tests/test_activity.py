"""The lifecycle filter: active statuses versus finished ones (KAN-62).

The archive axis has its own module for the same reason this one does — they
are independent filters that happen to both hide rows, and keeping the tests
apart keeps that independence visible.
"""

import pytest

from app import models


class TestStatusSets:
    def test_every_status_belongs_to_exactly_one_set(self):
        """INACTIVE is computed as the complement, so this is really a check
        that nothing has been added to ACTIVE that is not a real status."""
        assert models.ACTIVE_STATUSES | models.INACTIVE_STATUSES == frozenset(
            models.ApplicationStatus
        )
        assert not (models.ACTIVE_STATUSES & models.INACTIVE_STATUSES)

    def test_the_four_terminal_statuses_are_inactive(self):
        for name in ("rejected", "ghosted", "posting_closed", "withdrawn"):
            assert models.ApplicationStatus[name] in models.INACTIVE_STATUSES


class TestActivityFilter:
    @pytest.fixture(autouse=True)
    def _seed(self, make_application):
        make_application(company="Still Interested", status="interested")
        make_application(company="Waiting", status="applied")
        make_application(company="Talking", status="interview")
        make_application(company="Turned Down", status="rejected")
        make_application(company="Silent", status="ghosted")
        make_application(company="Pulled", status="posting_closed")
        make_application(company="Walked Away", status="withdrawn")

    def _companies(self, client, query=""):
        body = client.get(f"/applications{query}").json()
        return {item["company"] for item in body["items"]}, body["total"]

    def test_defaults_to_active_only(self, client):
        """The behaviour change: a finished application is not on screen when
        the page loads."""
        companies, total = self._companies(client)
        assert companies == {"Still Interested", "Waiting", "Talking"}
        assert total == 3

    def test_inactive_returns_only_finished_work(self, client):
        companies, total = self._companies(client, "?activity=inactive")
        assert companies == {"Turned Down", "Silent", "Pulled", "Walked Away"}
        assert total == 4

    def test_all_is_the_old_behaviour(self, client):
        _, total = self._companies(client, "?activity=all")
        assert total == 7

    def test_rejects_an_unknown_value(self, client):
        assert client.get("/applications?activity=finished").status_code == 422

    def test_a_status_alone_is_not_narrowed_by_the_default(self, client):
        """Asking for one status is asking for that status, whatever its
        lifecycle. Intersecting it with a default the caller never mentioned
        would make `?status=rejected` return nothing at all."""
        companies, total = self._companies(client, "?status=rejected")
        assert companies == {"Turned Down"}
        assert total == 1

    def test_an_explicit_activity_still_applies_alongside_a_status(self, client):
        """The two only stop combining when one was never asked for. Said
        together, an impossible pair is empty rather than one silently
        winning."""
        _, total = self._companies(client, "?activity=active&status=rejected")
        assert total == 0

        companies, _ = self._companies(client, "?activity=inactive&status=rejected")
        assert companies == {"Turned Down"}

    def test_is_independent_of_the_archive_filter(self, client, make_application):
        gone = make_application(company="Filed Away", status="applied")
        client.post(f"/applications/{gone['id']}/archive")

        # Active by status, but archived: hidden by the other axis.
        companies, _ = self._companies(client)
        assert "Filed Away" not in companies

        companies, _ = self._companies(client, "?show=archived")
        assert companies == {"Filed Away"}


class TestUnfilteredTotal:
    @pytest.fixture(autouse=True)
    def _seed(self, client, make_application):
        make_application(company="Waiting", status="applied")
        make_application(company="Turned Down", status="rejected")
        gone = make_application(company="Filed Away", status="applied")
        client.post(f"/applications/{gone['id']}/archive")

    def test_counts_every_row_whatever_the_filters(self, client):
        """It is what the list subtracts from to say how many rows it is not
        showing, so it has to ignore both hiding axes — including archive."""
        body = client.get("/applications").json()
        assert body["total"] == 1
        assert body["total_unfiltered"] == 3

    def test_does_not_move_with_the_filters(self, client):
        for query in ("", "?activity=all", "?activity=inactive", "?show=all",
                      "?search=Waiting"):
            body = client.get(f"/applications{query}").json()
            assert body["total_unfiltered"] == 3, query

    def test_is_unaffected_by_paging(self, client):
        """`total` is the filtered count, not the page — the count line would
        be wrong on any list past its first page otherwise."""
        body = client.get("/applications?activity=all&show=all&limit=1").json()
        assert len(body["items"]) == 1
        assert body["total"] == 3
        assert body["total_unfiltered"] == 3
