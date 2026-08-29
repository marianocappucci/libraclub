"""La política de cancelación y la devolución de la seña.

Revision ID: 0010_politica_cancelacion
Revises: 0009_avisos
Create Date: 2026-08-29

Hasta acá cancelar era gratis y sin consecuencias: el jugador apretaba el botón,
el turno se liberaba y **la seña se quedaba donde estaba**. Ni se devolvía ni
quedaba anotado que no se devolvía. Es la segunda brecha de la Fase A y la que
Alquila Tu Cancha vende como funcionalidad propia («devolución automática si
cancela con más de 24 horas»).

Dos cosas entran:

- **`sucursales.horas_de_cancelacion`**, la ventana. 🔴 Entra **`NULL`**, y eso
  es la mitad del diseño: `NULL` significa «esta sucursal no devuelve nada
  automáticamente», que es exactamente lo que hacen hoy las instancias que ya
  existen. Un `server_default` de 24 le prendería la devolución de plata a todas
  sin que nadie lo decida — y una migración no es el lugar donde se toman
  decisiones de negocio. La política se enciende cargando el número en la
  pantalla de la sucursal.

- **Dos estados nuevos de `estado_pago`** y las tres columnas de la devolución.
  `DEVOLUCION_PENDIENTE` es un estado y no un booleano porque **es plata que el
  complejo debe**: sin él, una devolución que falló se ve igual que una que
  nunca correspondió.

> ⚠️ **`ALTER TYPE ... ADD VALUE` y la transacción.** PostgreSQL 12+ lo permite
> adentro de una transacción, pero **el valor nuevo no se puede usar en esa
> misma transacción**. Por eso esta migración sólo agrega los valores y no
> actualiza ninguna fila con ellos. Si alguna vez hace falta backfill con un
> valor nuevo, va en una migración aparte — no es una preferencia de estilo, es
> un error de PostgreSQL.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_politica_cancelacion"
down_revision = "0009_avisos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sucursales", sa.Column("horas_de_cancelacion", sa.Integer(), nullable=True)
    )

    # Los dos valores nuevos del ENUM. `IF NOT EXISTS` para que re-correr la
    # migración sobre una base a medio migrar no aborte: `ADD VALUE` sin él
    # falla si el valor ya está, y eso deja la revisión sin poder terminar.
    op.execute("ALTER TYPE estado_pago ADD VALUE IF NOT EXISTS 'devolucion_pendiente'")
    op.execute("ALTER TYPE estado_pago ADD VALUE IF NOT EXISTS 'devuelto'")

    op.add_column(
        "pagos_de_reserva", sa.Column("refund_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "pagos_de_reserva",
        sa.Column("devuelto_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pagos_de_reserva",
        sa.Column("detalle_devolucion", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pagos_de_reserva", "detalle_devolucion")
    op.drop_column("pagos_de_reserva", "devuelto_at")
    op.drop_column("pagos_de_reserva", "refund_id")
    op.drop_column("sucursales", "horas_de_cancelacion")
    # 🔴 Los valores del ENUM **no se sacan**. PostgreSQL no tiene
    # `ALTER TYPE ... DROP VALUE`: habría que recrear el tipo entero, y con él
    # todas las columnas que lo usan. Dejar dos valores de más en un tipo es
    # inocuo; un downgrade que recrea tipos con datos vivos, no.
