"""progreso por archivo de solicitud

Revision ID: c2a8f5d7e901
Revises: b7e4c1a9d2f3
Create Date: 2026-11-02 00:10:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "c2a8f5d7e901"
down_revision = "b7e4c1a9d2f3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("catalog_request_files", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade():
    with op.batch_alter_table("catalog_request_files", schema=None) as batch_op:
        batch_op.drop_column("progress")
