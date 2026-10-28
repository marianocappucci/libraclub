"""La seña de una reserva del mostrador tiene plazo (ADR-029, addendum del 2026-10-28).

Una `pendiente_pago` (la reserva tomada por teléfono o en el local) pasa a tener `vence_at`:
24 horas desde que se tomó, y nunca después de 2 horas antes del turno. Para que el barrido que
las vence (`ix_reservas_vence_at`) las encuentre, el índice parcial deja de ser sólo de las
provisorias del portal y cubre también a las `pendiente_pago`.

🔑 **No hay `UPDATE` de datos, y es la decisión.** Las `pendiente_pago` que ya existen quedan con
`vence_at` en `NULL`, que significa «sin plazo»: el barrido no las toca. La alternativa era darles
24 horas desde el despliegue, y era la peor: una reserva que el mostrador tomó hace tres semanas
con un «pagás cuando vengas» se liberaría sola al día siguiente de desplegar, sin que nadie lo
decidiera; y una de un turno que ya pasó (nunca se confirmó ni se canceló) vencería de golpe. Sin
plazo, lo único que se pierde es que esas reservas viejas no vencen solas —que es lo que pasaba
hasta hoy— y el mostrador las resuelve a mano. La regla vale para las que se tomen de acá en más.

Sin columna nueva ni constraint nuevo (un `CHECK` que exigiera `vence_at` a toda `pendiente_pago`
rompería a las existentes y a las que baja el espejo de LibraEdge de un nodo sin actualizar).

Revision ID: 0017_sena_del_mostrador_vence
Revises: 0016_avisos_y_promociones
Create Date: 2026-10-28
"""

from alembic import op

revision = "0017_sena_del_mostrador_vence"
down_revision = "0016_avisos_y_promociones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_reservas_vence_at", table_name="reservas")
    op.create_index(
        "ix_reservas_vence_at",
        "reservas",
        ["vence_at"],
        postgresql_where="estado IN ('provisoria', 'pendiente_pago')",
    )


def downgrade() -> None:
    op.drop_index("ix_reservas_vence_at", table_name="reservas")
    op.create_index(
        "ix_reservas_vence_at",
        "reservas",
        ["vence_at"],
        postgresql_where="estado = 'provisoria'",
    )
