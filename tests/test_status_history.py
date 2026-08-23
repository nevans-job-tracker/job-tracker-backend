"""Status change history (KAN-42).

Nothing reads this table yet, which is exactly why it needs tests: a gap in the
recording would be invisible until someone builds a timeline months from now,
against history that can never be reconstructed.
"""
import ast
import inspect

from app import crud, models


def history(client, application_id):
    """Reads the table directly — there is deliberately no endpoint yet."""
    from app.database import SessionLocal

    with SessionLocal() as db:
        return [
            (row.from_status, row.to_status)
            for row in db.query(models.StatusChange)
            .filter(models.StatusChange.application_id == application_id)
            .order_by(models.StatusChange.changed_at, models.StatusChange.id)
            .all()
        ]


class TestRecording:
    def test_a_create_opens_the_history(self, client, application_payload):
        created = client.post("/applications", json=application_payload).json()
        assert history(client, created["id"]) == [
            (None, models.ApplicationStatus.applied)
        ]

    def test_the_opening_row_has_no_from_status(self, client, make_application):
        """An application does not transition into existence, so NULL is the
        honest value rather than inventing a status it came from."""
        created = make_application()
        assert history(client, created["id"])[0][0] is None

    def test_an_undated_create_records_interested(self, client):
        """The status actually stored is what gets recorded, not the one the
        request asked for — a dateless create is reinterpreted (§3)."""
        created = client.post(
            "/applications", json={"company": "Acme", "role_title": "SDET"}
        ).json()
        assert history(client, created["id"]) == [
            (None, models.ApplicationStatus.interested)
        ]

    def test_a_change_is_recorded_with_where_it_came_from(
        self, client, make_application
    ):
        created = make_application()
        client.patch(
            f"/applications/{created['id']}", json={"status": "phone_screen"}
        )
        assert history(client, created["id"]) == [
            (None, models.ApplicationStatus.applied),
            (models.ApplicationStatus.applied, models.ApplicationStatus.phone_screen),
        ]

    def test_every_step_of_a_lifecycle_is_kept(self, client, make_application):
        created = make_application()
        for status in ["phone_screen", "interview", "offer"]:
            client.patch(f"/applications/{created['id']}", json={"status": status})

        assert [to for _, to in history(client, created["id"])] == [
            models.ApplicationStatus.applied,
            models.ApplicationStatus.phone_screen,
            models.ApplicationStatus.interview,
            models.ApplicationStatus.offer,
        ]

    def test_going_backwards_is_recorded_like_any_other_move(
        self, client, make_application
    ):
        """§3 allows any status to follow any other. A timeline that assumed a
        monotonic lifecycle would be wrong about real data."""
        created = make_application()
        client.patch(f"/applications/{created['id']}", json={"status": "rejected"})
        client.patch(f"/applications/{created['id']}", json={"status": "interview"})

        assert history(client, created["id"])[-1] == (
            models.ApplicationStatus.rejected,
            models.ApplicationStatus.interview,
        )


class TestWhatIsNotRecorded:
    def test_setting_the_same_status_again_records_nothing(
        self, client, make_application
    ):
        """The detail screen sends every field on every save, so the status
        arrives unchanged constantly. Recording those would bury the real
        transitions and make every computed duration read as zero."""
        created = make_application()
        for _ in range(3):
            client.patch(f"/applications/{created['id']}", json={"status": "applied"})

        assert len(history(client, created["id"])) == 1

    def test_editing_other_fields_records_nothing(self, client, make_application):
        created = make_application()
        client.patch(
            f"/applications/{created['id']}",
            json={"notes": "Spoke to the recruiter", "next_action": "Follow up"},
        )
        assert len(history(client, created["id"])) == 1

    def test_archiving_records_nothing(self, client, make_application):
        """Archive is an axis of its own, independent of status (§4.1)."""
        created = make_application()
        client.post(f"/applications/{created['id']}/archive")
        client.post(f"/applications/{created['id']}/unarchive")
        assert len(history(client, created["id"])) == 1


class TestIsolation:
    def test_history_belongs_to_its_own_application(self, client, make_application):
        first = make_application(company="Alpha")
        second = make_application(company="Bravo")
        client.patch(f"/applications/{first['id']}", json={"status": "offer"})

        assert len(history(client, first["id"])) == 2
        assert len(history(client, second["id"])) == 1

    def test_the_list_and_detail_responses_are_unchanged(
        self, client, make_application
    ):
        """This story ships no UI and no API surface. If `status_changes` leaks
        into a response, the story has done more than it claimed."""
        created = make_application()
        assert "status_changes" not in client.get("/applications").json()["items"][0]
        assert "status_changes" not in client.get(f"/applications/{created['id']}").json()


class TestHistoryEndpoint:
    """GET /applications/{id}/history — what the timeline reads (KAN-43)."""

    def test_returns_the_opening_row(self, client, make_application):
        created = make_application()
        body = client.get(f"/applications/{created['id']}/history").json()
        assert len(body) == 1
        assert body[0]["from_status"] is None
        assert body[0]["to_status"] == "applied"
        assert body[0]["changed_at"]

    def test_returns_changes_oldest_first(self, client, make_application):
        created = make_application()
        for status in ["phone_screen", "interview"]:
            client.patch(f"/applications/{created['id']}", json={"status": status})

        body = client.get(f"/applications/{created['id']}/history").json()
        assert [r["to_status"] for r in body] == [
            "applied",
            "phone_screen",
            "interview",
        ]

    def test_a_repeated_status_appears_every_time(self, client, make_application):
        """§3 allows any transition, so a status recurring is ordinary — the
        timeline renders three entries rather than deduplicating."""
        created = make_application()
        for status in ["rejected", "interview", "rejected"]:
            client.patch(f"/applications/{created['id']}", json={"status": status})

        body = client.get(f"/applications/{created['id']}/history").json()
        assert [r["to_status"] for r in body].count("rejected") == 2

    def test_only_this_application_s_history(self, client, make_application):
        first = make_application(company="Alpha")
        second = make_application(company="Bravo")
        client.patch(f"/applications/{first['id']}", json={"status": "offer"})

        assert len(client.get(f"/applications/{first['id']}/history").json()) == 2
        assert len(client.get(f"/applications/{second['id']}/history").json()) == 1

    def test_missing_application_returns_404(self, client):
        assert client.get("/applications/999999/history").status_code == 404

    def test_history_is_still_absent_from_the_detail_response(
        self, client, make_application
    ):
        """The endpoint is separate on purpose. Embedding it in ApplicationOut
        would make the CSV export lazily load history per row — the N+1 §2.1
        exists to prevent."""
        created = make_application()
        detail = client.get(f"/applications/{created['id']}").json()
        assert "status_changes" not in detail
        assert "history" not in detail

    def test_the_csv_export_fetch_does_not_carry_history(
        self, client, make_application
    ):
        make_application()
        row = client.get("/applications?include_contacts=true").json()["items"][0]
        assert "status_changes" not in row


def test_only_two_paths_change_a_status():
    """Pins the assumption the recording rests on.

    `_record_status` is called explicitly rather than from an ORM event, so it
    only fires where someone remembered to call it. If a third function starts
    assigning `.status`, history goes silently incomplete — nothing would look
    wrong until a timeline built months later turned out to have holes.

    This reads the source rather than the behaviour, because the failure being
    guarded against is code that does not exist yet.
    """
    source = inspect.getsource(crud)
    tree = ast.parse(source)

    def writes_attributes(fn_node):
        """True if the function assigns an attribute, directly or via setattr.

        Parsed rather than grepped: `list_applications` contains `.status ==`,
        and a substring check reads that comparison as an assignment and cries
        wolf. A guard that fires when nothing is wrong gets disabled.
        """
        for node in ast.walk(fn_node):
            if isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Attribute) for t in node.targets):
                    return True
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "setattr"
            ):
                return True
        return False

    assigns = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and writes_attributes(node)
    }
    assert assigns == {"update_application", "update_contact", "set_archived"}, (
        "A function in crud.py now assigns attributes. If it can set an "
        "application's status, it must call _record_status too, or history "
        f"goes silently incomplete — see KAN-42. Found: {sorted(assigns)}"
    )
    # And the two recording sites are still there.
    assert source.count("_record_status(") == 3  # one definition, two calls
