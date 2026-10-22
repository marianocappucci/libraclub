"""`actividad_log` con la forma de `libraauth`, sea cual sea el orden en que se crea.

Revision ID: 0012_actividad_log
Revises: 0011_qr_del_buffet
Create Date: 2026-10-22

Hasta acá la tabla la creaba el arranque de la app (`AuditoriaBase.metadata.create_all`),
en la base del dominio. Con **una sola base** (ADR-020) el motor comercial escribe en la
misma, y `libracommerce-migrar` —que corre antes que esta cadena— la crea primero con su
propio DDL: `ts TEXT` y `entidad_id INTEGER`. `libraauth` la declara `ts TIMESTAMP` y
`entidad_id VARCHAR`, y como el listener del ORM castea cada parámetro al tipo declarado
(`$5::VARCHAR` contra una columna `integer`), **cada escritura auditada del dominio
—una sucursal, una reserva, una cancha— moría con `DatatypeMismatch`**. Medido el
2026-10-22 sobre una base vacía con la cadena entera.

La forma de `libraauth` sirve a los dos escritores: el registrador crudo del motor
comercial manda el `ts` como texto ISO y el id como texto, que `timestamp` y `varchar`
aceptan (lo dice `crear_tabla_actividad_log`, ADR-022 de libraauth). La del motor
comercial sólo sirve al segundo. Por eso esta revisión **lleva la tabla a la forma de
`libraauth`** en vez de depender de quién llegó primero:

- no existe: la crea (el caso de una base nueva en la que esta cadena corrió antes que
  el arranque);
- existe como la dejó el motor comercial: convierte las dos columnas, conservando las filas
  (`USING ts::timestamp`; el id entero pasa a texto);
- ya es la de `libraauth` (`libraclub-dev` y `libraclub-demo` hoy): no hace nada.

No hay `downgrade` que valga: volver a `TEXT` perdería precisión y ninguna versión anterior
lo necesita, porque las dos formas se pueden escribir con el registrador crudo.
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_actividad_log"
down_revision = "0011_qr_del_buffet"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("actividad_log"):
        op.create_table(
            "actividad_log",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("ts", sa.DateTime(), nullable=False),
            sa.Column("usuario", sa.String(100), nullable=False),
            sa.Column("accion", sa.String(20), nullable=False),
            sa.Column("entidad", sa.String(50), nullable=False),
            sa.Column("entidad_id", sa.String(100), nullable=True),
            sa.Column("descripcion", sa.String(500), nullable=False),
            sa.Column("cambios", sa.Text(), nullable=True),
        )
        op.create_index("ix_actividad_log_ts", "actividad_log", ["ts"])
        op.create_index("ix_actividad_log_accion", "actividad_log", ["accion"])
        op.create_index("ix_actividad_log_entidad", "actividad_log", ["entidad"])
        return

    columnas = {c["name"]: c["type"] for c in inspector.get_columns("actividad_log")}
    if not isinstance(columnas["ts"], sa.DateTime):
        op.execute("ALTER TABLE actividad_log ALTER COLUMN ts TYPE timestamp USING ts::timestamp")
    if isinstance(columnas["entidad_id"], sa.Integer):
        op.execute(
            "ALTER TABLE actividad_log ALTER COLUMN entidad_id TYPE varchar(100) USING entidad_id::varchar"
        )


def downgrade():
    pass
