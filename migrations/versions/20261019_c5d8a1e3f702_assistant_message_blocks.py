"""assistant message blocks

Revision ID: c5d8a1e3f702
Revises: a7e41c0b52d9
Create Date: 2026-10-19 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c5d8a1e3f702"
down_revision: str | Sequence[str] | None = "a7e41c0b52d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistant_messages",
        sa.Column(
            "blocks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("assistant_messages", "blocks")
