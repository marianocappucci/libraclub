"""Los avisos al cliente: confirmación, recordatorio y cancelación.

Revision ID: 0009_avisos
Revises: 0008_cobro_con_qr
Create Date: 2026-08-29

La brecha número uno contra el rubro: los cuatro competidores más vendidos del
mercado argentino mandan confirmación y recordatorio, y este producto no mandaba
nada. Había SMTP —lo usan el reset de clave y el envío de la factura— pero
ninguna reserva disparaba un mail.

**`avisos` es el registro de lo que se intentó, no una cola de lo que falta.**
No hay estado `pendiente` y no hay `programado_para`: lo que falta mandar se
deduce de las reservas en cada barrida. El motivo está en ADR-015 y se resume
así: una cola hay que llenarla desde cada camino que confirma un turno, y hoy
son tres —`crear()`, `cambiar_estado()` y `aplicar_pago_aprobado()`, que escribe
`reserva.estado = CONFIRMADA` **a mano** y no pasa por los otros dos—. Un cuarto
camino que se olvide de encolar no falla: simplemente no avisa, y eso no se
descubre.

`clientes.acepta_avisos` entra en `true` porque quien deja su email al reservar
espera que le llegue el turno; el `server_default` se **saca** después de llenar
las filas viejas, para que el valor de una fila nueva salga del modelo y no de
la base.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_avisos"
down_revision = "0008_cobro_con_qr"
branch_labels = None
depends_on = None

#: 🔴 Se crean a mano arriba y las columnas los usan con `create_type=False`,
#: que es la regla que fijó `0006` después de que la trampa mordiera dos veces:
#: dejar que `create_table` los cree además de crearlos acá aborta la migración
#: con *"type already exists"*, y `create_type=False` sin la creación explícita
#: la aborta al revés, al crear la primera columna que los usa.
TIPO = postgresql.ENUM(
    "confirmacion", "recordatorio", "cancelacion", name="tipo_aviso",
    create_type=False,
)
CANAL = postgresql.ENUM("email", "whatsapp", name="canal_aviso", create_type=False)
ESTADO = postgresql.ENUM(
    "enviado", "fallido", "omitido", name="estado_aviso", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    for tipo in (TIPO, CANAL, ESTADO):
        tipo.create(bind, checkfirst=False)

    op.create_table(
        "avisos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reserva_id", sa.Integer(), nullable=False),
        sa.Column("tipo", TIPO, nullable=False),
        sa.Column("canal", CANAL, nullable=False),
        sa.Column("horas_antes", sa.SmallInteger(), nullable=True),
        sa.Column("estado", ESTADO, nullable=False),
        sa.Column("destino", sa.String(length=160), nullable=False),
        sa.Column("asunto", sa.String(length=200), nullable=True),
        sa.Column("cuerpo", sa.Text(), nullable=True),
        sa.Column("detalle", sa.String(length=500), nullable=True),
        sa.Column("intentos", sa.SmallInteger(), nullable=False),
        sa.Column("enviado_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["reserva_id"], ["reservas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # 🔴 Lo único que impide mandar el mismo aviso dos veces. El cron corre
        # cada pocos minutos y la barrida vuelve a mirar las mismas reservas:
        # sin esta clave, un turno del viernes recibe un recordatorio por cada
        # corrida entre las 24 h y la hora del partido.
        #
        # `NULLS NOT DISTINCT` porque `horas_antes` es NULL en confirmación y
        # cancelación, y con la semántica normal dos NULL no colisionan — la
        # clave no aplicaría justamente a los dos tipos que nunca se repiten.
        sa.UniqueConstraint(
            "reserva_id",
            "tipo",
            "canal",
            "horas_antes",
            name="uq_avisos_reserva_tipo_canal",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_avisos_reserva", "avisos", ["reserva_id"])
    op.create_index("ix_avisos_estado", "avisos", ["estado"])

    op.add_column(
        "clientes",
        sa.Column(
            "acepta_avisos", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.alter_column("clientes", "acepta_avisos", server_default=None)


def downgrade() -> None:
    op.drop_column("clientes", "acepta_avisos")
    op.drop_index("ix_avisos_estado", table_name="avisos")
    op.drop_index("ix_avisos_reserva", table_name="avisos")
    op.drop_table("avisos")
    bind = op.get_bind()
    for tipo in (ESTADO, CANAL, TIPO):
        tipo.drop(bind, checkfirst=False)
