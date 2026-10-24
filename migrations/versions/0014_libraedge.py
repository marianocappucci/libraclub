"""libraedge: las tablas del nodo offline (LibraEdge, ADR-023).

Revision ID: 0014_libraedge
Revises: 0013_reservas_en_el_nodo
Create Date: 2026-10-24

Llama a las funciones del paquete en vez de re-expresar el DDL con `op.create_table(...)`: la fuente de verdad es el DDL de
LibraEdge, y re-escribirlo acá crearía **una segunda fuente que se desincroniza en el primer cambio** del motor. Es la misma
revisión que `0009_libraedge` de VentaLibra y `0003_libraedge` de Restolibra.

**Se crean en toda instancia, sea nodo o no.** Un central que nunca corra offline igual las necesita: `node_identity` para
autenticar a los nodos que le pushean (y para la pantalla «Sucursal sin internet»), `sync_inbox` para deduplicar operaciones
repetidas, `sync_changelog` para publicar la bajada y `libraedge_mapeo` para las reservas con id provisorio. Crearlas sólo
donde la instancia sea un nodo dejaría el schema de unas instancias distinto del de otras **en silencio**; por eso esta
revisión **no consulta** la identidad del nodo. Es idempotente (`CREATE TABLE IF NOT EXISTS`).

> El trigger del changelog **no** se instala acá: publicar una tabla es una decisión de aprovisionamiento del central
> (`libraedge-central nodo publicar`), no parte del schema del producto.
"""
from alembic import op
from libracore.db._postgres import ConnectionWrapper
from libraedge.db.changelog import init_changelog_schema
from libraedge.db.schema import init_schema as init_edge_schema

revision = "0014_libraedge"
down_revision = "0013_reservas_en_el_nodo"
branch_labels = None
depends_on = None


def upgrade():
    # `ConnectionWrapper` envuelve el bind de Alembic en la conexión que espera el DDL de la familia: traduce los `?`, el
    # `INTEGER PRIMARY KEY AUTOINCREMENT` y saltea el `PRAGMA foreign_keys = ON` con el que arranca `init_schema()` de LibraEdge,
    # que contra PostgreSQL reventaría.
    #
    # 🔑 Directo y no `libracore.db.migraciones.conexion_libracore(bind)`: esa elige el adaptador mirando si `libracore.db.core`
    # está configurada (`is_postgres()`), y una cadena de Alembic corre sin que nadie la haya configurado: devolvería la
    # conexión cruda de psycopg y el `PRAGMA` reventaría. LibraClub es PostgreSQL y nada más (`facturacion.configurar`).
    conn = ConnectionWrapper(op.get_bind().connection.driver_connection)
    init_edge_schema(conn)
    init_changelog_schema(conn)


def downgrade():
    # 🔴 Bajar esta revisión NO borra las tablas: el outbox puede tener operaciones que un nodo generó durante un corte y todavía
    # no confirmó, y no están en ningún otro lado. Las tablas quedan y volver a subir es idempotente.
    pass
