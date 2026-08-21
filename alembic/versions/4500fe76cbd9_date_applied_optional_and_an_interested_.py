"""date_applied optional, and an 'interested' status

Lets the tracker hold a job before it has been applied to (KAN-31). Two
changes that have to land together: a record with no `date_applied` needs a
status that says why, and `interested` is meaningless while every record must
carry a date.

The first revision that *alters* an existing table — the baseline only created
them — so a few things are deliberate rather than incidental:

  * `interested` is **appended** to the enum rather than inserted at the front
    where it belongs in the lifecycle. MySQL and MariaDB store an ENUM as its
    ordinal, and appending is the one modification they can make without
    reinterpreting existing rows. Display order is the frontend's business;
    `STATUS_LABELS` lists it first regardless.

  * `batch_alter_table` for both changes. SQLite cannot ALTER a column in
    place, and the test suite runs on SQLite; on MariaDB batch mode emits a
    plain ALTER, so this is one code path rather than a dialect branch.

  * The downgrade refuses rather than guesses. Reversing this is lossy — there
    is no honest date for a record that never had one, and no status to
    demote `interested` to. It checks first and raises, so a downgrade either
    reverses cleanly or does nothing at all.

Revision ID: 4500fe76cbd9
Revises: de0ac7356ab2
Create Date: 2026-08-21 10:41:22.108733

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4500fe76cbd9'
down_revision: Union[str, Sequence[str], None] = 'de0ac7356ab2'
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
)
_NEW_STATUSES = _OLD_STATUSES + ("interested",)


def _status_enum(values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name="applicationstatus")


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("applications") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=_status_enum(_OLD_STATUSES),
            type_=_status_enum(_NEW_STATUSES),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "date_applied",
            existing_type=sa.Date(),
            nullable=True,
        )


def downgrade() -> None:
    """Downgrade schema.

    Refuses if anything in the table depends on what this revision added.
    Restoring NOT NULL over a NULL would mean inventing a date the user never
    supplied, and MySQL outside strict mode would quietly write 0000-00-00
    rather than complain.
    """
    blocking = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM applications "
            "WHERE date_applied IS NULL OR status = 'interested'"
        )
    ).scalar()

    if blocking:
        raise RuntimeError(
            f"Refusing to downgrade: {blocking} application(s) have no date "
            "applied or are marked 'interested', and this revision is what "
            "makes those representable. Give them a date and a different "
            "status first — there is no correct value to invent here."
        )

    with op.batch_alter_table("applications") as batch_op:
        batch_op.alter_column(
            "date_applied",
            existing_type=sa.Date(),
            nullable=False,
        )
        batch_op.alter_column(
            "status",
            existing_type=_status_enum(_NEW_STATUSES),
            type_=_status_enum(_OLD_STATUSES),
            existing_nullable=False,
        )
