"""cover letter text

Keeps what was written to a given employer (KAN-40). Text rather than an
uploaded file, and that choice is what makes this revision a one-liner:

  * A text column rides the existing encrypted nightly dump, so KAN-19 and
    KAN-37's restore rehearsal keeps meaning exactly what it meant. A second
    store on the filesystem would have left a green RESTORE VERIFIED sitting
    next to a bucket missing every cover letter.
  * No new encryption path. REQUIREMENTS.md §5 requires client-side encryption
    before upload, and a cover letter carries the owner's name and history.
  * Nothing can diverge: no row pointing at a missing file, no orphan file.

A PDF can be regenerated from the text, which is what the owner actually
wanted. See REQUIREMENTS.md §2 and §6.2.

Revision ID: 53f76402812f
Revises: 127a196f3c90
Create Date: 2026-08-23 09:58:14.220417

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '53f76402812f'
down_revision: Union[str, Sequence[str], None] = '127a196f3c90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("applications", sa.Column("cover_letter", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema.

    Refuses if any row holds cover letter text. Dropping a column is not a
    lossy conversion that could be argued about — the text simply ceases to
    exist, with nothing left to recover it from. Same stance as 4500fe76cbd9
    and 127a196f3c90: a downgrade either reverses cleanly or does nothing.
    """
    blocking = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM applications "
            "WHERE cover_letter IS NOT NULL AND cover_letter <> ''"
        )
    ).scalar()

    if blocking:
        raise RuntimeError(
            f"Refusing to downgrade: {blocking} application(s) hold cover letter "
            "text, and dropping this column would discard it with nothing left "
            "to recover it from. Clear the field first if that is genuinely "
            "what you want."
        )

    # Batch, because dropping a column is the half SQLite has historically not
    # supported in place. On MariaDB this emits a plain ALTER.
    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("cover_letter")
