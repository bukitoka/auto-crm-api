"""merge the member role into admin

Revision ID: a7e41c0b52d9
Revises: 9c2d5e7f1a43
Create Date: 2026-10-18 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7e41c0b52d9"
down_revision: str | Sequence[str] | None = "9c2d5e7f1a43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Admins are the people doing CRM work now; the super admin is the flag on the account.
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'member'")


def downgrade() -> None:
    # Nothing to undo: the old members can't be told apart from admins any more.
    pass
