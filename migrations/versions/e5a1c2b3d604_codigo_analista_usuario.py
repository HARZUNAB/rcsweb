"""código corto de analista en usuarios

Revision ID: e5a1c2b3d604
Revises: d4f7a1c9e502
Create Date: 2026-11-03 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "e5a1c2b3d604"
down_revision = "d4f7a1c9e502"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("analyst_code", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("analyst_aliases", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("analyst_aliases")
        batch_op.drop_column("analyst_code")
