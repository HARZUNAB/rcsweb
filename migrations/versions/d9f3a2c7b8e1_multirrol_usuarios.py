"""multirol de usuarios

Revision ID: d9f3a2c7b8e1
Revises: a4d2f7c9b1e0
Create Date: 2026-11-14 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "d9f3a2c7b8e1"
down_revision = "a4d2f7c9b1e0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "role"),
    )
    op.create_index("ix_user_roles_role", "user_roles", ["role"])

    bind = op.get_bind()
    usuarios = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("role", sa.String),
    )
    roles = sa.table(
        "user_roles",
        sa.column("user_id", sa.Integer),
        sa.column("role", sa.String),
    )
    for fila in bind.execute(sa.select(usuarios)).mappings():
        if not fila["role"]:
            continue
        bind.execute(
            roles.insert().values(
                user_id=fila["id"],
                role=fila["role"],
            )
        )


def downgrade():
    op.drop_index("ix_user_roles_role", table_name="user_roles")
    op.drop_table("user_roles")
