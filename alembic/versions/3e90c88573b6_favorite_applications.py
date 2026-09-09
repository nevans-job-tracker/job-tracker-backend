"""favorite applications

Adds `is_favorite` (KAN-81), a third axis alongside status and archived_at
and independent of both: "this is one of the good ones" is a judgement laid
across the application's lifecycle rather than a stage in it, and archive
already carries whether a record should still be in view.

NOT NULL, defaulting to false — the `pay_period` reasoning rather than
`employment_type`'s (see 9c1e7d4b8a52). Every record either is or is not a
favorite, so there is no honest "unset" the way there is for a pay period
never stated. Defaulting every existing row to false is also what makes the
column safe for the extension, which POSTs to /applications without knowing
it exists: pydantic ignores unknown fields, and an unrecognised column would
only be dangerous if a NOT NULL addition had no server-side default.

It writes no history — status_changes is not touched by this revision.
`is_favorite` is not a lifecycle event, and putting a toggled preference in
that table would bury real transitions under taste.

Revision ID: 3e90c88573b6
Revises: bc35cc0e64a5
Create Date: 2026-09-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3e90c88573b6'
down_revision: Union[str, Sequence[str], None] = 'bc35cc0e64a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    batch_alter_table for the same reason as every revision since KAN-31:
    SQLite cannot ALTER a column in place and the tests run on SQLite, while
    on MariaDB batch mode emits a plain ALTER.
    """
    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_favorite",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    """Downgrade schema.

    Refuses rather than guesses, consistent with every revision since KAN-31.
    An untouched database — nothing ever starred — downgrades cleanly; one
    with any favorite marked does not, because dropping the column would
    discard which applications were starred with nothing left to recover it
    from.
    """
    blocking = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM applications WHERE is_favorite = 1")
    ).scalar()

    if blocking:
        raise RuntimeError(
            f"Refusing to downgrade: {blocking} application(s) are marked a "
            "favorite, and dropping this column would discard that with "
            "nothing left to recover it from. Clear the flag first if that "
            "is genuinely what you want."
        )

    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("is_favorite")
