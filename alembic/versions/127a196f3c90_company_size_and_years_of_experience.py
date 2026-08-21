"""company size and years of experience

Two fields wanted for judging fit at a glance and filtering later (KAN-35,
KAN-32). They ship as one revision because they are one deploy and one restart;
splitting them would mean two ALTERs on the same table minutes apart for no
benefit.

  * `company_size` — Wellfound's six bands, as an enum. The values are known,
    closed, externally defined and bounded by employee count, so any company
    maps to exactly one. This is the opposite case to `source`, which
    REQUIREMENTS.md §2 deliberately left as free text because its real values
    were not yet known.

    Declaration order is smallest-to-largest, which matters on MySQL and
    MariaDB: they store an ENUM as its ordinal, so `ORDER BY company_size`
    gives band order rather than alphabetical. Unlike the `interested` status
    added in 4500fe76cbd9, this order is right from the start and there is
    nothing to append around.

  * `years_experience_min` — a nullable small integer. "3-5 years" and "5+"
    both store as the minimum.

Both nullable: a posting often states neither, and guessing is worse than
leaving it blank.

`op.add_column` needs no batch wrapper — plain ALTER ADD COLUMN works on every
dialect here. The downgrade does use batch, because dropping a column is the
half SQLite has historically not supported in place.

Revision ID: 127a196f3c90
Revises: 4500fe76cbd9
Create Date: 2026-08-21 11:08:44.510221

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '127a196f3c90'
down_revision: Union[str, Sequence[str], None] = '4500fe76cbd9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COMPANY_SIZES = ("seed", "early", "mid_size", "large", "very_large", "massive")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "applications",
        sa.Column(
            "company_size",
            sa.Enum(*_COMPANY_SIZES, name="companysize"),
            nullable=True,
        ),
    )
    op.add_column(
        "applications",
        sa.Column("years_experience_min", sa.SmallInteger(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema.

    Refuses if either column holds anything. Dropping a column is not a lossy
    conversion that could be argued about — the values simply cease to exist,
    with no record that they ever did. Same stance as 4500fe76cbd9: a
    downgrade either reverses cleanly or does nothing at all.
    """
    blocking = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM applications "
            "WHERE company_size IS NOT NULL OR years_experience_min IS NOT NULL"
        )
    ).scalar()

    if blocking:
        raise RuntimeError(
            f"Refusing to downgrade: {blocking} application(s) record a company "
            "size or a years-of-experience minimum, and dropping these columns "
            "would discard those values with nothing left to recover them from. "
            "Clear the fields first if that is genuinely what you want."
        )

    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("years_experience_min")
        batch_op.drop_column("company_size")
