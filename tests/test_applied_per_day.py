"""GET /applications/applied-per-day — the second insights chart (KAN-90).

The interesting property is the one that differs from the status timeline: a
day is a *count of events*, not a snapshot. A day nothing was sent on is a
real zero and must be present, where the status chart carries the previous
day's counts forward instead.
"""

from datetime import date, datetime, timedelta

from app import models
from app.database import SessionLocal


class TestAppliedPerDay:
    def series(self, client):
        response = client.get("/applications/applied-per-day")
        assert response.status_code == 200
        return response.json()["series"]

    def days(self, client):
        return {point["date"]: point["count"] for point in self.series(client)}

    def test_no_dated_applications_is_an_empty_series(
        self, client, application_payload
    ):
        # Not a 404 and not a single zeroed day, matching the status timeline.
        client.post(
            "/applications", json={**application_payload, "date_applied": None}
        )
        assert self.series(client) == []

    def test_counts_the_applications_sent_on_a_day(self, client, application_payload):
        for company in ("One", "Two", "Three"):
            client.post(
                "/applications",
                json={
                    **application_payload,
                    "company": company,
                    "date_applied": "2026-09-12",
                },
            )
        assert self.days(client)["2026-09-12"] == 3

    def test_a_quiet_day_is_a_zero_rather_than_a_gap(
        self, client, application_payload
    ):
        """The opposite of the status timeline, deliberately.

        That chart is a snapshot, so it carries the previous day forward — an
        application still sits in a status on a day nothing happened. This one
        counts events, so joining 09-12 straight to 09-15 would draw three
        days of steady activity that did not happen.
        """
        for company, day in (("One", "2026-09-12"), ("Two", "2026-09-15")):
            client.post(
                "/applications",
                json={**application_payload, "company": company, "date_applied": day},
            )

        days = self.days(client)
        assert days["2026-09-12"] == 1
        assert days["2026-09-13"] == 0
        assert days["2026-09-14"] == 0
        assert days["2026-09-15"] == 1

    def test_days_are_consecutive_with_no_repeats(self, client, application_payload):
        for company, day in (("One", "2026-09-12"), ("Two", "2026-09-20")):
            client.post(
                "/applications",
                json={**application_payload, "company": company, "date_applied": day},
            )

        dates = [date.fromisoformat(p["date"]) for p in self.series(client)]
        assert dates == sorted(dates)
        assert len(dates) == len(set(dates))
        assert all(b - a == timedelta(days=1) for a, b in zip(dates, dates[1:]))

    def test_it_runs_to_today_even_after_a_quiet_stretch(
        self, client, application_payload
    ):
        """Trailing zeros are the answer to "how am I doing lately", not
        missing data. A chart stopping at the last application would hide the
        fact that nothing has gone out since."""
        long_ago = (datetime.utcnow().date() - timedelta(days=5)).isoformat()
        client.post(
            "/applications", json={**application_payload, "date_applied": long_ago}
        )

        days = self.days(client)
        today = datetime.utcnow().date().isoformat()
        assert today in days
        assert days[today] == 0
        assert days[long_ago] == 1

    def test_a_future_date_extends_the_range_past_today(
        self, client, application_payload
    ):
        # §2 warns on a future date rather than rejecting it, so the end of
        # the range is whichever is later.
        ahead = (datetime.utcnow().date() + timedelta(days=3)).isoformat()
        client.post(
            "/applications", json={**application_payload, "date_applied": ahead}
        )

        days = self.days(client)
        assert days[ahead] == 1
        assert list(days)[-1] == ahead

    def test_undated_applications_are_absent_by_construction(
        self, client, application_payload
    ):
        """Most of the tracker is a shortlist never applied to (KAN-31), so
        this chart covers a minority of rows on purpose. It is "applications
        sent", not "activity"."""
        client.post(
            "/applications",
            json={**application_payload, "date_applied": "2026-09-12"},
        )
        for company in ("Two", "Three"):
            client.post(
                "/applications",
                json={
                    **application_payload,
                    "company": company,
                    "status": "interested",
                    "date_applied": None,
                },
            )

        assert sum(p["count"] for p in self.series(client)) == 1

    def test_archived_applications_are_excluded(self, client, application_payload):
        # KAN-76 rather than a fresh decision: archiving is how a record that
        # should never have existed is removed.
        kept = client.post(
            "/applications",
            json={**application_payload, "date_applied": "2026-09-12"},
        ).json()
        filed = client.post(
            "/applications",
            json={
                **application_payload,
                "company": "Filed",
                "date_applied": "2026-09-12",
            },
        ).json()
        client.post(f"/applications/{filed['id']}/archive")

        assert self.days(client)["2026-09-12"] == 1
        assert kept["id"] != filed["id"]

    def test_unarchiving_brings_it_back(self, client, application_payload):
        created = client.post(
            "/applications",
            json={**application_payload, "date_applied": "2026-09-12"},
        ).json()
        client.post(f"/applications/{created['id']}/archive")
        assert self.series(client) == []

        client.post(f"/applications/{created['id']}/unarchive")
        assert self.days(client)["2026-09-12"] == 1

    def test_every_status_counts_including_the_inactive_ones(
        self, client, application_payload
    ):
        """This chart answers "what did I send", and a rejection was still
        sent. Filtering by status would make the past change as outcomes
        arrive, which is the failure §4.5 rejects the funnel design for.
        """
        for company, status in (
            ("One", "applied"),
            ("Two", "rejected"),
            ("Three", "withdrawn"),
            ("Four", "posting_closed"),
        ):
            client.post(
                "/applications",
                json={
                    **application_payload,
                    "company": company,
                    "status": status,
                    "date_applied": "2026-09-12",
                },
            )

        assert self.days(client)["2026-09-12"] == 4

    def test_a_duplicate_cannot_appear(self, client, application_payload):
        """KAN-86's status marks the copy that was *not* applied to, so it
        carries no date and cannot reach this chart. Asserted rather than
        assumed, since KAN-89 is excluding duplicates from the other chart on
        this screen and the two must not be confused for one rule."""
        client.post(
            "/applications",
            json={
                **application_payload,
                "status": "duplicate",
                "date_applied": None,
            },
        )
        assert self.series(client) == []

    def test_it_is_not_read_as_an_application_id(self, client):
        # The third route in this file declared before /{application_id},
        # which is typed int and would 422 on the path segment instead.
        assert client.get("/applications/applied-per-day").status_code == 200

    def test_it_does_not_read_the_history_table(self, client, application_payload):
        """§2.2 chose `date_applied` over `status_changes` before either chart
        existed: `changed_at` is when the row was *edited*, so a batch entered
        one evening would all land on that evening. This pins the choice — the
        record is dated in the past but its history row is stamped now.
        """
        created = client.post(
            "/applications",
            json={**application_payload, "date_applied": "2026-09-12"},
        ).json()

        with SessionLocal() as db:
            rows = (
                db.query(models.StatusChange)
                .filter(models.StatusChange.application_id == created["id"])
                .all()
            )
        assert rows, "the create should have opened a history row"
        assert all(r.changed_at.date() != date(2026, 9, 12) for r in rows)

        assert self.days(client)["2026-09-12"] == 1
