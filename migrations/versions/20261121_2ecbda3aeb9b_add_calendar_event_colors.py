"""add calendar event colors

Revision ID: 2ecbda3aeb9b
Revises: e87ba08fe1cb
Create Date: 2026-11-21 19:34:07.404239

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2ecbda3aeb9b"
down_revision: str | Sequence[str] | None = "e87ba08fe1cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "calendar_events",
        sa.Column("color", sa.String(length=12), server_default="teal", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("calendar_events", "color")
