"""Torneos: competidores, zonas, fixture y resultados.

Revision ID: 0006_torneos
Revises: 0005_falta_uno
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_torneos"
down_revision = "0005_falta_uno"
branch_labels = None
depends_on = None

#: 🔴 **Los tipos ENUM se crean a mano y las columnas los usan con
#: `create_type=False`.** Es la trampa que ya mordió dos veces en este repo, y
#: tiene dos caras opuestas:
#:
#: - `deporte` **ya existe** —lo creó `0001` para `canchas`—, así que dejar que
#:   `create_table` lo cree otra vez aborta la migración con "type already
#:   exists". Le pasó a `0003` con `alcance_dia`.
#: - los tres nuevos **no existen**, y con `create_type=False` a secas nadie los
#:   crearía: la migración fallaría al crear la primera columna que los use. Le
#:   pasó a `0004`.
#:
#: Creándolos explícitamente arriba y apagando la creación automática abajo, las
#: dos caras quedan cubiertas por la misma regla y no hay que acordarse de cuál
#: es cuál en cada tabla.
FORMATO = postgresql.ENUM(
    "eliminacion", "liga", "zonas", name="formato_torneo", create_type=False
)
ESTADO = postgresql.ENUM(
    "armado", "sorteado", "finalizado", "cancelado",
    name="estado_torneo", create_type=False,
)
ETAPA = postgresql.ENUM("grupos", "llaves", name="etapa_torneo", create_type=False)

#: El que YA existe. Se declara igual para poder referenciarlo sin recrearlo.
DEPORTE = postgresql.ENUM(
    "padel", "futbol", "tenis", "basquet", "voley", "hockey", "otro",
    name="deporte", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    for tipo in (FORMATO, ESTADO, ETAPA):
        tipo.create(bind, checkfirst=False)

    op.create_table(
        "torneos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("deporte", DEPORTE, nullable=False),
        sa.Column("formato", FORMATO, nullable=False),
        sa.Column("estado", ESTADO, nullable=False, server_default="armado"),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date(), nullable=True),
        sa.Column("sets_para_ganar", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("cantidad_zonas", sa.Integer(), nullable=True),
        sa.Column("clasifican_por_zona", sa.Integer(), nullable=True),
        sa.Column("semilla", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("observaciones", sa.String(), nullable=True),
        sa.CheckConstraint("hasta IS NULL OR hasta >= desde", name="ck_torneos_rango"),
        sa.CheckConstraint(
            "sets_para_ganar BETWEEN 1 AND 5", name="ck_torneos_sets_para_ganar"
        ),
        # Los parámetros de zonas existen SÓLO en el formato que los usa. Un 1 y
        # un 0 para los otros formatos serían números que mienten, y el que los
        # lee no tendría cómo saber que no significan nada.
        sa.CheckConstraint(
            "(formato = 'zonas' AND cantidad_zonas >= 2 "
            " AND clasifican_por_zona BETWEEN 1 AND 2) "
            "OR (formato <> 'zonas' AND cantidad_zonas IS NULL "
            " AND clasifican_por_zona IS NULL)",
            name="ck_torneos_zonas_coherente",
        ),
        sa.ForeignKeyConstraint(["sucursal_id"], ["sucursales.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sucursal_id", "nombre", name="uq_torneos_sucursal_nombre"),
    )
    op.create_index("ix_torneos_sucursal", "torneos", ["sucursal_id"])

    op.create_table(
        "zonas_de_torneo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("torneo_id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["torneo_id"], ["torneos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("torneo_id", "nombre", name="uq_zonas_torneo_nombre"),
    )
    op.create_index("ix_zonas_torneo", "zonas_de_torneo", ["torneo_id"])

    op.create_table(
        "competidores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("torneo_id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("zona_id", sa.Integer(), nullable=True),
        sa.Column("siembra", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("observaciones", sa.String(), nullable=True),
        sa.CheckConstraint(
            "siembra IS NULL OR siembra >= 1", name="ck_competidores_siembra"
        ),
        sa.ForeignKeyConstraint(["torneo_id"], ["torneos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["zona_id"], ["zonas_de_torneo.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("torneo_id", "nombre", name="uq_competidores_torneo_nombre"),
    )
    op.create_index("ix_competidores_torneo", "competidores", ["torneo_id"])
    op.create_index("ix_competidores_zona", "competidores", ["zona_id"])
    # Dos cabezas de serie con el mismo número no se pueden ordenar, y el sorteo
    # tendría que elegir por criterio propio cuál va primero. Parcial: los que no
    # están sembrados son la mayoría y en PostgreSQL los NULL no colisionan.
    op.create_index(
        "uq_competidores_siembra", "competidores", ["torneo_id", "siembra"],
        unique=True, postgresql_where=sa.text("siembra IS NOT NULL"),
    )

    op.create_table(
        "integrantes_de_competidor",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competidor_id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("telefono", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["competidor_id"], ["competidores.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_integrantes_competidor", "integrantes_de_competidor", ["competidor_id"]
    )

    op.create_table(
        "partidos_de_torneo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("torneo_id", sa.Integer(), nullable=False),
        sa.Column("etapa", ETAPA, nullable=False),
        sa.Column("zona_id", sa.Integer(), nullable=True),
        sa.Column("ronda", sa.Integer(), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("competidor_a_id", sa.Integer(), nullable=True),
        sa.Column("competidor_b_id", sa.Integer(), nullable=True),
        sa.Column("avanza_a_id", sa.Integer(), nullable=True),
        sa.Column("avanza_a_slot", sa.String(length=1), nullable=True),
        sa.Column("reserva_id", sa.Integer(), nullable=True),
        sa.Column("ganador_id", sa.Integer(), nullable=True),
        sa.Column("finalizado", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(etapa = 'llaves' AND zona_id IS NULL) OR etapa = 'grupos'",
            name="ck_partidos_zona_segun_etapa",
        ),
        # Nadie juega contra sí mismo. Los dos pueden ser NULL —una llave que
        # espera dos ganadores— y por eso los `IS NULL` adelante: `NULL <> NULL`
        # da NULL, que un CHECK acepta.
        sa.CheckConstraint(
            "competidor_a_id IS NULL OR competidor_b_id IS NULL "
            "OR competidor_a_id <> competidor_b_id",
            name="ck_partidos_distintos",
        ),
        sa.CheckConstraint(
            "ganador_id IS NULL OR finalizado", name="ck_partidos_ganador_finalizado"
        ),
        sa.CheckConstraint(
            "(avanza_a_id IS NULL AND avanza_a_slot IS NULL) "
            "OR (avanza_a_id IS NOT NULL AND avanza_a_slot IN ('a', 'b'))",
            name="ck_partidos_avanza_coherente",
        ),
        sa.ForeignKeyConstraint(
            ["avanza_a_id"], ["partidos_de_torneo.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["competidor_a_id"], ["competidores.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["competidor_b_id"], ["competidores.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["ganador_id"], ["competidores.id"], ondelete="SET NULL"),
        # SET NULL y no CASCADE: cancelar el bloqueo de una cancha deja el
        # partido sin horario, no borra el partido del fixture.
        sa.ForeignKeyConstraint(["reserva_id"], ["reservas.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["torneo_id"], ["torneos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["zona_id"], ["zonas_de_torneo.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # La zona entra en la clave —si no, la fecha 1 de la Zona A choca con la
        # fecha 1 de la Zona B— y con `NULLS NOT DISTINCT`, porque en llaves y
        # en liga `zona_id` es NULL y dos NULL no colisionan en un UNIQUE
        # común: el cuadro admitiría dos finales.
        sa.UniqueConstraint(
            "torneo_id", "etapa", "zona_id", "ronda", "orden",
            name="uq_partidos_torneo_posicion",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_partidos_avanza", "partidos_de_torneo", ["avanza_a_id"])
    op.create_index("ix_partidos_torneo", "partidos_de_torneo", ["torneo_id"])
    op.create_index("ix_partidos_zona", "partidos_de_torneo", ["zona_id"])
    # Una reserva sostiene UN partido: sin esto, reprogramar mal dejaría dos
    # partidos colgados del mismo bloqueo y liberar uno le sacaría la cancha al
    # otro.
    op.create_index(
        "uq_partidos_reserva", "partidos_de_torneo", ["reserva_id"],
        unique=True, postgresql_where=sa.text("reserva_id IS NOT NULL"),
    )

    op.create_table(
        "parciales_de_partido",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("partido_id", sa.Integer(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("puntos_a", sa.Integer(), nullable=False),
        sa.Column("puntos_b", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("numero >= 1", name="ck_parciales_numero"),
        sa.CheckConstraint("puntos_a >= 0 AND puntos_b >= 0", name="ck_parciales_puntos"),
        sa.ForeignKeyConstraint(
            ["partido_id"], ["partidos_de_torneo.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("partido_id", "numero", name="uq_parciales_partido_numero"),
    )


def downgrade() -> None:
    op.drop_table("parciales_de_partido")
    op.drop_table("partidos_de_torneo")
    op.drop_table("integrantes_de_competidor")
    op.drop_table("competidores")
    op.drop_table("zonas_de_torneo")
    op.drop_table("torneos")
    # Los tipos NO se borran solos con las tablas: quedarían huérfanos y el
    # `upgrade` siguiente fallaría con "type already exists" — que es
    # exactamente el modo en que un downgrade deja la base peor que antes.
    #
    # `deporte` **no se toca**: lo creó `0001` y lo siguen usando las canchas.
    bind = op.get_bind()
    for tipo in (ETAPA, ESTADO, FORMATO):
        tipo.drop(bind, checkfirst=False)
