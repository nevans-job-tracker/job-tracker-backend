"""a duplicate status

The same job reaches the tracker twice (KAN-86) — saved once from LinkedIn and
once from another source — and only one of the two is applied to. There was no
honest value for the other.

Every existing status describes the application or the posting. This one
describes the *record*: nothing is wrong with the opportunity, it is simply
being held more than once. `posting_closed` would claim a real opportunity
ended, `withdrawn` would claim the candidate pulled out, and `rejected` and
`ghosted` would claim an employer did something — the same three wrong facts
KAN-57 and KAN-79 already recorded.

Archiving hides such a row but records only *that* it should be out of view,
not *why* (REQUIREMENTS §4.1). The two axes compose rather than compete, and a
duplicate usually wants both.

Appended to the enum rather than placed with the other terminal states, for the
same reason `interested` was in 4500fe76cbd9, `posting_closed` in b3e51f0a7c46
and `scam` in bc35cc0e64a5: MySQL and MariaDB store an ENUM as its ordinal, so
appending is the only change that leaves existing rows meaning what they meant.
Display order is the frontend's, in STATUS_LABELS.

It needs no lifecycle change. Both ACTIVE_STATUSES complements — the model's
and the frontend's — compute the inactive set rather than listing it, so a
value added here is inactive by construction (KAN-62).

It needs no insights change either, and that is a decision rather than an
omission. No status is excluded from the chart; the only exclusion is KAN-76's,
which filters on the *record* being archived. Carving out the first per-status
exception would turn "this is what the tracker held on these days" into "except
the statuses we decided not to count". Archiving a duplicate already removes it
from every day, so the escape hatch exists and there is no second mechanism to
keep in agreement with the first.

Revision ID: d9f47a2c1b63
Revises: 3e90c88573b6
Create Date: 2026-09-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9f47a2c1b63'
down_revision: Union[str, Sequence[str], None] = '3e90c88573b6'
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
    "scam",
)

_NEW_STATUSES = _OLD_STATUSES + ("duplicate",)


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
    since KAN-31. There is no honest replacement: every other status makes a
    claim about the application or the posting, and the fact being recorded
    here is about the record itself.

    Archiving is the nearest thing a downgrade could reach for, and it is not
    equivalent — it would move the row out of view while losing the reason, and
    it is a different column besides. Reassigning by hand is the honest answer.

    Both tables are counted. A history row can hold the value when no
    application currently does — the record moved on afterwards — and dropping
    it from the enum would corrupt that row rather than the current state.
    """
    bind = op.get_bind()
    applications = bind.execute(
        sa.text("SELECT COUNT(*) FROM applications WHERE status = 'duplicate'")
    ).scalar()
    history = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM status_changes "
            "WHERE to_status = 'duplicate' OR from_status = 'duplicate'"
        )
    ).scalar()

    if applications or history:
        raise RuntimeError(
            f"Refusing to downgrade: {applications} application(s) and "
            f"{history} history row(s) use 'duplicate'. Every other status "
            "claims something about the application or the posting, and this "
            "one is about the record, so there is nothing honest to move them "
            "to. Reassign them first if that is genuinely what you want."
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
