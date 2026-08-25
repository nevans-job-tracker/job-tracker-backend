"""pay period, employment type, contract term, and weekly hours

Five columns in one revision (KAN-50, KAN-51), the way KAN-32 and KAN-35
shipped together — they were specified in one conversation and there is no
state where half of them is useful.

`pay_period` records what the figures in salary_min/salary_max measure. Before
it, the two were told apart by magnitude alone: the display rule "values below
1000 are shown unrounded" was the only thing stopping an 86/hour rate from
rendering as "0K". A guard doing a schema's job.

**The backfill is the column default and nothing cleverer.** A
`salary_min < 1000 => hourly` rule is the obvious move and is wrong on this
data: one row reads `0.00 - 120000.00`, an annual posting with a bogus zero
minimum, which that rule would silently relabel hourly. Stamping every existing
row `annual` is true of all but one, and that one is corrected by hand
afterwards. A known correction beats a heuristic that mislabels quietly.

`employment_type`, `contract_term_months` and `hours_per_week` are nullable and
*not* defaulted,
which is the opposite choice and deliberate. Every pay figure really is annual
or hourly, so `pay_period` has no honest "unset". Plenty of postings simply do
not say whether they are permanent, so blank is a real answer there and
defaulting to full_time would invent a fact for all 59 existing rows.

`hours_per_week_min`/`_max` is a pair rather than a scalar because postings
write it as a range — "Commitment: 10-40 hrs/week" — and one column would have
to throw an end away. It is deliberately not tied to any particular
employment_type: contract and part-time postings state it and full-time ones
rarely do, but 20 hours a week means the same thing on either, so a pairing
rule would buy nothing and only give the API another way to say no.

Both enums are declared in the order the application declares them, because
MySQL and MariaDB store an ENUM as its ordinal — that order is what any
`ORDER BY employment_type` means.

Revision ID: 9c1e7d4b8a52
Revises: 83ffeed76a6f
Create Date: 2026-08-25 16:40:12.114837

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c1e7d4b8a52'
down_revision: Union[str, Sequence[str], None] = '83ffeed76a6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PAY_PERIODS = ("annual", "hourly")

# Most to least conventional commitment, the two contract kinds adjacent.
_EMPLOYMENT_TYPES = (
    "full_time",
    "part_time",
    "contract",
    "contract_to_hire",
    "volunteer",
)


def upgrade() -> None:
    """Upgrade schema.

    batch_alter_table for the same reason as every revision since KAN-31:
    SQLite cannot ALTER a column in place and the tests run on SQLite, while
    on MariaDB batch mode emits a plain ALTER. One code path, no dialect
    branch.
    """
    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(
            sa.Column(
                "pay_period",
                sa.Enum(*_PAY_PERIODS, name="payperiod"),
                nullable=False,
                server_default="annual",
            )
        )
        batch_op.add_column(
            sa.Column(
                "employment_type",
                sa.Enum(*_EMPLOYMENT_TYPES, name="employmenttype"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("contract_term_months", sa.SmallInteger(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("hours_per_week_min", sa.SmallInteger(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("hours_per_week_max", sa.SmallInteger(), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema.

    Refuses rather than guesses, consistent with every revision since KAN-31.

    Weaker than the KAN-42 refusal — a pay period or an employment type can be
    retyped from the posting, where status history could not be regenerated at
    all. It still refuses, because "retypeable in principle" means someone has
    to open 59 job ads, and silent data loss during a downgrade is exactly the
    failure this project keeps designing against.

    A row is only counted if it carries something the revision added. An
    untouched database downgrades cleanly.
    """
    rows = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM applications "
            "WHERE pay_period <> 'annual' "
            "   OR employment_type IS NOT NULL "
            "   OR contract_term_months IS NOT NULL"
            "   OR hours_per_week_min IS NOT NULL"
            "   OR hours_per_week_max IS NOT NULL"
        )
    ).scalar()

    if rows:
        raise RuntimeError(
            f"Refusing to downgrade: {rows} application(s) carry a pay period, "
            "employment type, contract term, or weekly hours that this "
            "revision added. "
            "Dropping these columns would discard those values, and each one "
            "means reopening a job posting to recover. Clear them first if "
            "that is genuinely what you want."
        )

    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("hours_per_week_max")
        batch_op.drop_column("hours_per_week_min")
        batch_op.drop_column("contract_term_months")
        batch_op.drop_column("employment_type")
        batch_op.drop_column("pay_period")
