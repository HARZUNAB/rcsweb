"""resultados persistentes de senal de cobertura de picks

Revision ID: a7c4e9b1d2f6
Revises: d4a7c2e9f1b8
Create Date: 2026-11-26 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "a7c4e9b1d2f6"
down_revision = "d4a7c2e9f1b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "picks_signal_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("estado", sa.String(length=24), nullable=False),
        sa.Column("senal_n", sa.Integer(), nullable=False),
        sa.Column("senal_estaciones", sa.Text(), nullable=False),
        sa.Column("detalle", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("analizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "event_id",
            "fingerprint",
            "rule_version",
            name="uq_picks_signal_results_event_fingerprint_rule",
        ),
    )
    op.create_index(
        "ix_picks_signal_results_source_id",
        "picks_signal_results",
        ["source_id"],
    )
    op.create_index(
        "ix_picks_signal_results_event_id",
        "picks_signal_results",
        ["event_id"],
    )
    op.create_index(
        "ix_picks_signal_results_fingerprint",
        "picks_signal_results",
        ["fingerprint"],
    )
    op.create_index(
        "ix_picks_signal_results_rule_version",
        "picks_signal_results",
        ["rule_version"],
    )
    op.create_index(
        "ix_picks_signal_results_estado",
        "picks_signal_results",
        ["estado"],
    )


def downgrade():
    op.drop_index(
        "ix_picks_signal_results_estado",
        table_name="picks_signal_results",
    )
    op.drop_index(
        "ix_picks_signal_results_rule_version",
        table_name="picks_signal_results",
    )
    op.drop_index(
        "ix_picks_signal_results_fingerprint",
        table_name="picks_signal_results",
    )
    op.drop_index(
        "ix_picks_signal_results_event_id",
        table_name="picks_signal_results",
    )
    op.drop_index(
        "ix_picks_signal_results_source_id",
        table_name="picks_signal_results",
    )
    op.drop_table("picks_signal_results")
