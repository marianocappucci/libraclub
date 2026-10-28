"""Aviso de seña por vencer, WhatsApp en modo registro y promociones (ADR-029).

Aditiva: dos valores nuevos de ENUM, un tipo nuevo y dos tablas nuevas. Nada de lo que ya
existe cambia de comportamiento — sin fila en `config_avisos` rigen los defaults (todos los
avisos prendidos, WhatsApp apagado) y sin promociones el precio de un turno es el de siempre.

Revision ID: 0016_avisos_y_promociones
Revises: 0015_americanos
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_avisos_y_promociones"
down_revision = "0015_americanos"
branch_labels = None
depends_on = None

#: Como en `0009`: el tipo se crea a mano y la columna lo usa con `create_type=False`.
MODO_WHATSAPP = postgresql.ENUM("apagado", "registro", name="modo_whatsapp", create_type=False)


def upgrade() -> None:
    # Un valor nuevo de un ENUM no se puede usar en la transacción que lo crea, y `ALTER TYPE ...
    # ADD VALUE` no corre dentro de un bloque transaccional en todas las versiones: Alembic
    # confirma lo hecho hasta acá, lo corre solo y sigue en una transacción nueva (igual que 0013).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE tipo_aviso ADD VALUE IF NOT EXISTS 'sena_por_vencer'")
        op.execute("ALTER TYPE estado_aviso ADD VALUE IF NOT EXISTS 'registrado'")

    MODO_WHATSAPP.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "config_avisos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("whatsapp", MODO_WHATSAPP, nullable=False),
        sa.Column("avisar_confirmacion", sa.Boolean(), nullable=False),
        sa.Column("avisar_recordatorio", sa.Boolean(), nullable=False),
        sa.Column("avisar_cancelacion", sa.Boolean(), nullable=False),
        sa.Column("avisar_sena_por_vencer", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_config_avisos_una_sola"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "promociones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("cancha_id", sa.Integer(), nullable=True),
        sa.Column("nombre", sa.String(length=80), nullable=False),
        sa.Column("descuento_porcentaje", sa.SmallInteger(), nullable=False),
        sa.Column("dias_semana", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("hora_desde", sa.Time(), nullable=False),
        sa.Column("hora_hasta", sa.Time(), nullable=False),
        sa.Column("vigente_desde", sa.Date(), nullable=True),
        sa.Column("vigente_hasta", sa.Date(), nullable=True),
        sa.Column("aplica_en_feriados", sa.Boolean(), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("hora_desde < hora_hasta", name="ck_promociones_franja"),
        sa.CheckConstraint(
            "descuento_porcentaje >= 1 AND descuento_porcentaje <= 99",
            name="ck_promociones_descuento",
        ),
        sa.CheckConstraint(
            "dias_semana IS NULL OR (cardinality(dias_semana) > 0 "
            "AND dias_semana <@ ARRAY[0,1,2,3,4,5,6]::smallint[])",
            name="ck_promociones_dias",
        ),
        sa.CheckConstraint(
            "vigente_hasta IS NULL OR vigente_desde IS NULL "
            "OR vigente_hasta >= vigente_desde",
            name="ck_promociones_vigencia",
        ),
        sa.ForeignKeyConstraint(["sucursal_id"], ["sucursales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cancha_id"], ["canchas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_promociones_sucursal", "promociones", ["sucursal_id"])
    op.create_index("ix_promociones_cancha", "promociones", ["cancha_id"])


def downgrade() -> None:
    op.drop_index("ix_promociones_cancha", table_name="promociones")
    op.drop_index("ix_promociones_sucursal", table_name="promociones")
    op.drop_table("promociones")
    op.drop_table("config_avisos")
    MODO_WHATSAPP.drop(op.get_bind(), checkfirst=False)

    # `ALTER TYPE ... DROP VALUE` no existe: habría que recrear el tipo entero, y con él la
    # columna y su restricción única. Los dos valores nuevos quedan en el tipo, sin uso. Lo que
    # sí hay que sacar son las filas que los usan, porque el código viejo no las conoce.
    op.execute("DELETE FROM avisos WHERE tipo = 'sena_por_vencer' OR estado = 'registrado'")
