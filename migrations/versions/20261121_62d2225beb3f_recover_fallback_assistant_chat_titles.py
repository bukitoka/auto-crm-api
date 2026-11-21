"""recover fallback assistant chat titles

Revision ID: 62d2225beb3f
Revises: c15669a5b337
Create Date: 2026-11-21 21:44:07.613517

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "62d2225beb3f"
down_revision: str | Sequence[str] | None = "c15669a5b337"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistant_conversations", sa.Column("title_pending", sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("assistant_conversations", "title_pending")
