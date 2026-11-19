"""antecedente de formas de onda por evento de revisión

Revision ID: f2b6d9c4a1e7
Revises: e1a5c8d2f7b3
Create Date: 2026-11-19 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "f2b6d9c4a1e7"
down_revision = "e1a5c8d2f7b3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "review_request_events",
        sa.Column("ondas", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("review_request_events", "ondas")
