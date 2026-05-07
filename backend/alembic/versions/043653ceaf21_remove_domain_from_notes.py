"""remove_domain_from_notes

Revision ID: 043653ceaf21
Revises: b1c2d3e4f5a6
Create Date: 2026-05-05 16:25:25.941736

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "043653ceaf21"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("notes", "domain")


def downgrade() -> None:
    op.add_column("notes", sa.Column("domain", sa.String(), nullable=True))
