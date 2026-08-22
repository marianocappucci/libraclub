"""«Falta uno»: partidos abiertos y quién se anota.

Revision ID: 0005_falta_uno
Revises: 0004_portal_publico
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_falta_uno"
down_revision = "0004_portal_publico"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "busquedas_de_jugadores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reserva_id", sa.Integer(), nullable=False),
        sa.Column("faltan", sa.Integer(), nullable=False),
        sa.Column("nota", sa.String(length=200), nullable=True),
        sa.Column("abierta", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("faltan > 0 AND faltan <= 20", name="ck_busquedas_faltan"),
        sa.ForeignKeyConstraint(["reserva_id"], ["reservas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Una reserva, una búsqueda: dos publicaciones del mismo partido serían
        # dos listas de anotados que no se ven entre sí.
        sa.UniqueConstraint("reserva_id", name="uq_busquedas_reserva"),
    )

    op.create_table(
        "anotados_en_partido",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("busqueda_id", sa.Integer(), nullable=False),
        sa.Column("cuenta_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["busqueda_id"], ["busquedas_de_jugadores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["cuenta_id"], ["cuentas_de_jugador.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # 🔑 Nadie se anota dos veces: sin esto, dos clicks ocupan dos lugares
        # con la misma persona y el partido queda "completo" con gente que no
        # existe.
        sa.UniqueConstraint("busqueda_id", "cuenta_id", name="uq_anotados_unico"),
    )
    op.create_index("ix_anotados_busqueda", "anotados_en_partido", ["busqueda_id"])


def downgrade() -> None:
    op.drop_index("ix_anotados_busqueda", table_name="anotados_en_partido")
    op.drop_table("anotados_en_partido")
    op.drop_table("busquedas_de_jugadores")
