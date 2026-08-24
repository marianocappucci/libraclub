"""El cobro con QR de MercadoPago en el mostrador.

Revision ID: 0008_cobro_con_qr
Revises: 0007_bloqueo_cancelado
Create Date: 2026-08-23

Hasta acá `pagos_de_reserva` era **sólo del portal**: el jugador reserva desde
el celular, paga, y el webhook confirma el turno. El cobro con QR del mostrador
usa la misma tabla —es el mismo pago de MercadoPago, con el mismo
`external_reference` y el mismo webhook— pero hace algo distinto al acreditarse:
la reserva ya está confirmada, y lo que falta es el movimiento de caja y la
factura.

Dos columnas, y ninguna es cosmética:

- **`canal`** dice de dónde vino el pago. Sin esto, distinguirlos obligaría a
  mirar el prefijo de la referencia, que es información de negocio escondida en
  un string. Es un `ENUM` de PostgreSQL y no un `varchar`, igual que el resto de
  los enums de este producto: un varchar con convención admite el valor que
  nadie previó, y el que lo descubre es el reporte que no cuadra.

- **`caja_movimiento_id`** es la marca de que este pago ya entró a la caja.
  🔴 **No se apoya en la idempotencia de `create_caja_movimiento`, y no es
  desconfianza:** ese chequeo es por `(referencia, factura_id)`, así que un
  primer intento sin factura —porque ARCA estaba caído— y un reintento que sí
  factura **no se ven entre sí** y entran dos veces. Sería el mismo ingreso
  contado dos veces en el arqueo del turno.

  ⚠️ **No lleva FK: apunta a la OTRA base.** `caja_movimientos` vive en la base
  de LibraCore, separada de la del dominio (ver `servicios/facturacion.py`).
  PostgreSQL no puede validar esa referencia y no hay que pedirle que lo intente.

`canal` entra con `server_default 'portal'` porque las filas que ya existen son
todas del portal — era lo único que había. El default se **saca** después de
llenar: dejarlo puesto haría que una fila nueva sin canal explícito se guarde
como del portal sin que nadie lo decida.
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_cobro_con_qr"
down_revision = "0007_bloqueo_cancelado"
branch_labels = None
depends_on = None

CANAL = sa.Enum("portal", "mostrador", name="canal_pago")


def upgrade() -> None:
    CANAL.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "pagos_de_reserva",
        sa.Column("canal", CANAL, nullable=False, server_default="portal"),
    )
    op.alter_column("pagos_de_reserva", "canal", server_default=None)
    op.add_column(
        "pagos_de_reserva",
        sa.Column("caja_movimiento_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pagos_de_reserva", "caja_movimiento_id")
    op.drop_column("pagos_de_reserva", "canal")
    CANAL.drop(op.get_bind(), checkfirst=True)
