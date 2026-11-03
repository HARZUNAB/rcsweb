"""marca de trabajo eliminado en solicitudes

Revision ID: d4f7a1c9e502
Revises: c2a8f5d7e901
Create Date: 2026-11-03 11:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "d4f7a1c9e502"
down_revision = "c2a8f5d7e901"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("catalog_requests", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("job_deleted_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("catalog_requests", schema=None) as batch_op:
        batch_op.drop_column("job_deleted_at")
