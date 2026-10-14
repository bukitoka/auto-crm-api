"""seed default pipeline stages

Revision ID: 2054110ae8f2
Revises: 2c67206afd33
Create Date: 2026-10-13 13:10:00.066611

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2054110ae8f2"
down_revision: str | Sequence[str] | None = "2c67206afd33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# A lightweight table definition: migrations must not import app models,
# because models change over time while this migration must stay the same.
pipeline_stages = sa.table(
    "pipeline_stages",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("position", sa.Integer()),
    sa.column("probability", sa.Integer()),
    sa.column("is_won", sa.Boolean()),
    sa.column("is_lost", sa.Boolean()),
)

DEFAULT_STAGES = [
    # (name, probability %, is_won, is_lost)
    ("Qualification", 10, False, False),
    ("Proposal", 40, False, False),
    ("Negotiation", 70, False, False),
    ("Won", 100, True, False),
    ("Lost", 0, False, True),
]


def upgrade() -> None:
    op.bulk_insert(
        pipeline_stages,
        [
            {
                "id": uuid.uuid7(),
                "name": name,
                "position": position,
                "probability": probability,
                "is_won": is_won,
                "is_lost": is_lost,
            }
            for position, (name, probability, is_won, is_lost) in enumerate(DEFAULT_STAGES, 1)
        ],
    )


def downgrade() -> None:
    names = [name for name, *_ in DEFAULT_STAGES]
    op.execute(pipeline_stages.delete().where(pipeline_stages.c.name.in_(names)))
