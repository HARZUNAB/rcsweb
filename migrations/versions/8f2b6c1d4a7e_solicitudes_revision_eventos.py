"""solicitudes de revision de eventos con indicios

Revision ID: 8f2b6c1d4a7e
Revises: f3c1a7d9e205
Create Date: 2026-11-11 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "8f2b6c1d4a7e"
down_revision = "f3c1a7d9e205"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_review_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("source_event_id", sa.String(length=128), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "source_id",
            "event_id",
            name="uq_event_review_requests_job_source_event",
        ),
    )
    with op.batch_alter_table("event_review_requests", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_event_review_requests_job_id"), ["job_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_event_review_requests_source_id"),
            ["source_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_event_review_requests_event_id"),
            ["event_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_event_review_requests_created_at"),
            ["created_at"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("event_review_requests", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_event_review_requests_created_at"))
        batch_op.drop_index(batch_op.f("ix_event_review_requests_event_id"))
        batch_op.drop_index(batch_op.f("ix_event_review_requests_source_id"))
        batch_op.drop_index(batch_op.f("ix_event_review_requests_job_id"))
    op.drop_table("event_review_requests")
