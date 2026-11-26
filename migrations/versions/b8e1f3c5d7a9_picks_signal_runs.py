"""corridas persistentes de senal de cobertura de picks

Revision ID: b8e1f3c5d7a9
Revises: a7c4e9b1d2f6
Create Date: 2026-11-26 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "b8e1f3c5d7a9"
down_revision = "a7c4e9b1d2f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "picks_signal_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("scope", sa.String(length=24), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("con_senal", sa.Integer(), nullable=False),
        sa.Column("sin_senal", sa.Integer(), nullable=False),
        sa.Column("sin_datos", sa.Integer(), nullable=False),
        sa.Column("errores", sa.Integer(), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("current_event", sa.String(length=160), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_picks_signal_runs_job_id",
        "picks_signal_runs",
        ["job_id"],
    )
    op.create_index(
        "ix_picks_signal_runs_source_id",
        "picks_signal_runs",
        ["source_id"],
    )
    op.create_index(
        "ix_picks_signal_runs_status",
        "picks_signal_runs",
        ["status"],
    )
    op.create_index(
        "ix_picks_signal_runs_created_at",
        "picks_signal_runs",
        ["created_at"],
    )

    op.create_table(
        "picks_signal_run_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["picks_signal_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "event_id",
            name="uq_picks_signal_run_items_run_event",
        ),
    )
    op.create_index(
        "ix_picks_signal_run_items_run_id",
        "picks_signal_run_items",
        ["run_id"],
    )
    op.create_index(
        "ix_picks_signal_run_items_event_id",
        "picks_signal_run_items",
        ["event_id"],
    )
    op.create_index(
        "ix_picks_signal_run_items_status",
        "picks_signal_run_items",
        ["status"],
    )
    op.create_index(
        "ix_picks_signal_run_items_run_status_pos",
        "picks_signal_run_items",
        ["run_id", "status", "position"],
    )


def downgrade():
    op.drop_index(
        "ix_picks_signal_run_items_run_status_pos",
        table_name="picks_signal_run_items",
    )
    op.drop_index(
        "ix_picks_signal_run_items_status",
        table_name="picks_signal_run_items",
    )
    op.drop_index(
        "ix_picks_signal_run_items_event_id",
        table_name="picks_signal_run_items",
    )
    op.drop_index(
        "ix_picks_signal_run_items_run_id",
        table_name="picks_signal_run_items",
    )
    op.drop_table("picks_signal_run_items")
    op.drop_index(
        "ix_picks_signal_runs_created_at",
        table_name="picks_signal_runs",
    )
    op.drop_index(
        "ix_picks_signal_runs_status",
        table_name="picks_signal_runs",
    )
    op.drop_index(
        "ix_picks_signal_runs_source_id",
        table_name="picks_signal_runs",
    )
    op.drop_index(
        "ix_picks_signal_runs_job_id",
        table_name="picks_signal_runs",
    )
    op.drop_table("picks_signal_runs")
