"""fuentes directas en solicitudes

Revision ID: f3c1a7d9e205
Revises: e5a1c2b3d604
Create Date: 2026-11-10 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "f3c1a7d9e205"
down_revision = "e5a1c2b3d604"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("catalog_requests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("direct_sources", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("catalog_requests", schema=None) as batch_op:
        batch_op.drop_column("direct_sources")
