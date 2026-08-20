"""Esquema inicial: sucursales, canchas, clientes, feriados, tarifas, series y reservas.

Revision ID: 0001_inicial
Revises:
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_inicial"
down_revision = None
branch_labels = None
depends_on = None


#: 🔴 Escrito **literal** y no derivado de `app.models.enums.ESTADOS_QUE_OCUPAN`.
#: Una migración es un registro histórico: si mañana se agrega un estado, esta
#: migración tiene que seguir describiendo lo que hizo el 2026-08-20, no lo que
#: dice el código de hoy. Lo que impide la divergencia es el test
#: `test_constraint_coincide_con_el_enum`, que compara el constraint **vivo en la
#: base** contra el enum — no un import acá.
ESTADOS_QUE_OCUPAN_SQL = (
    "'provisoria', 'pendiente_pago', 'confirmada', 'jugada', 'bloqueo'"
)


def upgrade() -> None:
    # `btree_gist` es lo que permite meter un `cancha_id WITH =` adentro de un
    # índice GiST: sin la extensión, GiST no sabe comparar un entero por
    # igualdad y el `ADD CONSTRAINT` falla con "data type integer has no default
    # operator class for access method gist".
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "sucursales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("direccion", sa.String(160)),
        sa.Column("localidad", sa.String(80)),
        sa.Column("telefono", sa.String(40)),
        sa.Column("email", sa.String(120)),
        sa.Column("punto_venta_arca", sa.Integer()),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observaciones", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("updated_by", sa.Integer()),
        sa.UniqueConstraint("nombre", name="uq_sucursales_nombre"),
    )
    op.create_index(
        "uq_sucursales_punto_venta",
        "sucursales",
        ["punto_venta_arca"],
        unique=True,
        postgresql_where=sa.text("punto_venta_arca IS NOT NULL"),
    )

    op.create_table(
        "canchas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sucursal_id", sa.Integer(), sa.ForeignKey("sucursales.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("nombre", sa.String(80), nullable=False),
        sa.Column(
            "deporte",
            sa.Enum("padel", "futbol", "tenis", "basquet", "voley", "hockey", "otro", name="deporte"),
            nullable=False,
            server_default="padel",
        ),
        sa.Column("duracion_turno_min", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("techada", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("iluminacion", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("superficie", sa.String(40)),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observaciones", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("updated_by", sa.Integer()),
        sa.UniqueConstraint("sucursal_id", "nombre", name="uq_canchas_sucursal_nombre"),
        sa.CheckConstraint("duracion_turno_min > 0 AND duracion_turno_min <= 480", name="ck_canchas_duracion_turno"),
    )
    op.create_index("ix_canchas_sucursal", "canchas", ["sucursal_id"])

    op.create_table(
        "clientes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("telefono", sa.String(40)),
        sa.Column("email", sa.String(120)),
        sa.Column("documento", sa.String(20)),
        sa.Column("cuit", sa.String(13)),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observaciones", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("updated_by", sa.Integer()),
    )
    op.create_index("ix_clientes_nombre", "clientes", ["nombre"])
    op.create_index("ix_clientes_telefono", "clientes", ["telefono"])

    op.create_table(
        "feriados",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sucursal_id", sa.Integer(), sa.ForeignKey("sucursales.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dia", sa.Date(), nullable=False),
        sa.Column("nombre", sa.String(80), nullable=False),
        sa.Column("cerrado", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("updated_by", sa.Integer()),
        sa.UniqueConstraint("sucursal_id", "dia", name="uq_feriados_sucursal_dia"),
    )
    op.create_index("ix_feriados_dia", "feriados", ["dia"])

    op.create_table(
        "tarifas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sucursal_id", sa.Integer(), sa.ForeignKey("sucursales.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cancha_id", sa.Integer(), sa.ForeignKey("canchas.id", ondelete="CASCADE")),
        sa.Column("nombre", sa.String(80), nullable=False),
        sa.Column(
            "alcance_dia",
            sa.Enum("todos", "dia_semana", "feriado", name="alcance_dia"),
            nullable=False,
            server_default="todos",
        ),
        sa.Column("dia_semana", sa.Integer()),
        sa.Column("hora_desde", sa.Time(), nullable=False),
        sa.Column("hora_hasta", sa.Time(), nullable=False),
        sa.Column("precio", sa.Numeric(12, 2), nullable=False),
        sa.Column("sena_porcentaje", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vigente_desde", sa.Date()),
        sa.Column("vigente_hasta", sa.Date()),
        sa.Column("prioridad", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("updated_by", sa.Integer()),
        sa.CheckConstraint("hora_desde < hora_hasta", name="ck_tarifas_franja"),
        sa.CheckConstraint("precio >= 0", name="ck_tarifas_precio"),
        sa.CheckConstraint("sena_porcentaje >= 0 AND sena_porcentaje <= 100", name="ck_tarifas_sena_porcentaje"),
        sa.CheckConstraint(
            "(alcance_dia = 'dia_semana' AND dia_semana IS NOT NULL AND dia_semana BETWEEN 0 AND 6) "
            "OR (alcance_dia <> 'dia_semana' AND dia_semana IS NULL)",
            name="ck_tarifas_dia_semana_coherente",
        ),
        sa.CheckConstraint(
            "vigente_hasta IS NULL OR vigente_desde IS NULL OR vigente_hasta >= vigente_desde",
            name="ck_tarifas_vigencia",
        ),
    )
    op.create_index("ix_tarifas_sucursal", "tarifas", ["sucursal_id"])
    op.create_index("ix_tarifas_cancha", "tarifas", ["cancha_id"])

    op.create_table(
        "series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cancha_id", sa.Integer(), sa.ForeignKey("canchas.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("cliente_id", sa.Integer(), sa.ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("dia_semana", sa.Integer(), nullable=False),
        sa.Column("hora", sa.Time(), nullable=False),
        sa.Column("duracion_min", sa.Integer(), nullable=False),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date()),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observaciones", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("updated_by", sa.Integer()),
        sa.CheckConstraint("dia_semana BETWEEN 0 AND 6", name="ck_series_dia_semana"),
        sa.CheckConstraint("duracion_min > 0 AND duracion_min <= 480", name="ck_series_duracion"),
        sa.CheckConstraint("hasta IS NULL OR hasta >= desde", name="ck_series_rango"),
    )
    op.create_index("ix_series_cancha", "series", ["cancha_id"])

    op.create_table(
        "reservas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cancha_id", sa.Integer(), sa.ForeignKey("canchas.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("cliente_id", sa.Integer(), sa.ForeignKey("clientes.id", ondelete="RESTRICT")),
        sa.Column("serie_id", sa.Integer(), sa.ForeignKey("series.id", ondelete="SET NULL")),
        sa.Column(
            "estado",
            sa.Enum(
                "provisoria", "pendiente_pago", "confirmada", "jugada",
                "cancelada", "ausente", "bloqueo",
                name="estado_reserva",
            ),
            nullable=False,
            server_default="confirmada",
        ),
        sa.Column(
            "origen",
            sa.Enum("mostrador", "telefono", "whatsapp", "portal", "serie", name="origen_reserva"),
            nullable=False,
            server_default="mostrador",
        ),
        sa.Column("comienza_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("termina_at", sa.DateTime(timezone=True), nullable=False),
        # Columna **generada**: la calcula PostgreSQL, nunca Python. Si fuera una
        # columna común, una reserva creada por un camino que se olvidara de
        # llenarla quedaría fuera del constraint de exclusión — invisible para la
        # garantía y perfectamente insertable encima de otra.
        sa.Column(
            "periodo",
            postgresql.TSTZRANGE(),
            sa.Computed("tstzrange(comienza_at, termina_at, '[)')", persisted=True),
            nullable=False,
        ),
        sa.Column("precio", sa.Numeric(12, 2)),
        sa.Column("sena", sa.Numeric(12, 2)),
        sa.Column("vence_at", sa.DateTime(timezone=True)),
        sa.Column("motivo", sa.String(200)),
        sa.Column("observaciones", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("updated_by", sa.Integer()),
        sa.CheckConstraint("termina_at > comienza_at", name="ck_reservas_intervalo"),
        sa.CheckConstraint(
            "(estado = 'bloqueo' AND cliente_id IS NULL) "
            "OR (estado <> 'bloqueo' AND cliente_id IS NOT NULL)",
            name="ck_reservas_cliente_segun_estado",
        ),
        sa.CheckConstraint("estado <> 'provisoria' OR vence_at IS NOT NULL", name="ck_reservas_provisoria_vence"),
        sa.CheckConstraint("precio IS NULL OR precio >= 0", name="ck_reservas_precio"),
        sa.CheckConstraint("sena IS NULL OR precio IS NULL OR sena <= precio", name="ck_reservas_sena"),
    )
    op.create_index("ix_reservas_cancha_comienza", "reservas", ["cancha_id", "comienza_at"])
    op.create_index("ix_reservas_cliente", "reservas", ["cliente_id"])
    op.create_index("ix_reservas_serie", "reservas", ["serie_id"])
    op.create_index(
        "ix_reservas_vence_at",
        "reservas",
        ["vence_at"],
        postgresql_where=sa.text("estado = 'provisoria'"),
    )

    # 🔑 **La garantía del producto.** Va como SQL literal y no por
    # `ExcludeConstraint`: es la línea más importante del schema y conviene que
    # se lea tal cual va a quedar en la base.
    op.execute(
        "ALTER TABLE reservas ADD CONSTRAINT ex_reservas_sin_superposicion "
        "EXCLUDE USING gist (cancha_id WITH =, periodo WITH &&) "
        f"WHERE (estado IN ({ESTADOS_QUE_OCUPAN_SQL}))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE reservas DROP CONSTRAINT IF EXISTS ex_reservas_sin_superposicion")
    op.drop_table("reservas")
    op.drop_table("series")
    op.drop_table("tarifas")
    op.drop_table("feriados")
    op.drop_table("clientes")
    op.drop_table("canchas")
    op.drop_index("uq_sucursales_punto_venta", table_name="sucursales")
    op.drop_table("sucursales")
    # Los tipos ENUM no se borran con las tablas: quedan huérfanos y el próximo
    # `upgrade` falla con "type already exists". Es la forma más común de que un
    # downgrade "funcione" y deje la base sin poder volver a migrar.
    for tipo in ("estado_reserva", "origen_reserva", "alcance_dia", "deporte"):
        op.execute(f"DROP TYPE IF EXISTS {tipo}")
    # `btree_gist` no se borra: puede haberla creado otra cosa, y dropearla
    # tumbaría cualquier índice que la esté usando.
