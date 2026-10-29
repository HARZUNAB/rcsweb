"""alias visibles sin mecanismo de origen

Revision ID: 9f1c2a7b4d10
Revises: ccd1bba64919
Create Date: 2026-10-29 12:00:00.000000

"""

from alembic import op

revision = "9f1c2a7b4d10"
down_revision = "ccd1bba64919"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE job_sources SET alias = 'SeisComp' WHERE alias = 'SeisComp (exportación)'")
    op.execute("UPDATE job_sources SET alias = 'Seisan' WHERE alias = 'Seisan (descarga SSH)'")


def downgrade():
    op.execute("UPDATE job_sources SET alias = 'SeisComp (exportación)' WHERE alias = 'SeisComp'")
    op.execute("UPDATE job_sources SET alias = 'Seisan (descarga SSH)' WHERE alias = 'Seisan'")
