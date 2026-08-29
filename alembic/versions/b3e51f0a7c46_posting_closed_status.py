"""a posting_closed status

A saved posting can turn out to be gone — pulled, filled, or expired — and
there was no status for it (KAN-57). The nearest existing value, `rejected`,
asserts that somebody considered the candidate and said no; when an ad is
withdrawn nobody decided anything, and often the application was never sent.
Recording it as a rejection would overstate the rejections in the search and
corrupt the history KAN-42 exists to make answerable later.

Appended to the enum rather than placed with the other terminal states, for
the same reason `interested` was appended in 4500fe76cbd9: MySQL and MariaDB
store an ENUM as its ordinal, so appending is the only change that leaves
existing rows meaning what they meant. Display order is the frontend's, in
STATUS_LABELS.

Revision ID: b3e51f0a7c46
Revises: 9c1e7d4b8a52
Create Date: 2026-08-29 17:02:44.318905

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e51f0a7c46'
down_revision: Union[str, Sequence[str], None] = '9c1e7d4b8a52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_STATUSES = (
    "applied",
    "phone_screen",
    "interview",
    "offer",
    "rejected",
    "ghosted",
    "withdrawn",
    "interested",
)

_NEW_STATUSES = _OLD_STATUSES + ("posting_closed",)


def _status_enum(values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name="applicationstatus")


def upgrade() -> None:
    """Upgrade schema.

    Both the applications table and the status_changes table carry the enum —
    status_changes has two columns of it — so all three have to move together
    or a transition into the new status could not be recorded.

    batch_alter_table for the reason every revision since KAN-31 has used it:
    SQLite cannot ALTER a column in place and the tests run on SQLite, while
    on MariaDB batch mode emits a plain ALTER. One code path, no dialect
    branch.
    """
    with op.batch_alter_table("applications") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=_status_enum(_OLD_STATUSES),
            type_=_status_enum(_NEW_STATUSES),
            existing_nullable=False,
        )

    with op.batch_alter_table("status_changes") as batch_op:
        batch_op.alter_column(
            "from_status",
            existing_type=_status_enum(_OLD_STATUSES),
            type_=_status_enum(_NEW_STATUSES),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "to_status",
            existing_type=_status_enum(_OLD_STATUSES),
            type_=_status_enum(_NEW_STATUSES),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema.

    Refuses while anything holds the new value, consistent with every revision
    since KAN-31. There is no honest replacement: `rejected` is the wrong fact
    and is precisely what this status exists to avoid recording, and silently
    rewriting history rows would be worse still.

    Both tables are counted. A history row can hold the value even when no
    application currently does — the application moved on afterwards — and
    dropping it from the enum would corrupt that row rather than the current
    state.
    """
    bind = op.get_bind()
    applications = bind.execute(
        sa.text("SELECT COUNT(*) FROM applications WHERE status = 'posting_closed'")
    ).scalar()
    history = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM status_changes "
            "WHERE to_status = 'posting_closed' OR from_status = 'posting_closed'"
        )
    ).scalar()

    if applications or history:
        raise RuntimeError(
            f"Refusing to downgrade: {applications} application(s) and "
            f"{history} history row(s) use 'posting_closed'. There is no "
            "honest status to move them to — 'rejected' is the wrong fact, "
            "and is what this status exists to avoid recording. Reassign them "
            "first if that is genuinely what you want."
        )

    with op.batch_alter_table("status_changes") as batch_op:
        batch_op.alter_column(
            "to_status",
            existing_type=_status_enum(_NEW_STATUSES),
            type_=_status_enum(_OLD_STATUSES),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "from_status",
            existing_type=_status_enum(_NEW_STATUSES),
            type_=_status_enum(_OLD_STATUSES),
            existing_nullable=True,
        )

    with op.batch_alter_table("applications") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=_status_enum(_NEW_STATUSES),
            type_=_status_enum(_OLD_STATUSES),
            existing_nullable=False,
        )
