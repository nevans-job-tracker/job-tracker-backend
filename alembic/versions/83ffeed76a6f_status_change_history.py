"""status change history

Records every status transition, so time-in-stage and status-over-time become
answerable later (KAN-42). Nothing reads this yet — the recording ships first
because it is the only part with a deadline. History cannot be reconstructed
after the fact, so every day without this table is a day that will always be
missing from any timeline built on it.

The backfill is deliberately minimal. We know each existing application's
current status and when the row was created, but *not how it got there* — so a
row claiming `created_at -> current status` would be fiction for anything that
has already moved. Instead each existing application gets one row stamped now,
with a NULL from_status, claiming only "as of this migration, it is this".
That is true, it gives every application an origin to measure forward from, and
it invents nothing.

Revision ID: 83ffeed76a6f
Revises: 53f76402812f
Create Date: 2026-08-23 11:26:41.905522

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '83ffeed76a6f'
down_revision: Union[str, Sequence[str], None] = '53f76402812f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUSES = (
    "applied",
    "phone_screen",
    "interview",
    "offer",
    "rejected",
    "ghosted",
    "withdrawn",
    "interested",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "status_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        # NULL means "this is where the history starts" rather than a
        # transition — either the application was just created, or it predates
        # this table.
        sa.Column(
            "from_status",
            sa.Enum(*_STATUSES, name="applicationstatus"),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            sa.Enum(*_STATUSES, name="applicationstatus"),
            nullable=False,
        ),
        sa.Column("changed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_status_changes_id", "status_changes", ["id"], unique=False)
    # The timeline reads one application in order; the graph reads a date range
    # for one status. One index each.
    op.create_index(
        "ix_status_changes_application",
        "status_changes",
        ["application_id", "changed_at"],
        unique=False,
    )
    op.create_index(
        "ix_status_changes_status_date",
        "status_changes",
        ["to_status", "changed_at"],
        unique=False,
    )

    # Open a history for everything that already exists. `changed_at` defaults
    # to now rather than to created_at, because now is the only thing we can
    # honestly assert about a record whose path we never observed.
    op.execute(
        "INSERT INTO status_changes (application_id, from_status, to_status, changed_at) "
        "SELECT id, NULL, status, CURRENT_TIMESTAMP FROM applications"
    )


def downgrade() -> None:
    """Downgrade schema.

    Refuses if the table holds anything, and the reason is stronger here than
    for the three revisions before it. Those dropped columns whose values could
    at least be retyped from a job posting. This is the *only* copy of when
    each status changed — nothing anywhere else can regenerate it, so dropping
    a populated table would be permanent in a way nothing else in this schema
    is.
    """
    rows = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM status_changes")
    ).scalar()

    if rows:
        raise RuntimeError(
            f"Refusing to downgrade: status_changes holds {rows} row(s), and it "
            "is the only record of when each status changed. Nothing else can "
            "regenerate it. Empty the table first if that is genuinely what "
            "you want."
        )

    op.drop_index("ix_status_changes_status_date", table_name="status_changes")
    op.drop_index("ix_status_changes_application", table_name="status_changes")
    op.drop_index("ix_status_changes_id", table_name="status_changes")
    op.drop_table("status_changes")
