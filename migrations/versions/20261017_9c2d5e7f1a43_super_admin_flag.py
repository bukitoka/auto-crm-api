"""replace the superadmin role with an is_super_admin flag

Revision ID: 9c2d5e7f1a43
Revises: 4b3166e5cb99
Create Date: 2026-10-17 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c2d5e7f1a43"
down_revision: str | Sequence[str] | None = "4b3166e5cb99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_super_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # The old superadmin role went to the first registered user, a team member with records of
    # their own, so it becomes a plain admin. The super admin is created on the setup page.
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'superadmin'")


def downgrade() -> None:
    op.drop_column("users", "is_super_admin")
