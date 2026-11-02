"""nombre visible de archivos de catálogo

Revision ID: b7e4c1a9d2f3
Revises: 9f1c2a7b4d10
Create Date: 2026-11-02 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "b7e4c1a9d2f3"
down_revision = "9f1c2a7b4d10"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("catalog_request_files", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("display_name", sa.String(length=80), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("catalog_request_files", schema=None) as batch_op:
        batch_op.drop_column("display_name")
