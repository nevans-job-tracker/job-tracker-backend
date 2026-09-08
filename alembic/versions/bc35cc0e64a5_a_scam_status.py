"""a scam status

Some postings turn out to be fraudulent (KAN-79), and there was no honest
value for one. The nearest, `posting_closed`, says a real opportunity ended —
pulled, filled, or expired. A scam is the opposite claim: there was never an
opportunity to end. Filing them together would overstate how many genuine
roles the search actually saw, and would corrupt any later question about how
many postings closed on their own.

`rejected` and `ghosted` are wrong for the reason KAN-57 already recorded for
`posting_closed`: both assert something about how a real employer treated the
candidate.

Appended to the enum rather than placed with the other terminal states, for
the same reason `interested` was in 4500fe76cbd9 and `posting_closed` in
b3e51f0a7c46: MySQL and MariaDB store an ENUM as its ordinal, so appending is
the only change that leaves existing rows meaning what they meant. Display
order is the frontend's, in STATUS_LABELS.

It needs no lifecycle change. Both ACTIVE_STATUSES complements — the model's
and the frontend's — compute the inactive set rather than listing it, so a
value added here is inactive by construction (KAN-62).

Revision ID: bc35cc0e64a5
Revises: b3e51f0a7c46
Create Date: 2026-09-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc35cc0e64a5'
down_revision: Union[str, Sequence[str], None] = 'b3e51f0a7c46'
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
    "posting_closed",
)

_NEW_STATUSES = _OLD_STATUSES + ("scam",)


def _status_enum(values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name="applicationstatus")


def upgrade() -> None:
    """Upgrade schema.

    Three columns, because status_changes carries the enum twice. All of them
    move together or a transition *into* the new status could not be recorded —
    the same trap b3e51f0a7c46 documents.

    batch_alter_table for the reason every revision since KAN-31 has used it:
    SQLite cannot ALTER a column in place and the tests run on SQLite, while on
    MariaDB batch mode emits a plain ALTER. One code path, no dialect branch.
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
    since KAN-31. There is no honest replacement: `posting_closed` would assert
    the opportunity was real, and `rejected` would assert an employer
    considered the candidate. Both are the false facts this status exists to
    stop recording.

    Both tables are counted. A history row can hold the value when no
    application currently does — the record moved on afterwards — and dropping
    it from the enum would corrupt that row rather than the current state.
    """
    bind = op.get_bind()
    applications = bind.execute(
        sa.text("SELECT COUNT(*) FROM applications WHERE status = 'scam'")
    ).scalar()
    history = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM status_changes "
            "WHERE to_status = 'scam' OR from_status = 'scam'"
        )
    ).scalar()

    if applications or history:
        raise RuntimeError(
            f"Refusing to downgrade: {applications} application(s) and "
            f"{history} history row(s) use 'scam'. There is no honest status "
            "to move them to — 'posting_closed' would claim the opportunity "
            "was real and 'rejected' would claim an employer considered you. "
            "Reassign them first if that is genuinely what you want."
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
