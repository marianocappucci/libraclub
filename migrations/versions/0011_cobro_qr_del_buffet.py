"""El cobro con QR de una venta de buffet, que no tiene turno detrás.

Revision ID: 0011_qr_del_buffet
Revises: 0010_politica_cancelacion
Create Date: 2026-09-08

Hasta acá el QR del mostrador cobraba **turnos**: `pagos_de_reserva.reserva_id`
era `NOT NULL` y toda la maquinaria colgaba de ahí. Pero en la Caja hay otra cosa
que se cobra y no es un turno — la **venta suelta del buffet**, la gaseosa que
compra alguien que no está jugando— y ahí elegir «MercadoPago» anotaba un
movimiento a mano, como si fuera una transferencia. El humano lo reportó el
2026-09-08: *"elijo pagar mercadopago y me tiene que aparecer la opción de QR"*.
Es el mismo reporte que el del 2026-08-28, sobre el otro camino.

Dos cambios, y los dos son sobre el **origen** del pago:

- **`reserva_id` pasa a admitir `NULL`.** No se pierde ninguna garantía: la que
  importaba —que un pago apunte a algo— la toma el CHECK de abajo, que es más
  fuerte que el `NOT NULL` porque también prohíbe la fila que apunta a las dos
  cosas a la vez.
- **`venta_id`**, el id de la venta de buffet. Sin FK a propósito: `sales` vive
  en la base de LibraCore, que es otra base — el mismo caso que
  `caja_movimiento_id`, documentado en el modelo.

Y el índice parcial que impide cobrar dos veces la misma venta, espejo exacto
del que ya existía para las reservas.

> 🔑 **No hay backfill y no puede haberlo.** Toda fila que ya está tiene
> `reserva_id` cargado, así que el CHECK las acepta todas sin tocar una sola.
> Se verificó antes de escribir esto: es lo que hace que la migración sea
> instantánea en las instancias con datos.
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_qr_del_buffet"
down_revision = "0010_politica_cancelacion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "pagos_de_reserva", "reserva_id", existing_type=sa.Integer(), nullable=True
    )
    op.add_column("pagos_de_reserva", sa.Column("venta_id", sa.Integer(), nullable=True))
    op.create_index(
        "uq_pagos_venta_aprobado",
        "pagos_de_reserva",
        ["venta_id"],
        unique=True,
        postgresql_where=sa.text("estado = 'aprobado'"),
    )
    op.create_check_constraint(
        "ck_pagos_reserva_origen",
        "pagos_de_reserva",
        "(reserva_id IS NULL) <> (venta_id IS NULL)",
    )


def downgrade() -> None:
    # 🔴 **Los pagos de buffet se borran, y por eso este downgrade pierde
    # datos.** No hay a dónde mudarlos: son cobros que no tienen turno, y la
    # columna que los identifica es la que se está sacando. Volver atrás con
    # `reserva_id` en `NOT NULL` es imposible sin esto — cualquier fila de
    # buffet lo violaría—, así que el borrado es explícito y no un efecto
    # colateral del ALTER.
    op.execute("DELETE FROM pagos_de_reserva WHERE reserva_id IS NULL")
    op.drop_constraint("ck_pagos_reserva_origen", "pagos_de_reserva", type_="check")
    op.drop_index("uq_pagos_venta_aprobado", table_name="pagos_de_reserva")
    op.drop_column("pagos_de_reserva", "venta_id")
    op.alter_column(
        "pagos_de_reserva", "reserva_id", existing_type=sa.Integer(), nullable=False
    )
