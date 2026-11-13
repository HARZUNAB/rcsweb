"""solicitudes de revision con varios eventos y PDF

Revision ID: a4d2f7c9b1e0
Revises: 8f2b6c1d4a7e
Create Date: 2026-11-13 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "a4d2f7c9b1e0"
down_revision = "8f2b6c1d4a7e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "review_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("assigned_to_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("report_path", sa.String(length=255), nullable=True),
        sa.Column("report_name", sa.String(length=255), nullable=True),
        sa.Column("report_format", sa.String(length=8), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closing_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_requests_job_id", "review_requests", ["job_id"]
    )
    op.create_index(
        "ix_review_requests_source_id", "review_requests", ["source_id"]
    )
    op.create_index(
        "ix_review_requests_created_by_id",
        "review_requests",
        ["created_by_id"],
    )
    op.create_index(
        "ix_review_requests_assigned_to_id",
        "review_requests",
        ["assigned_to_id"],
    )
    op.create_index(
        "ix_review_requests_status", "review_requests", ["status"]
    )
    op.create_index(
        "ix_review_requests_notified_at",
        "review_requests",
        ["notified_at"],
    )

    op.create_table(
        "review_request_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("source_event_id", sa.String(length=128), nullable=False),
        sa.Column("fila_catalogo", sa.Integer(), nullable=True),
        sa.Column("event_time", sa.String(length=32), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("depth_km", sa.Float(), nullable=True),
        sa.Column("magnitude", sa.Float(), nullable=True),
        sa.Column("magnitude_type", sa.String(length=16), nullable=False),
        sa.Column("analyst", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("motive", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"], ["review_requests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id",
            "source_id",
            "event_id",
            name="uq_review_request_events_request_source_event",
        ),
    )
    op.create_index(
        "ix_review_request_events_request_id",
        "review_request_events",
        ["request_id"],
    )
    op.create_index(
        "ix_review_request_events_source_id",
        "review_request_events",
        ["source_id"],
    )
    op.create_index(
        "ix_review_request_events_event_id",
        "review_request_events",
        ["event_id"],
    )

    # Migra las solicitudes antiguas de un evento a la nueva estructura.
    bind = op.get_bind()
    antiguas = sa.table(
        "event_review_requests",
        sa.column("id", sa.Integer),
        sa.column("job_id", sa.String),
        sa.column("source_id", sa.String),
        sa.column("event_id", sa.String),
        sa.column("source_event_id", sa.String),
        sa.column("requested_by_id", sa.Integer),
        sa.column("note", sa.Text),
        sa.column("status", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    solicitudes = sa.table(
        "review_requests",
        sa.column("id", sa.Integer),
        sa.column("job_id", sa.String),
        sa.column("source_id", sa.String),
        sa.column("created_by_id", sa.Integer),
        sa.column("assigned_to_id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("note", sa.Text),
        sa.column("report_path", sa.String),
        sa.column("report_name", sa.String),
        sa.column("report_format", sa.String),
        sa.column("notified_at", sa.DateTime(timezone=True)),
        sa.column("accepted_at", sa.DateTime(timezone=True)),
        sa.column("closed_at", sa.DateTime(timezone=True)),
        sa.column("closing_note", sa.Text),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    eventos = sa.table(
        "review_request_events",
        sa.column("request_id", sa.Integer),
        sa.column("source_id", sa.String),
        sa.column("event_id", sa.String),
        sa.column("source_event_id", sa.String),
        sa.column("fila_catalogo", sa.Integer),
        sa.column("event_time", sa.String),
        sa.column("latitude", sa.Float),
        sa.column("longitude", sa.Float),
        sa.column("depth_km", sa.Float),
        sa.column("magnitude", sa.Float),
        sa.column("magnitude_type", sa.String),
        sa.column("analyst", sa.String),
        sa.column("priority", sa.String),
        sa.column("motive", sa.String),
    )
    for fila in bind.execute(sa.select(antiguas)).mappings():
        creada = bind.execute(
            solicitudes.insert()
            .values(
                job_id=fila["job_id"],
                source_id=fila["source_id"],
                created_by_id=fila["requested_by_id"],
                assigned_to_id=None,
                status="notificada",
                note=fila["note"],
                report_path=None,
                report_name=None,
                report_format="pdf",
                notified_at=fila["created_at"],
                accepted_at=None,
                closed_at=None,
                closing_note=None,
                created_at=fila["created_at"],
            )
            .returning(solicitudes.c.id)
        )
        request_id = creada.scalar_one()
        bind.execute(
            eventos.insert().values(
                request_id=request_id,
                source_id=fila["source_id"],
                event_id=fila["event_id"],
                source_event_id=fila["source_event_id"] or "",
                fila_catalogo=None,
                event_time="",
                latitude=None,
                longitude=None,
                depth_km=None,
                magnitude=None,
                magnitude_type="",
                analyst="",
                priority="",
                motive="",
            )
        )


def downgrade():
    op.drop_index(
        "ix_review_request_events_event_id",
        table_name="review_request_events",
    )
    op.drop_index(
        "ix_review_request_events_source_id",
        table_name="review_request_events",
    )
    op.drop_index(
        "ix_review_request_events_request_id",
        table_name="review_request_events",
    )
    op.drop_table("review_request_events")
    op.drop_index(
        "ix_review_requests_notified_at", table_name="review_requests"
    )
    op.drop_index("ix_review_requests_status", table_name="review_requests")
    op.drop_index(
        "ix_review_requests_assigned_to_id", table_name="review_requests"
    )
    op.drop_index(
        "ix_review_requests_created_by_id", table_name="review_requests"
    )
    op.drop_index(
        "ix_review_requests_source_id", table_name="review_requests"
    )
    op.drop_index("ix_review_requests_job_id", table_name="review_requests")
    op.drop_table("review_requests")
