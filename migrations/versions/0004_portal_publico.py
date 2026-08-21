"""El portal público: cuentas de jugador y pagos de reserva.

Revision ID: 0004_portal_publico
Revises: 0003_franjas_atencion
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_portal_publico"
down_revision = "0003_franjas_atencion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cuentas_de_jugador",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("telefono", sa.String(length=40), nullable=True),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_cuentas_jugador_email"),
    )
    op.create_index("ix_cuentas_jugador_cliente", "cuentas_de_jugador", ["cliente_id"])

    # 🔴 **El tipo se crea explícitamente Y la columna lleva
    # `create_type=False`.** Hacen falta las dos mitades y por motivos opuestos:
    #
    # - Sin el `create()`, en un `downgrade`+`upgrade` el tipo ya no está y el
    #   `CREATE TABLE` no lo crea solo con `postgresql.ENUM(create_type=False)`.
    # - Sin el `create_type=False`, `create_table` emite un segundo
    #   `CREATE TYPE` y la migración muere con *"type estado_pago already
    #   exists"* — verificado, es lo que pasó al escribirla.
    #
    # Es la trampa **opuesta** a la de `alcance_dia` en la 0003, donde el tipo ya
    # existía y sólo hacía falta la segunda mitad. Copiar cualquiera de las dos
    # migraciones sin mirar cuál es el caso da un error distinto cada vez.
    estado_pago = postgresql.ENUM(
        "pendiente", "aprobado", "rechazado", "vencido",
        name="estado_pago", create_type=False,
    )
    sa.Enum(
        "pendiente", "aprobado", "rechazado", "vencido", name="estado_pago"
    ).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "pagos_de_reserva",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reserva_id", sa.Integer(), nullable=False),
        sa.Column("monto", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("estado", estado_pago, nullable=False, server_default="pendiente"),
        sa.Column("referencia", sa.String(length=64), nullable=False),
        sa.Column("preference_id", sa.String(length=64), nullable=True),
        sa.Column("payment_id", sa.String(length=64), nullable=True),
        sa.Column("estado_mp", sa.String(length=40), nullable=True),
        sa.Column("pagado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("monto > 0", name="ck_pagos_reserva_monto"),
        sa.ForeignKeyConstraint(["reserva_id"], ["reservas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referencia", name="uq_pagos_reserva_referencia"),
    )
    # Un solo pago APROBADO por reserva. Parcial: los rechazados y los
    # reintentos pueden repetirse, lo que no puede es cobrar dos veces.
    op.create_index(
        "uq_pagos_reserva_aprobado", "pagos_de_reserva", ["reserva_id"],
        unique=True, postgresql_where=sa.text("estado = 'aprobado'"),
    )
    op.create_index("ix_pagos_reserva_payment", "pagos_de_reserva", ["payment_id"])


def downgrade() -> None:
    op.drop_index("ix_pagos_reserva_payment", table_name="pagos_de_reserva")
    op.drop_index("uq_pagos_reserva_aprobado", table_name="pagos_de_reserva")
    op.drop_table("pagos_de_reserva")
    sa.Enum(name="estado_pago").drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_cuentas_jugador_cliente", table_name="cuentas_de_jugador")
    op.drop_table("cuentas_de_jugador")
