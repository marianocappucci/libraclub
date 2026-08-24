#!/usr/bin/env python3
"""Panel de administración de LibraClub.

    python3 scripts/panel_admin.py            → menú interactivo
    python3 scripts/panel_admin.py listar
    python3 scripts/panel_admin.py backup micliente

Envoltorio de configuración sobre `libracore.provisioning.panel_admin`. Es
además lo que consume el backoffice compartido (`libra-backoffice`) a través de
`libracore.admin.services`: sin este archivo, LibraClub se podría listar pero
no operar.
"""
from pathlib import Path

from libracore.provisioning import (
    client_from_config,
    configure,
    forward_host_from_config,
    le_email_from_config,
    npm_available,
)
from libracore.provisioning.panel_admin import (
    _set_servicio_estado,
    cli,
    cmd_activar,
    cmd_actualizar,
    cmd_backup,
    cmd_backup_all,
    cmd_eliminar,
    cmd_estado_servicio,
    cmd_info,
    cmd_list_backups,
    cmd_listar,
    cmd_logs,
    cmd_npm_crear,
    cmd_npm_eliminar,
    cmd_npm_listar,
    cmd_pausar,
    cmd_restart,
    cmd_restore_db,
    cmd_start,
    cmd_stop,
    cmd_suspender,
    compose,
    container_status,
    find_client,
    interactive,
    load_clients,
    pick_client,
)

REPO_ROOT = Path(__file__).parent.parent.resolve()

#: Re-exportados: es la interfaz que consume el backoffice compartido a través
#: de `libracore.admin.services`. Van en `__all__` para que quede escrito que la
#: razón de importarlos es exponerlos, y para que el linter no los borre por
#: "no usados".
__all__ = [
    "cli", "cmd_activar", "cmd_actualizar", "cmd_backup", "cmd_backup_all",
    "cmd_eliminar", "cmd_estado_servicio", "cmd_info", "cmd_list_backups",
    "cmd_listar", "cmd_logs", "cmd_npm_crear", "cmd_npm_eliminar",
    "cmd_npm_listar", "cmd_pausar", "cmd_restart", "cmd_restore_db",
    "cmd_start", "cmd_stop", "cmd_suspender", "compose", "container_status",
    "find_client", "interactive", "load_clients", "pick_client",
    "_set_servicio_estado",
    "client_from_config", "configure", "forward_host_from_config",
    "le_email_from_config", "npm_available",
    "CLIENTES_DIR", "REPO_ROOT", "_NPM_AVAILABLE",
]

# 🔑 **Este bloque tiene que decir lo MISMO que el del otro script.**
# `configure()` pisa un `_cfg` GLOBAL y `libracore.admin.services` importa los
# dos módulos en el mismo proceso, así que gana el último import. Si uno se
# desviara del otro, un alta hecha después de un listado saldría con la
# configuración del que ganó. `tests/test_provisioning.py` lo verifica
# comparando los dos, no leyendo uno.
configure(
    product_name="LIBRACLUB",
    image_name="libraclub:latest",
    container_prefix="libraclub",
    # Vestigio del tiempo de SQLite: con `postgres=True` no se crea ningún
    # archivo. Sigue siendo obligatorio y el backoffice lo muestra, así que se
    # deja el nombre que le correspondería.
    db_filename="libraclub.db",
    repo_root=REPO_ROOT,
    # Este producto nace sobre PostgreSQL: no hay instancias SQLite que migrar.
    postgres=True,
    # La misma imagen que el CI, la de dev y la del cliente. El collation viene
    # de la imagen y `-alpine` ordena por bytes: una instancia nueva que ordenara
    # distinto que dev sería un cambio de comportamiento invisible.
    postgres_image="postgres:16",
    # El backup del cron arma el MISMO ZIP que la pantalla de Configuración →
    # Datos / Backup, en vez de un `tar.gz` aparte que la pantalla no lista y el
    # cliente no puede restaurar. Este producto puede prenderlo porque su
    # pantalla sale de `libracore.respaldo` (ver `build_backup_router` en
    # `app/main.py`).
    backup_zip=True,
    # 🔴 **El deploy corre las migraciones.** Sin esto, `panel_admin.py
    # actualizar` mueve la instancia a la imagen nueva y **nadie aplica las
    # revisiones que viajaron adentro**: los otros `alembic upgrade` del repo
    # están en `semilla_dev.py`, `reset_demo.sh` y la suite, ninguno en el
    # camino de deploy. Le pasó a la `0008` del cobro con QR, que llegó a `main`
    # el 2026-08-24 sin nadie que la corriera.
    #
    # LibraCore lo ejecuta con `compose run --rm` **antes** del `up -d`: la
    # migración corre con el código nuevo mientras la instancia todavía sirve el
    # viejo, y si falla aborta el deploy en vez de dejar código nuevo sobre
    # esquema viejo. Ver `cmd_actualizar` en `libracore.provisioning`.
    # ⚠️ **Anidada, no plana.** Desde LibraCore `v1.51.0` esto es una secuencia
    # de comandos, no un comando: la forma plana la rechaza el motor con
    # `TypeError` al importar este módulo. Hasta el 2026-08-24 acá decía
    # `("alembic", "upgrade", "head")`, que era válido contra el `v1.48.0` que
    # este repo pineaba — pero el panel del VPS ya tenía instalado el `1.51.0`,
    # así que el próximo deploy de este producto habría roto el panel entero al
    # importar: `listar`, `backup` y `actualizar` incluidos.
    #
    # Una sola cadena: las revisiones de este repo crean sus 18 tablas propias
    # —`canchas`, `reservas`, `torneos`, `sucursales`— y ninguna del esquema de
    # LibraGenda, así que no hay una segunda `alembic_version` que aplicar antes.
    # Gestiolibra y MedLibra sí la tienen y por eso declaran dos comandos.
    migraciones=(("alembic", "upgrade", "head"),),
    # `health_path` **no se pasa**: desde hoy este producto sirve `/health`
    # además de `/salud`, que es el default del motor y la ruta de los otros
    # seis. Ver el comentario en `app/routers/salud.py` — con la SPA horneada,
    # apuntar el chequeo a una ruta inexistente devuelve 200 igual.
    #
    # Desde dónde empieza a buscar puerto un cliente nuevo. Hasta el 8099
    # inclusive está tomado por el resto del ecosistema —el 8099 lo ocupa la
    # instancia `dev` de este mismo producto— medido con `ss -ltn` en el VPS el
    # 2026-08-20.
    #
    # No es el puerto que se asigna: `next_port()` arranca acá y sube mientras
    # el número esté en uso, y el conjunto de usados sale de `docker ps -aq` del
    # host **entero**, contenedores parados incluidos. O sea que dos productos
    # con el mismo `base_port` no chocan; lo que sí importa es no arrancar la
    # búsqueda en un rango lleno.
    base_port=8100,
)

# Re-exportado por compatibilidad con cualquier uso directo de este módulo.
CLIENTES_DIR = REPO_ROOT / "clientes"

_NPM_AVAILABLE = npm_available()

if __name__ == "__main__":
    cli()
