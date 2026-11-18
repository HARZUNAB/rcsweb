"""correo de usuario y evidencia de revisión

Revision ID: c7e2a4f9b6d1
Revises: d9f3a2c7b8e1
Create Date: 2026-11-18 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "c7e2a4f9b6d1"
down_revision = "d9f3a2c7b8e1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("email", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.add_column(
        "review_requests",
        sa.Column("email_to", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "review_requests",
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "review_requests",
        sa.Column("email_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "review_requests",
        sa.Column("evidence_path", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "review_requests",
        sa.Column("evidence_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "review_requests",
        sa.Column("evidence_size", sa.Integer(), nullable=True),
    )
    op.add_column(
        "review_requests",
        sa.Column("evidence_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "review_requests",
        sa.Column(
            "evidence_uploaded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "review_request_events",
        sa.Column(
            "parameters_changed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "review_request_events",
        sa.Column("updated_url", sa.String(length=1000), nullable=True),
    )


def downgrade():
    op.drop_column("review_request_events", "updated_url")
    op.drop_column("review_request_events", "parameters_changed")

    op.drop_column("review_requests", "evidence_uploaded_at")
    op.drop_column("review_requests", "evidence_sha256")
    op.drop_column("review_requests", "evidence_size")
    op.drop_column("review_requests", "evidence_name")
    op.drop_column("review_requests", "evidence_path")
    op.drop_column("review_requests", "email_error")
    op.drop_column("review_requests", "email_sent_at")
    op.drop_column("review_requests", "email_to")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "email")
