"""assistant message attachments

Revision ID: 4b3166e5cb99
Revises: 7b1e4c2a9d30
Create Date: 2026-10-16 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4b3166e5cb99"
down_revision: str | Sequence[str] | None = "7b1e4c2a9d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistant_messages",
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("assistant_messages", "attachments")
