"""La facturación de LibraClub, compuesta sobre `libracore.db`.

Hoy sólo la **configuración de ARCA**: qué CUIT emite, con qué punto de venta y
con qué certificado. La emisión viene después — ver el pendiente de F3 en
`wiki/entities/libraclub.md`.

🔴 **`libracore.db` va contra su PROPIA base, no la del dominio.** No es una
preferencia: `init_core_schema()` crea `usuarios` y `auth_log`, y este producto
**ya tiene esas dos tablas** con la forma de `libraauth`. Compartiendo base el
`CREATE TABLE IF NOT EXISTS` no las pisaría —así que nada fallaría— y libracore
quedaría leyendo tablas con las columnas de otro motor. El síntoma sería un
error de columna inexistente en la primera factura, meses después.

Es el mismo arreglo que ya usan Gestiolibra, MedLibra y VentaLibra, donde
además `usuarios` vive del lado de LibraCore. Acá vive del lado del dominio, así
que la separación es al revés — pero la conclusión es la misma: dos bases.

> ⚠️ **Dos bases significa que el backup tiene que llevarse las dos.** Un backup
> de una sola no se puede restaurar: o volvés el dominio y te quedan facturas de
> otro momento, o al revés. Y no falla — da un ZIP que se descarga y pesa poco.
> Ver `_instancia_a_respaldar` en `app/main.py`.
"""

from __future__ import annotations

from libracore.db import arca_config as db_arca_config
from libracore.db import caja as db_caja
from libracore.db import core as libracore_core
from libracore.db.schema import init_core_schema

#: Una sola "empresa" ARCA: LibraClub es de instancia única por cliente
#: (arquitectura silo), así que no hay lista de empresas para elegir. Es una
#: constante y no una tabla, igual que en los tres verticales de la familia.
EMPRESA = "complejo"


class FacturacionNoConfigurada(RuntimeError):
    """La instancia no tiene `LIBRACLUB_LIBRACORE_DATABASE_URL`.

    Se levanta al usar la facturación, **no al arrancar**: un complejo que
    todavía no factura tiene que poder levantar la aplicación igual.
    """


def configurar(database_url: str | None) -> bool:
    """Apunta `libracore.db` a su base y crea el schema. Devuelve si quedó lista.

    Idempotente: `init_core_schema` usa `CREATE TABLE IF NOT EXISTS`, así que
    llamarla en cada arranque no rompe nada.

    Sin URL no hace nada y devuelve `False` — la app levanta igual y lo único
    que no anda es la facturación.
    """
    global _hay_base
    if not database_url:
        _hay_base = False
        return False
    _crear_base_si_falta(database_url)
    libracore_core.configure(database_url)
    conexion = libracore_core.get_connection()
    try:
        init_core_schema(conexion)
        conexion.commit()
    finally:
        conexion.close()
    # Una caja por defecto, que es lo que después necesita el cierre por turno.
    if db_caja.get_default_caja_id() is None:
        caja_id = db_caja.create_caja_config(
            "Caja del complejo", "", list(db_caja.MEDIOS_PAGO_LABELS),
        )
        db_caja.set_default_caja(caja_id)
    _hay_base = True
    return True


#: Si esta instancia tiene base de LibraCore. Lo fija `configurar()` al arrancar.
_hay_base = False


def hay_base() -> bool:
    return _hay_base


def _crear_base_si_falta(url: str) -> None:
    """Crea la base de LibraCore si no existe todavía.

    🔑 **Para que el deploy sea `git pull` + rebuild y nada más.** La alternativa
    era un paso manual (`createdb`) en la receta del README, al lado de
    `alembic upgrade head` — y un paso manual que se olvida acá **tira el
    contenedor al arrancar**, porque psycopg no se puede conectar a una base que
    no existe. Un producto que ya tiene dos bases no puede depender de que
    alguien se acuerde de crear la segunda.

    Es idempotente y no toca nada si la base ya está. Requiere que el usuario de
    la conexión pueda crear bases; en los composes de la familia es el
    `POSTGRES_USER` del propio contenedor, que sí puede.
    """
    import psycopg

    servidor, _, nombre = url.rpartition("/")
    nombre = nombre.split("?", 1)[0]
    if not nombre:
        return
    # `postgres` es la base de mantenimiento: existe siempre y no se toca.
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as conexion:
        existe = conexion.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (nombre,)
        ).fetchone()
        if not existe:
            # Sin parámetro: `CREATE DATABASE` no los acepta. El nombre sale de
            # una variable de entorno del operador, no de una request.
            conexion.execute(f'CREATE DATABASE "{nombre}"')


def obtener_config_arca() -> dict | None:
    return db_arca_config.obtener_arca_config(EMPRESA)


def guardar_config_arca(
    cuit: str, punto_venta: int, clave_path: str, certificado_path: str,
    ambiente: str = "homologacion",
) -> dict:
    """Crea o actualiza la configuración de ARCA de esta instancia.

    🔑 `ambiente` por default en `homologacion`: una instancia recién configurada
    **no** puede emitir contra producción por omisión. Pasar a `produccion` es un
    acto deliberado, no lo que pasa si alguien deja el campo como vino.
    """
    if obtener_config_arca() is None:
        db_arca_config.crear_arca_config(
            EMPRESA, cuit, punto_venta, clave_path, certificado_path, ambiente,
        )
    else:
        db_arca_config.actualizar_arca_config(
            EMPRESA, cuit=cuit, punto_venta=punto_venta,
            clave_path=clave_path, certificado_path=certificado_path,
            ambiente=ambiente,
        )
    return obtener_config_arca()
