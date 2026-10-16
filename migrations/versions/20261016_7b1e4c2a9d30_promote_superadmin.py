"""promote the oldest active admin to superadmin

Revision ID: 7b1e4c2a9d30
Revises: f3da229e116e
Create Date: 2026-10-16 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7b1e4c2a9d30"
down_revision: str | Sequence[str] | None = "f3da229e116e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Data only: `role` is a plain String(20) column. Skipped if a superadmin already exists.
    op.execute(
        """
        UPDATE users SET role = 'superadmin'
        WHERE id = (
            SELECT id FROM users WHERE role = 'admin' AND is_active
            ORDER BY created_at, id LIMIT 1
        )
        AND NOT EXISTS (SELECT 1 FROM users WHERE role = 'superadmin')
        """
    )


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'superadmin'")
