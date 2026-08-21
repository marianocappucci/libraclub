"""La reserva recuerda su comprobante.

Revision ID: 0002_factura_reserva
Revises: 0001_inicial
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_factura_reserva"
down_revision = "0001_inicial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 🔴 **Sin FOREIGN KEY, y no es un olvido.** La factura vive en la base de
    # LibraCore y esta tabla en la del dominio: son dos bases distintas, así que
    # no hay integridad referencial que declarar. Lo que la reemplaza es el
    # UNIQUE de abajo, que es lo que de verdad importa acá.
    op.add_column("reservas", sa.Column("factura_id", sa.Integer(), nullable=True))

    # 🔑 **UNIQUE, y ésta es la línea que hace el trabajo.** Dos facturas por la
    # misma reserva son dos veces el mismo ingreso ante ARCA, y no se arregla
    # borrando: hace falta una nota de crédito. Un chequeo en Python no alcanza —
    # dos clicks simultáneos en "Facturar" pasan los dos por el `if` antes de que
    # cualquiera escriba. Acá lo corta la base.
    #
    # Parcial (`WHERE factura_id IS NOT NULL`): las reservas sin facturar son la
    # enorme mayoría y todas tienen `NULL`, que en un UNIQUE común no colisiona
    # entre sí pero igual paga el índice.
    op.create_index(
        "uq_reservas_factura",
        "reservas",
        ["factura_id"],
        unique=True,
        postgresql_where=sa.text("factura_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_reservas_factura", table_name="reservas")
    op.drop_column("reservas", "factura_id")
