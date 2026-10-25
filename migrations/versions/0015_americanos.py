"""Campeonatos americanos: games por set, zonas sin llaves, categorías y eventos (ADR-024).

Aditiva: columnas nuevas con default y dos tablas nuevas. Ningún torneo existente
cambia de comportamiento — `games_por_set` en `NULL` es «no se controlan los
games», `termina_en_zonas` en falso es «hay llaves» y `categoria`/`evento_id`
en `NULL` es «torneo suelto».

Revision ID: 0015_americanos
Revises: 0014_libraedge
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_americanos"
down_revision = "0014_libraedge"
branch_labels = None
depends_on = None

#: El CHECK de antes (0006) y el de ahora. El de ahora admite además un torneo por
#: zonas que termina en las zonas: sin `clasifican_por_zona` y con `termina_en_zonas`.
#:
#: 🔴 Y cierra un agujero del de antes: con `cantidad_zonas` o `clasifican_por_zona`
#: en `NULL`, `NULL >= 2` da `NULL` y un CHECK **acepta** el `NULL` — un torneo por zonas
#: sin esos datos entraba. Por eso el `IS NOT NULL` explícito. La API nunca los dejó
#: pasar, así que no hay filas que lo incumplan.
CHECK_ANTERIOR = (
    "(formato = 'zonas' AND cantidad_zonas >= 2 "
    " AND clasifican_por_zona BETWEEN 1 AND 2) "
    "OR (formato <> 'zonas' AND cantidad_zonas IS NULL "
    " AND clasifican_por_zona IS NULL)"
)
CHECK_NUEVO = (
    "(formato = 'zonas' AND cantidad_zonas IS NOT NULL AND cantidad_zonas >= 2 AND ("
    "  (NOT termina_en_zonas AND clasifican_por_zona IS NOT NULL "
    "   AND clasifican_por_zona BETWEEN 1 AND 2) "
    "  OR (termina_en_zonas AND clasifican_por_zona IS NULL))) "
    "OR (formato <> 'zonas' AND cantidad_zonas IS NULL "
    " AND clasifican_por_zona IS NULL AND NOT termina_en_zonas)"
)


def upgrade() -> None:
    op.create_table(
        "eventos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("observaciones", sa.String(), nullable=True),
        sa.CheckConstraint("hasta IS NULL OR hasta >= desde", name="ck_eventos_rango"),
        sa.ForeignKeyConstraint(["sucursal_id"], ["sucursales.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sucursal_id", "nombre", name="uq_eventos_sucursal_nombre"),
    )
    op.create_index("ix_eventos_sucursal", "eventos", ["sucursal_id"])

    op.create_table(
        "eventos_canchas",
        sa.Column("evento_id", sa.Integer(), nullable=False),
        sa.Column("cancha_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["evento_id"], ["eventos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cancha_id"], ["canchas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("evento_id", "cancha_id"),
    )

    op.add_column("torneos", sa.Column("games_por_set", sa.Integer(), nullable=True))
    op.add_column(
        "torneos",
        sa.Column("termina_en_zonas", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
    )
    op.add_column("torneos", sa.Column("categoria", sa.String(length=60), nullable=True))
    op.add_column("torneos", sa.Column("evento_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_torneos_evento", "torneos", "eventos", ["evento_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_torneos_evento", "torneos", ["evento_id"])
    op.create_index(
        "uq_torneos_evento_categoria", "torneos", ["evento_id", "categoria"],
        unique=True, postgresql_where=sa.text("evento_id IS NOT NULL"),
    )

    op.drop_constraint("ck_torneos_zonas_coherente", "torneos", type_="check")
    op.create_check_constraint("ck_torneos_zonas_coherente", "torneos", CHECK_NUEVO)
    op.create_check_constraint(
        "ck_torneos_games_por_set", "torneos",
        "games_por_set IS NULL OR "
        "(games_por_set IN (6, 9) AND deporte IN ('padel', 'tenis'))",
    )


def downgrade() -> None:
    # 🔴 Un torneo que termina en las zonas no tiene `clasifican_por_zona`, y el
    # CHECK de antes lo exige entre 1 y 2. Al bajar se le pone 1 (pasa sólo el
    # primero de cada zona): es lo más cercano a «el primero de cada zona es el
    # campeón», y la alternativa es no poder bajar. Los games por set, la
    # categoría y el evento se pierden: son columnas que no existían.
    op.drop_constraint("ck_torneos_games_por_set", "torneos", type_="check")
    # 🔑 El CHECK nuevo se saca ANTES del UPDATE: con él puesto, un torneo con
    # `termina_en_zonas` y `clasifican_por_zona = 1` es justo lo que prohíbe.
    op.drop_constraint("ck_torneos_zonas_coherente", "torneos", type_="check")
    op.execute(
        "UPDATE torneos SET clasifican_por_zona = 1 "
        "WHERE termina_en_zonas AND clasifican_por_zona IS NULL"
    )
    op.create_check_constraint("ck_torneos_zonas_coherente", "torneos", CHECK_ANTERIOR)

    op.drop_index("uq_torneos_evento_categoria", table_name="torneos")
    op.drop_index("ix_torneos_evento", table_name="torneos")
    op.drop_constraint("fk_torneos_evento", "torneos", type_="foreignkey")
    op.drop_column("torneos", "evento_id")
    op.drop_column("torneos", "categoria")
    op.drop_column("torneos", "termina_en_zonas")
    op.drop_column("torneos", "games_por_set")

    op.drop_table("eventos_canchas")
    op.drop_index("ix_eventos_sucursal", table_name="eventos")
    op.drop_table("eventos")
