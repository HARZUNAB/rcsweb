"""notificación omitida en solicitudes de revisión

Revision ID: d4a7c2e9f1b8
Revises: b3d7e9f1c2a4
Create Date: 2026-11-23 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "d4a7c2e9f1b8"
down_revision = "b3d7e9f1c2a4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "review_requests",
        sa.Column(
            "email_skipped",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_column("review_requests", "email_skipped")
