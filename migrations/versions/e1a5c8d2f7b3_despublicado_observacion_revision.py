"""despublicado y observación por evento de revisión

Revision ID: e1a5c8d2f7b3
Revises: c7e2a4f9b6d1
Create Date: 2026-11-18 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "e1a5c8d2f7b3"
down_revision = "c7e2a4f9b6d1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "review_request_events",
        sa.Column(
            "unpublished",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "review_request_events",
        sa.Column("observation", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("review_request_events", "observation")
    op.drop_column("review_request_events", "unpublished")
