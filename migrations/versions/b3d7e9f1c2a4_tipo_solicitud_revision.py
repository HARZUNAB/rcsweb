"""tipo de solicitud de revisión

Revision ID: b3d7e9f1c2a4
Revises: f2b6d9c4a1e7
Create Date: 2026-11-20 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "b3d7e9f1c2a4"
down_revision = "f2b6d9c4a1e7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "review_requests",
        sa.Column(
            "kind",
            sa.String(length=20),
            nullable=False,
            server_default="solucion",
        ),
    )
    op.create_index(
        "ix_review_requests_kind", "review_requests", ["kind"], unique=False
    )


def downgrade():
    op.drop_index("ix_review_requests_kind", table_name="review_requests")
    op.drop_column("review_requests", "kind")
