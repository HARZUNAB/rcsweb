"""copias y adjunto en la notificación de revisión

Revision ID: a7c9e1f4b2d8
Revises: b8e1f3c5d7a9
Create Date: 2026-11-27 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "a7c9e1f4b2d8"
down_revision = "b8e1f3c5d7a9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "review_requests",
        sa.Column("email_cc", sa.Text(), nullable=True),
    )
    op.add_column(
        "review_requests",
        sa.Column(
            "email_attach_report",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_column("review_requests", "email_attach_report")
    op.drop_column("review_requests", "email_cc")
