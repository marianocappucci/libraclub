from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, inspect, pool, text

from app.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

url = os.environ.get("DATABASE_URL")
if not url:
    raise RuntimeError("Falta DATABASE_URL: LibraClub migra sobre PostgreSQL.")
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata

#: 🔴 **La tabla de versión es PROPIA de este producto, no `alembic_version`.**
#:
#: `alembic_version` es el nombre por defecto y es el que usa la cadena de
#: LibraCore (`libracore-migrar`). Hasta ahora no importaba: el core vivía en
#: `libraclub_core`, otra base. Con **una sola base** (ADR-020, decisión del
#: humano del 2026-10-22) las dos cadenas migran en la misma, y dos cadenas sobre
#: una tabla de versión se pisan la revisión: la segunda en correr cree que la
#: primera es suya y muere con *Can't locate revision identified by
#: '0028_caja_del_nodo'* (medido el 2026-10-22 sobre una base vacía).
#:
#: LibraCargo, LibraDesk, Gestiolibra y MedLibra ya usan el nombre con sufijo.
VERSION_TABLE = "alembic_version_libraclub"

#: El nombre que tenía hasta el 2026-10-22, y que sigue teniendo en cada base que
#: no se migró desde entonces (`libraclub-dev`, `libraclub-demo`).
VERSION_TABLE_VIEJA = "alembic_version"


def _revisiones_propias() -> set[str]:
    """Los ids de TODAS las revisiones de la cadena de este repo."""
    return {r.revision for r in ScriptDirectory.from_config(config).walk_revisions()}


def adoptar_la_tabla_de_version_vieja(connection) -> bool:
    """Renombra `alembic_version` a la tabla propia si ahí está la cadena de LibraClub.

    **Autorrenombre**: una base de antes tiene la revisión de este producto en
    `alembic_version`. Con `VERSION_TABLE` nuevo y la tabla vieja, Alembic no
    encontraría revisión, creería la base sin migrar y arrancaría en la `0001`
    contra tablas que ya existen: el deploy abortaría. Por eso el renombre es
    parte de la migración y no un paso manual del operador.

    Corre **dentro de la transacción de la migración** (se llama adentro de
    `begin_transaction()`): si la migración falla, el renombre se deshace y la
    base queda como estaba.

    Sólo renombra si hace falta y si la tabla es de acá:

    - ya existe `alembic_version_libraclub`: no hay nada que adoptar;
    - no existe `alembic_version`: base nueva, la crea Alembic;
    - `alembic_version` guarda una revisión que NO es de esta cadena (es la de
      LibraCore, en una base unida): esa tabla es del motor y no se toca.

    Devuelve si renombró.
    """
    tablas = set(inspect(connection).get_table_names())
    if VERSION_TABLE in tablas or VERSION_TABLE_VIEJA not in tablas:
        return False
    revisiones = set(connection.execute(text(f"SELECT version_num FROM {VERSION_TABLE_VIEJA}")).scalars())
    if not revisiones or not revisiones <= _revisiones_propias():
        return False
    connection.execute(text(f"ALTER TABLE {VERSION_TABLE_VIEJA} RENAME TO {VERSION_TABLE}"))
    # Un RENAME de tabla **no renombra sus restricciones**: la clave primaria
    # seguiría llamándose `alembic_version_pkc`, el nombre de cualquier cadena sin
    # sufijo, y PostgreSQL no admite dos restricciones con el mismo nombre en un
    # schema. Con eso la cadena del motor moriría al crear SU `alembic_version`
    # en la misma base (*relation "alembic_version_pkc" already exists*, medido en
    # LibraCargo el 2026-10-05, ADR-029 de ese producto).
    clave = inspect(connection).get_pk_constraint(VERSION_TABLE).get("name")
    if clave and clave != f"{VERSION_TABLE}_pkc":
        connection.execute(text(f'ALTER TABLE {VERSION_TABLE} RENAME CONSTRAINT "{clave}" TO {VERSION_TABLE}_pkc'))
    return True


def _es_de_este_producto(objeto, nombre, tipo, reflejado, comparado) -> bool:
    """Lo que `alembic check` y el autogenerate comparan: sólo las tablas de este producto.

    Con una sola base, en la misma viven las tablas del motor (LibraCore y
    LibraCommerce) y las de `libraauth`, que migran sus propias cadenas. Una
    tabla que está en la base y no en los modelos de acá no es «un cambio sin
    migrar»: es de otro.
    """
    if tipo == "table" and reflejado and comparado is None:
        return nombre in target_metadata.tables
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
            include_object=_es_de_este_producto,
        )
        with context.begin_transaction():
            adoptar_la_tabla_de_version_vieja(connection)
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
