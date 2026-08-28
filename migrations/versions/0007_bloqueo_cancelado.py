"""Un bloqueo se tiene que poder cancelar.

Revision ID: 0007_bloqueo_cancelado
Revises: 0006_torneos
Create Date: 2026-08-21

🔴 **Arregla un 500 que existía desde `0001`.** `ck_reservas_cliente_segun_estado`
decía que toda fila que no fuera `bloqueo` tenía que tener cliente — y un bloqueo
cancelado deja de ser `bloqueo` sin ganar un cliente, así que la base lo
rechazaba.

O sea que las dos mitades del producto se contradecían y ninguna lo sabía:

- `servicios/reservas.py` declara `BLOQUEO -> {CANCELADA}` como transición
  válida;
- `DetalleDeReserva.tsx` ofrece el botón **«Quitar bloqueo»**, que manda
  exactamente esa transición;
- y la base contestaba `CheckViolation`, que el router no traduce, así que
  llegaba al operador como un 500.

Lo encontró la reprogramación de un partido de torneo, que necesita liberar el
bloqueo viejo antes de tomar el nuevo. La suite no lo veía porque ningún test
cancelaba un bloqueo: se probaba que se creara y que impidiera reservar encima,
que es lo que uno piensa en probar de un bloqueo.

La regla nueva dice lo que la vieja quería decir: **el cliente es obligatorio
mientras la fila esté viva**. Una fila cancelada ya no ocupa nada ni se factura,
y qué tenía en `cliente_id` deja de ser una regla del dominio.
"""

import sqlalchemy as sa  # noqa: F401  (lo usa el `op.create_check_constraint`)
from alembic import op

revision = "0007_bloqueo_cancelado"
down_revision = "0006_torneos"
branch_labels = None
depends_on = None

NOMBRE = "ck_reservas_cliente_segun_estado"

VIEJA = (
    "(estado = 'bloqueo' AND cliente_id IS NULL) "
    "OR (estado <> 'bloqueo' AND cliente_id IS NOT NULL)"
)
NUEVA = (
    "estado = 'cancelada' "
    "OR (estado = 'bloqueo' AND cliente_id IS NULL) "
    "OR (estado NOT IN ('bloqueo', 'cancelada') AND cliente_id IS NOT NULL)"
)


def upgrade() -> None:
    op.drop_constraint(NOMBRE, "reservas", type_="check")
    op.create_check_constraint(NOMBRE, "reservas", NUEVA)


def downgrade() -> None:
    # ⚠️ El downgrade **falla si ya hay bloqueos cancelados**, y está bien que
    # falle: son filas que la regla vieja no admite. Borrarlas para que el
    # downgrade pase sería perder datos en silencio.
    op.drop_constraint(NOMBRE, "reservas", type_="check")
    op.create_check_constraint(NOMBRE, "reservas", VIEJA)
