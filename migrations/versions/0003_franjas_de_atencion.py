"""Horario de atención por sucursal, cancha y día.

Revision ID: 0003_franjas_atencion
Revises: 0002_factura_reserva
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_franjas_atencion"
down_revision = "0002_factura_reserva"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "franjas_de_atencion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("cancha_id", sa.Integer(), nullable=True),
        # 🔴 **`create_type=False` y no es opcional.** El tipo `alcance_dia` ya
        # existe en la base: lo creó la tabla `tarifas` en `0001`. Sin esto,
        # Alembic emite otro `CREATE TYPE` y la migración muere con
        # *"type alcance_dia already exists"* — en PostgreSQL, que es el único
        # motor de la familia. No aparece contra SQLite, donde los enums son
        # CHECKs y no tipos con nombre.
        sa.Column(
            "alcance_dia",
            postgresql.ENUM(
                "todos", "dia_semana", "feriado", name="alcance_dia", create_type=False
            ),
            nullable=False,
            server_default="todos",
        ),
        sa.Column("dia_semana", sa.Integer(), nullable=True),
        sa.Column("abre", sa.Time(), nullable=False),
        sa.Column("cierra", sa.Time(), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(alcance_dia = 'dia_semana' AND dia_semana IS NOT NULL "
            " AND dia_semana BETWEEN 0 AND 6) "
            "OR (alcance_dia <> 'dia_semana' AND dia_semana IS NULL)",
            name="ck_franjas_dia_semana_coherente",
        ),
        sa.ForeignKeyConstraint(["cancha_id"], ["canchas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sucursal_id"], ["sucursales.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_franjas_sucursal", "franjas_de_atencion", ["sucursal_id"])
    op.create_index("ix_franjas_cancha", "franjas_de_atencion", ["cancha_id"])
    # 🔑 **No se siembra ninguna franja.** Una instancia sin franjas cae en el
    # horario por defecto (8:00–00:00), que es exactamente el que tenía
    # hardcodeado hasta ahora: el deploy no cambia lo que la agenda muestra
    # hasta que alguien configure su horario de verdad. Sembrar filas 8–00 haría
    # lo mismo pero dejaría al complejo sin saber que nunca configuró nada.


def downgrade() -> None:
    op.drop_index("ix_franjas_cancha", table_name="franjas_de_atencion")
    op.drop_index("ix_franjas_sucursal", table_name="franjas_de_atencion")
    op.drop_table("franjas_de_atencion")
    # El tipo `alcance_dia` NO se borra: lo sigue usando `tarifas`.
