"""Reservas que se dan en un nodo sin conexión: exclusión partida y estado `en_conflicto`.

Revision ID: 0013_reservas_en_el_nodo
Revises: 0012_actividad_log
Create Date: 2026-10-24

ADR-022. Tres cambios, todos aditivos y sin tocar una fila existente:

1. **El estado `en_conflicto`** en el tipo `estado_reserva`. Es una reserva que se dio en el club
   sin conexión y que, al llegar al central, chocó con otra que ya estaba: gana la primera en
   llegar y ésta queda guardada pero no ocupa la cancha. No está en la cláusula `WHERE` de la
   exclusión, así que no la mira.
2. **`conflicto_con_id` y `estado_previo`**, para que la pantalla de conflictos diga contra qué
   chocó y a qué estado vuelve al resolverse. Nulas en toda fila que no está en conflicto.
3. **La exclusión GiST partida por el signo del id.** Una reserva dada en un nodo nace con un id
   provisorio negativo (`libraedge.mapeo`); la base del nodo tiene, además, lo que el espejo trae
   del central, que puede ocupar la misma cancha a la misma hora. Con una sola exclusión, el
   espejo no podría insertar esa fila y se trabaría la sincronización. Ahora:
   `ex_reservas_sin_superposicion` (la de siempre, con su nombre) cubre `id > 0` y
   `ex_reservas_del_nodo_sin_superposicion` cubre `id < 0`. En el central no hay ids negativos:
   la segunda es vacía y la primera hace lo mismo que antes.

> 🔑 **No hay backfill y no puede haberlo**: toda fila que ya está tiene `id > 0`, así que entra
> en la exclusión de siempre, y las dos columnas nuevas son `NULL`.

## Volver atrás

`downgrade` deja el esquema como estaba en `0012`, con dos salvedades que se dicen acá y no se
callan:

- **Se niega** si hay una reserva con id negativo: es de un nodo y todavía no subió. Con la
  exclusión única esa fila podría chocar con el espejo, y borrarla perdería una reserva. Hay que
  dejar que sincronice (o resolverla) antes.
- **El valor `en_conflicto` queda en el tipo**: PostgreSQL no permite quitar un valor de un
  `ENUM`. Las reservas que estén en ese estado pasan a `cancelada`, con el motivo
  «Estaba en conflicto» (y la versión anterior de la aplicación no sabe leer el estado).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_reservas_en_el_nodo"
down_revision = "0012_actividad_log"
branch_labels = None
depends_on = None

#: Los estados que ocupan la cancha. **Literales y no derivados del enum**: una migración es
#: un registro histórico, y no puede cambiar de significado si mañana se agrega un estado.
_OCUPAN = "'provisoria', 'pendiente_pago', 'confirmada', 'jugada', 'bloqueo'"

_EXCLUSION = (
    "ALTER TABLE reservas ADD CONSTRAINT {nombre} "
    "EXCLUDE USING gist (cancha_id WITH =, periodo WITH &&) "
    "WHERE (estado IN (" + _OCUPAN + ") AND id {signo} 0)"
)


def upgrade() -> None:
    # Un valor nuevo de un ENUM no se puede usar en la transacción que lo crea, y `ALTER TYPE ...
    # ADD VALUE` no corre dentro de un bloque transaccional en todas las versiones: Alembic
    # confirma lo hecho hasta acá, lo corre solo y sigue en una transacción nueva.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE estado_reserva ADD VALUE IF NOT EXISTS 'en_conflicto'")

    op.add_column("reservas", sa.Column("conflicto_con_id", sa.Integer(), nullable=True))
    op.add_column(
        "reservas",
        sa.Column(
            "estado_previo",
            postgresql.ENUM(name="estado_reserva", create_type=False),
            nullable=True,
        ),
    )

    op.execute("ALTER TABLE reservas DROP CONSTRAINT IF EXISTS ex_reservas_sin_superposicion")
    op.execute(_EXCLUSION.format(nombre="ex_reservas_sin_superposicion", signo=">"))
    op.execute(_EXCLUSION.format(nombre="ex_reservas_del_nodo_sin_superposicion", signo="<"))


def downgrade() -> None:
    bind = op.get_bind()
    provisorias = bind.execute(sa.text("SELECT count(*) FROM reservas WHERE id < 0")).scalar_one()
    if provisorias:
        raise RuntimeError(
            f"Hay {provisorias} reserva(s) con id provisorio (negativo): se dieron en un nodo y "
            "todavía no subieron al central. Dejá que sincronicen antes de volver a la 0012."
        )

    # Antes de soltar el estado hay que sacar las filas que lo usan (el valor del ENUM queda).
    op.execute(
        "UPDATE reservas SET estado = 'cancelada', "
        "motivo = COALESCE(NULLIF(motivo, ''), 'Estaba en conflicto'), "
        "vence_at = NULL "
        "WHERE estado = 'en_conflicto'"
    )

    op.execute("ALTER TABLE reservas DROP CONSTRAINT IF EXISTS ex_reservas_del_nodo_sin_superposicion")
    op.execute("ALTER TABLE reservas DROP CONSTRAINT IF EXISTS ex_reservas_sin_superposicion")
    op.execute(
        "ALTER TABLE reservas ADD CONSTRAINT ex_reservas_sin_superposicion "
        "EXCLUDE USING gist (cancha_id WITH =, periodo WITH &&) "
        f"WHERE (estado IN ({_OCUPAN}))"
    )
    op.drop_column("reservas", "estado_previo")
    op.drop_column("reservas", "conflicto_con_id")
