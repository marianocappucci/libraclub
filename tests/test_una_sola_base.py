"""Una sola base: dominio y LibraCore juntos (ADR-020), y el código anda con las dos formas.

Decisión del humano del 2026-10-22. Este PR no une ninguna instancia (`libraclub-dev` y
`libraclub-demo` seguían con `libraclub_core` aparte hasta que las unió `libracore-unir-bases`, el
mismo 2026-10-22; hoy no queda ninguna instancia con dos bases, y la variable del core se retiró del
compose de dev): el código anda con las dos formas, y estos tests son los que miden la de dos
bases, que la suite ya no cubre. Lo que se fija acá, en el orden en que lo vivió cada instancia:

1. **La tabla de versión es propia** (`alembic_version_libraclub`). Una base de antes tiene la
   revisión de este producto en `alembic_version` —el nombre de la cadena del motor— y se renombra
   sola en la primera migración, sin perder la revisión. Una base nueva crea la suya. Y en una base
   unida con la de LibraCore las dos cadenas conviven sin pisarse.
2. **La config** resuelve una sola base cuando falta la variable del core o es la misma URL, y
   respeta las dos cuando son distintas.
3. **El respaldo** lleva el core como segunda base sólo si es otra.
4. **La cadena de migraciones** trae `libracommerce-migrar`, en el orden que se midió.

Los tests que migran corren sobre bases descartables (`base_temporal`), nunca sobre la del worker.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from libracore.respaldo import Instancia

from app import database
from app import main as principal
from app.config import Config, misma_base
from app.servicios import facturacion

RAIZ = Path(__file__).resolve().parent.parent
BIN = Path(sys.executable).parent

TABLA_PROPIA = "alembic_version_libraclub"
TABLA_DEL_MOTOR = "alembic_version"


# ── herramientas ────────────────────────────────────────────────────────────


def _libpq(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _alembic() -> AlembicConfig:
    cfg = AlembicConfig(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    return cfg


def _cabeza_propia() -> str:
    return ScriptDirectory.from_config(_alembic()).get_current_head()


def _migrar_el_producto(url: str, monkeypatch) -> None:
    """`alembic upgrade head` del producto contra `url` (lo que lee `migrations/env.py`: `DATABASE_URL`)."""
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(_alembic(), "head")


def _correr(comando: list[str], url: str) -> subprocess.CompletedProcess:
    """Una cadena del deploy, como la corre el compose: las dos variables del producto sobre `url`."""
    entorno = {
        **os.environ,
        "DATABASE_URL": url,
        "LIBRACLUB_DATABASE_URL": url,
        "LIBRACLUB_LIBRACORE_DATABASE_URL": url,
    }
    r = subprocess.run(
        [str(BIN / comando[0]), *comando[1:]], env=entorno, capture_output=True, text=True, timeout=300,
    )
    assert r.returncode == 0, f"{' '.join(comando)}: {r.stderr[-2000:]}"
    return r


def _versiones(url: str) -> dict[str, str]:
    """`{tabla de versión: revisión}` de las que existan en la base."""
    with psycopg.connect(_libpq(url)) as con:
        tablas = [t for (t,) in con.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'alembic_version%'")]
        return {t: con.execute(f'SELECT version_num FROM "{t}"').fetchone()[0] for t in sorted(tablas)}


def _claves(url: str) -> set[str]:
    with psycopg.connect(_libpq(url)) as con:
        return {n for (n,) in con.execute("SELECT conname FROM pg_constraint WHERE conname LIKE 'alembic_version%'")}


def _volver_al_nombre_de_antes(url: str) -> None:
    """Deja la base como la dejaba este producto hasta el 2026-10-22 (así están `-dev` y `-demo`).

    El `RENAME` de la tabla —que es el que hizo cualquiera que renombrara a mano— no renombra
    su clave primaria: queda `alembic_version_pkc`, igual que en una base creada con el nombre
    por defecto.
    """
    with psycopg.connect(_libpq(url), autocommit=True) as con:
        con.execute(f"ALTER TABLE {TABLA_PROPIA} RENAME TO {TABLA_DEL_MOTOR}")
        con.execute(f"ALTER TABLE {TABLA_DEL_MOTOR} RENAME CONSTRAINT {TABLA_PROPIA}_pkc TO {TABLA_DEL_MOTOR}_pkc")


# ── 1. La tabla de versión propia, con autorrenombre ────────────────────────


def test_una_base_nueva_crea_su_propia_tabla_de_version(base_temporal, monkeypatch):
    url = base_temporal("nueva")
    _migrar_el_producto(url, monkeypatch)

    assert _versiones(url) == {TABLA_PROPIA: _cabeza_propia()}
    # Nada llamado `alembic_version`: ese nombre es de la cadena del motor.
    assert _claves(url) == {f"{TABLA_PROPIA}_pkc"}


def test_una_base_de_antes_se_renombra_sola_y_sigue_en_su_revision(base_temporal, monkeypatch):
    url = base_temporal("deantes")
    _migrar_el_producto(url, monkeypatch)
    _volver_al_nombre_de_antes(url)
    assert _versiones(url) == {TABLA_DEL_MOTOR: _cabeza_propia()}  # control: de verdad quedó como antes

    # Sin autorrenombre esto buscaría revisión en una tabla que no existe, creería la base sin
    # migrar y arrancaría en la 0001 contra tablas que ya existen: el deploy abortaría.
    _migrar_el_producto(url, monkeypatch)

    assert _versiones(url) == {TABLA_PROPIA: _cabeza_propia()}
    assert _claves(url) == {f"{TABLA_PROPIA}_pkc"}


def test_una_base_de_antes_en_una_revision_vieja_migra_desde_ahi(base_temporal, monkeypatch):
    """El autorrenombre conserva la revisión que tenía, no la pisa con la cabeza."""
    url = base_temporal("viejita")
    _migrar_el_producto(url, monkeypatch)
    monkeypatch.setenv("DATABASE_URL", url)
    command.downgrade(_alembic(), "0010_politica_cancelacion")
    _volver_al_nombre_de_antes(url)
    assert _versiones(url) == {TABLA_DEL_MOTOR: "0010_politica_cancelacion"}

    _migrar_el_producto(url, monkeypatch)  # corre sólo la 0011

    assert _versiones(url) == {TABLA_PROPIA: _cabeza_propia()}


def test_el_autorrenombre_se_deshace_si_la_migracion_falla(base_temporal, monkeypatch):
    """Va en la transacción de la migración: si ésta se cae, la base queda como estaba."""
    url = base_temporal("atomica")
    _migrar_el_producto(url, monkeypatch)
    command.downgrade(_alembic(), "0010_politica_cancelacion")
    _volver_al_nombre_de_antes(url)
    # Se rompe la 0011 a propósito: la columna que agrega ya existe.
    with psycopg.connect(_libpq(url), autocommit=True) as con:
        con.execute("ALTER TABLE pagos_de_reserva ADD COLUMN venta_id integer")

    with pytest.raises(Exception, match="venta_id"):
        _migrar_el_producto(url, monkeypatch)

    # Ni renombrada ni a medias: con el nombre de antes y en la revisión de antes.
    assert _versiones(url) == {TABLA_DEL_MOTOR: "0010_politica_cancelacion"}
    assert _claves(url) == {f"{TABLA_DEL_MOTOR}_pkc"}


def test_la_base_unida_con_la_del_motor_no_confunde_las_dos_cadenas(base_temporal, monkeypatch):
    """El caso de una instancia ya unida: la cadena del motor y la de este producto en la misma base."""
    url = base_temporal("unida")
    _correr(["libracore-migrar", "upgrade", "--prefijo", "libraclub"], url)
    del_motor = _versiones(url)
    assert list(del_motor) == [TABLA_DEL_MOTOR]  # control: el motor puso la suya

    # Acá `alembic_version` guarda una revisión del MOTOR: no es de este producto y no se toca.
    _migrar_el_producto(url, monkeypatch)

    ahora = _versiones(url)
    assert ahora[TABLA_DEL_MOTOR] == del_motor[TABLA_DEL_MOTOR]
    assert ahora[TABLA_PROPIA] == _cabeza_propia()
    assert ahora[TABLA_DEL_MOTOR] != ahora[TABLA_PROPIA]

    # Y repetir cualquiera de las dos no las mueve.
    _correr(["libracore-migrar", "upgrade", "--prefijo", "libraclub"], url)
    _migrar_el_producto(url, monkeypatch)
    assert _versiones(url) == ahora


def test_una_base_de_antes_que_se_une_con_el_motor_no_choca_en_la_clave(base_temporal, monkeypatch):
    """El camino completo de `libraclub-dev`: se renombra al desplegar y recién después se une.

    La cadena del motor tiene que crear **su** `alembic_version` en la base: si la clave de este
    producto siguiera llamándose `alembic_version_pkc`, PostgreSQL no admite dos con el mismo
    nombre en un schema y `libracore-migrar` muere con *relation "alembic_version_pkc" already
    exists* (medido en LibraCargo el 2026-10-05).
    """
    url = base_temporal("camino")
    _migrar_el_producto(url, monkeypatch)
    _volver_al_nombre_de_antes(url)

    _migrar_el_producto(url, monkeypatch)  # el deploy de este PR: autorrenombre
    _correr(["libracore-migrar", "upgrade", "--prefijo", "libraclub"], url)  # la unión: el motor llega a la misma base

    versiones = _versiones(url)
    assert versiones[TABLA_PROPIA] == _cabeza_propia()
    assert TABLA_DEL_MOTOR in versiones and versiones[TABLA_DEL_MOTOR] != versiones[TABLA_PROPIA]
    assert {f"{TABLA_PROPIA}_pkc", f"{TABLA_DEL_MOTOR}_pkc"} <= _claves(url)


@pytest.fixture
def instancia_de_una_base(base_temporal):
    """Lo que hace un alta nueva: las cuatro cadenas del deploy sobre una base vacía, una sola para todo."""
    from libracore.provisioning import get_config

    importlib.reload(importlib.import_module("scripts.panel_admin"))
    url = base_temporal("cadena")
    for comando in get_config().migraciones:
        _correr(list(comando), url)
    return url


def test_la_cadena_entera_del_deploy_corre_sobre_una_base_vacia(instancia_de_una_base):
    """Las cuatro cadenas en el orden que declara el producto, una sola base."""
    url = instancia_de_una_base

    versiones = _versiones(url)
    assert set(versiones) == {
        TABLA_DEL_MOTOR, TABLA_PROPIA, "alembic_version_libracommerce", "alembic_version_libraauth",
    }
    assert versiones[TABLA_PROPIA] == _cabeza_propia()
    # Y el buffet quedó en la base del dominio, que es la única.
    with psycopg.connect(_libpq(url)) as con:
        assert con.execute("SELECT to_regclass('public.sales')").fetchone()[0] is not None
        assert con.execute("SELECT to_regclass('public.reservas')").fetchone()[0] is not None


def test_la_app_arranca_sobre_esa_base_y_audita_el_dominio_y_el_buffet_en_el_mismo_log(
    instancia_de_una_base, tmp_path, monkeypatch
):
    """🔴 El defecto que sólo se ve con las dos escrituras en la misma base.

    `libracommerce-migrar` corre antes que la cadena de este producto y crea `actividad_log` con su
    DDL (`ts TEXT`, `entidad_id INTEGER`). El listener de `libraauth`, que audita el dominio, castea
    cada parámetro al tipo que declara (`$5::VARCHAR`): contra esa tabla, **toda escritura auditada
    —una sucursal, una reserva— moría con `DatatypeMismatch`**. La revisión `0012` lleva la tabla a la
    forma de `libraauth`; con ella, el dominio y el buffet escriben en la misma y `/logs` ve las dos.
    """
    from fastapi.testclient import TestClient

    from app.main import crear_app

    url = instancia_de_una_base
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", "clave-de-prueba")
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(
        database_url=url, entorno="test", debug=False, directorio_de_datos=str(tmp_path),
        libracore_database_url=_libpq(url),
    )
    assert config.core_en_la_del_dominio

    api = TestClient(crear_app(config), base_url="https://testserver")
    assert api.post("/auth/login", json={"username": "admin", "password": "clave-de-prueba"}).status_code == 200
    sucursal = api.post("/api/sucursales", json={
        "nombre": "Complejo Unico", "direccion": None, "localidad": None, "telefono": None, "email": None,
        "punto_venta_arca": None, "activa": True, "observaciones": None,
    })
    assert sucursal.status_code == 201, sucursal.text
    producto = api.post(f"/api/buffet/productos?sucursal_id={sucursal.json()['id']}", json={
        "nombre": "Gaseosa 500ml", "precio": "1200.00", "costo": "700.00", "stock_minimo": "6"})
    assert producto.status_code == 201, producto.text
    assert api.get("/api/caja/turnos").status_code == 200  # una ruta que lee LibraCore, en la misma base

    entidades = {f["entidad"] for f in api.get("/api/logs").json()["actividad"]}
    assert "sucursal" in entidades  # el dominio, por el listener de libraauth
    assert "producto" in entidades  # el buffet, por el registrador del motor comercial


# ── 1b. `actividad_log` con la forma de libraauth ───────────────────────────


def _tipos_de_actividad_log(url: str) -> dict[str, str]:
    with psycopg.connect(_libpq(url)) as con:
        return dict(con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'actividad_log' AND column_name IN ('ts', 'entidad_id')").fetchall())


FORMA_DE_LIBRAAUTH = {"ts": "timestamp without time zone", "entidad_id": "character varying"}


def test_la_0012_crea_actividad_log_si_no_existe(base_temporal, monkeypatch):
    url = base_temporal("log_nueva")
    _migrar_el_producto(url, monkeypatch)
    assert _tipos_de_actividad_log(url) == FORMA_DE_LIBRAAUTH


def test_la_0012_convierte_la_de_el_motor_comercial_y_conserva_las_filas(base_temporal, monkeypatch):
    url = base_temporal("log_comercial")
    _migrar_el_producto(url, monkeypatch)
    monkeypatch.setenv("DATABASE_URL", url)
    command.downgrade(_alembic(), "0011_qr_del_buffet")
    with psycopg.connect(_libpq(url), autocommit=True) as con:
        con.execute("DROP TABLE actividad_log")
        con.execute(  # el DDL de `libracommerce.db.auditoria`, tal cual
            "CREATE TABLE actividad_log (id BIGSERIAL PRIMARY KEY, ts TEXT NOT NULL, usuario TEXT NOT NULL "
            "DEFAULT 'Sistema', accion TEXT NOT NULL, entidad TEXT NOT NULL, entidad_id INTEGER, "
            "descripcion TEXT NOT NULL DEFAULT '', cambios TEXT)")
        con.execute("INSERT INTO actividad_log (ts, accion, entidad, entidad_id) "
                    "VALUES ('2026-10-22T19:08:47', 'crear', 'producto', 7)")
    assert _tipos_de_actividad_log(url) == {"ts": "text", "entidad_id": "integer"}  # control

    _migrar_el_producto(url, monkeypatch)

    assert _tipos_de_actividad_log(url) == FORMA_DE_LIBRAAUTH
    with psycopg.connect(_libpq(url)) as con:
        fila = con.execute("SELECT ts, entidad_id, entidad FROM actividad_log").fetchall()
    assert [(f[0].isoformat(), f[1], f[2]) for f in fila] == [("2026-10-22T19:08:47", "7", "producto")]


def test_la_0012_no_toca_la_que_ya_tiene_la_forma_de_libraauth(base_temporal, monkeypatch):
    """`libraclub-dev` y `libraclub-demo` antes de unirse: el arranque la creó con `AuditoriaBase`."""
    url = base_temporal("log_vieja")
    _migrar_el_producto(url, monkeypatch)
    with psycopg.connect(_libpq(url), autocommit=True) as con:
        con.execute("INSERT INTO actividad_log (ts, usuario, accion, entidad, entidad_id, descripcion) "
                    "VALUES (now(), 'admin', 'crear', 'sucursal', 'x-1', '')")
    monkeypatch.setenv("DATABASE_URL", url)
    command.downgrade(_alembic(), "0011_qr_del_buffet")
    command.upgrade(_alembic(), "head")
    with psycopg.connect(_libpq(url)) as con:
        assert con.execute("SELECT entidad_id FROM actividad_log").fetchall() == [("x-1",)]
    assert _tipos_de_actividad_log(url) == FORMA_DE_LIBRAAUTH


# ── 2. La config ────────────────────────────────────────────────────────────

DOMINIO = "postgresql+psycopg://u:p@servidor:5432/libraclub"


@pytest.fixture
def entorno_de_config(monkeypatch):
    """Un entorno de config limpio: sólo lo que el test declare."""
    for nombre in ("DATABASE_URL", "LIBRACLUB_DATABASE_URL", "LIBRACLUB_LIBRACORE_DATABASE_URL"):
        monkeypatch.delenv(nombre, raising=False)
    monkeypatch.setenv("LIBRACLUB_DATABASE_URL", DOMINIO)
    return monkeypatch


def test_sin_variable_del_core_todo_usa_la_base_del_dominio(entorno_de_config):
    config = Config.desde_entorno()
    assert config.libracore_database_url == DOMINIO
    assert config.core_en_la_del_dominio


def test_la_misma_base_escrita_de_otra_forma_se_resuelve_a_la_del_dominio(entorno_de_config):
    """El compose escribe el core como `postgresql://` y el dominio como `postgresql+psycopg://`."""
    entorno_de_config.setenv("LIBRACLUB_LIBRACORE_DATABASE_URL", "postgresql://u:p@servidor:5432/libraclub")
    config = Config.desde_entorno()
    assert config.libracore_database_url == DOMINIO  # la del dominio tal cual, un solo valor
    assert config.core_en_la_del_dominio


def test_con_otra_base_para_el_core_se_respetan_las_dos(entorno_de_config):
    """La forma de dos bases, que ya no tiene instancias pero el código sigue soportando."""
    entorno_de_config.setenv("LIBRACLUB_LIBRACORE_DATABASE_URL", "postgresql://u:p@servidor:5432/libraclub_core")
    config = Config.desde_entorno()
    assert config.database_url == DOMINIO
    assert config.libracore_database_url == "postgresql://u:p@servidor:5432/libraclub_core"
    assert not config.core_en_la_del_dominio


def test_el_core_sigue_exigiendo_postgresql(entorno_de_config):
    entorno_de_config.setenv("LIBRACLUB_LIBRACORE_DATABASE_URL", "sqlite:///core.db")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Config.desde_entorno()


def test_una_config_armada_a_mano_sin_core_sigue_sin_facturacion():
    """`None` sólo existe armando la `Config` a mano: es el «instancia sin facturar» de los tests."""
    config = Config(database_url=DOMINIO, entorno="test", debug=False)
    assert config.libracore_database_url is None
    assert not config.core_en_la_del_dominio


@pytest.mark.parametrize(("a", "b", "esperado"), [
    ("postgresql://u@h:5432/x", "postgresql+psycopg://u@h:5432/x", True),
    ("postgresql://u@h:5432/x", "postgresql://u@h:5432/x/", True),
    ("postgresql://u@h:5432/x?sslmode=disable", "postgresql://u@h:5432/x", True),
    ("postgresql://u@h:5432/x", "postgresql://u@h:5432/x_core", False),
    ("postgresql://u@h:5432/x", "postgresql://u@otro:5432/x", False),
])
def test_misma_base(a, b, esperado):
    assert misma_base(a, b) is esperado


def test_el_modulo_de_addons_sin_variable_del_core_usa_la_del_dominio(monkeypatch):
    """`app.database` corre bajo `docker exec`, sin `Config`: la misma regla, resuelta ahí."""
    from libracore.db import core as libracore_core

    configuradas = []
    monkeypatch.setattr(libracore_core, "esta_configurado", lambda: False)
    monkeypatch.setattr(libracore_core, "configure", configuradas.append)
    for nombre in ("DATABASE_URL", "LIBRACLUB_DATABASE_URL", "LIBRACLUB_LIBRACORE_DATABASE_URL"):
        monkeypatch.delenv(nombre, raising=False)

    with pytest.raises(RuntimeError, match="LIBRACLUB_DATABASE_URL"):
        database._asegurar_core_configurado()  # sin ninguna de las dos, falla nombrándolas

    monkeypatch.setenv("LIBRACLUB_DATABASE_URL", DOMINIO)
    database._asegurar_core_configurado()
    assert configuradas == [DOMINIO]

    monkeypatch.setenv("LIBRACLUB_LIBRACORE_DATABASE_URL", "postgresql://u:p@servidor:5432/libraclub_core")
    database._asegurar_core_configurado()
    assert configuradas[-1] == "postgresql://u:p@servidor:5432/libraclub_core"


# ── 3. El respaldo ──────────────────────────────────────────────────────────


def _config(dominio: str, core: str | None) -> Config:
    return Config(database_url=dominio, entorno="test", debug=False, libracore_database_url=core)


def test_con_una_sola_base_el_respaldo_no_declara_el_core_otra_vez():
    # Aunque el core esté escrito de otra forma, es la misma base: un dump alcanza.
    instancia = principal._instancia_a_respaldar(
        _config("postgresql+psycopg://u:p@h:5432/libraclub", "postgresql://u:p@h:5432/libraclub"))
    assert instancia.postgres_extra == []
    assert [nombre for _, nombre in instancia.dumps] == ["libraclub.dump"]


def test_sin_core_el_respaldo_lleva_sólo_el_dominio():
    instancia = principal._instancia_a_respaldar(_config("postgresql+psycopg://u:p@h:5432/libraclub", None))
    assert instancia.postgres_extra == []


def test_con_dos_bases_el_respaldo_lleva_las_dos():
    """Un backup con una sola mitad no se puede restaurar y no falla: pesa poco."""
    instancia = principal._instancia_a_respaldar(
        _config("postgresql+psycopg://u:p@h:5432/libraclub", "postgresql://u:p@h:5432/libraclub_core"))
    assert instancia.postgres_extra == ["postgresql://u:p@h:5432/libraclub_core"]
    assert [nombre for _, nombre in instancia.dumps] == ["libraclub.dump", "libraclub_core.dump"]


def test_control_declarar_la_misma_base_dos_veces_no_se_puede():
    """Lo que `misma_base` evita: `Instancia` rechaza dos bases que caen en el mismo archivo del ZIP."""
    with pytest.raises(ValueError, match="mismo archivo"):
        Instancia(nombre="libraclub", postgres_url="postgresql://u:p@h:5432/libraclub",
                  postgres_extra=["postgresql://u:p@h:5432/libraclub"])


# ── 4. La facturación crea la base del core sólo si es otra ─────────────────


@pytest.fixture
def core_aislado(monkeypatch):
    """`configurar()` deja apuntados `libracore.db.core` y `_hay_base`: globales del proceso. Se restauran."""
    from libracore.db import core as libracore_core

    for nombre in ("_db_path", "_database_url", "_timeout", "_extra_pragmas"):
        monkeypatch.setattr(libracore_core, nombre, getattr(libracore_core, nombre))
    monkeypatch.setattr(facturacion, "_hay_base", facturacion._hay_base)


def _existe(servidor_libpq: str, nombre: str) -> bool:
    with psycopg.connect(f"{servidor_libpq}/postgres", autocommit=True) as con:
        return con.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nombre,)).fetchone() is not None


def test_con_una_sola_base_configurar_no_crea_ninguna_base(base_temporal, core_aislado, monkeypatch):
    url = base_temporal("fact_una")

    def _no_deberia(_url):
        raise AssertionError("no hay base que crear: el core es la del dominio")

    monkeypatch.setattr(facturacion, "_crear_base_si_falta", _no_deberia)

    assert facturacion.configurar(_libpq(url), url_del_dominio=url) is True
    with psycopg.connect(_libpq(url)) as con:
        assert con.execute("SELECT to_regclass('public.turnos_caja')").fetchone()[0] is not None
        assert con.execute("SELECT to_regclass('public.sales')").fetchone()[0] is not None


def test_con_dos_bases_configurar_crea_la_del_core_si_falta(base_temporal, core_aislado):
    dominio = base_temporal("fact_dos_dom")
    core = base_temporal("fact_dos_core", existe=False)
    servidor, _, nombre_core = _libpq(core).rpartition("/")
    assert not _existe(servidor, nombre_core)  # control: de verdad no está

    assert facturacion.configurar(_libpq(core), url_del_dominio=dominio) is True

    assert _existe(servidor, nombre_core)
    with psycopg.connect(_libpq(core)) as con:
        assert con.execute("SELECT to_regclass('public.turnos_caja')").fetchone()[0] is not None


# ── 5. La cadena de migraciones y el alta ───────────────────────────────────


@pytest.mark.parametrize("script", ["nuevo_cliente", "panel_admin"])
def test_la_cadena_corre_el_motor_el_buffet_la_auth_y_la_propia_en_ese_orden(script):
    """El orden se midió sobre una base vacía (ver el comentario de `migraciones` en los scripts).

    Se aserta lo que el deploy ejecuta, comando por comando, y no la tupla contra un literal escrito acá.
    """
    from libracore.provisioning import get_config

    importlib.reload(importlib.import_module(f"scripts.{script}"))
    comandos = [" ".join(c) for c in get_config().migraciones]

    assert comandos == [
        "libracore-migrar upgrade --prefijo libraclub",
        "libracommerce-migrar upgrade --prefijo libraclub",
        "libraauth-migrar upgrade --prefijo libraclub --base dominio",
        "alembic upgrade head",
    ]


@pytest.mark.parametrize("script", ["nuevo_cliente", "panel_admin"])
def test_un_alta_nueva_nace_con_una_sola_base(script):
    """Las dos variables del producto llevan la misma base: el compose del cliente sale con una."""
    from libracore.provisioning import get_config

    importlib.reload(importlib.import_module(f"scripts.{script}"))
    configuracion = get_config()

    assert configuracion.base_core_separada is False
    urls = dict(configuracion.db_urls)
    assert urls["LIBRACLUB_DATABASE_URL"] == urls["LIBRACLUB_LIBRACORE_DATABASE_URL"] == "libraclub"
    assert configuracion.bases_postgres == ("libraclub",)


def test_el_compose_de_dev_no_declara_variables_del_core():
    """Una sola base: el compose de dev no lleva la base del core ni el destino del buffet.

    `LIBRACLUB_LIBRACORE_DATABASE_URL` y `LIBRACOMMERCE_MIGRAR_URL` apuntaban a `libraclub_core`
    mientras la instancia tenía dos bases (la segunda hacía falta para que `libracommerce-migrar`
    no creara 25 tablas vacías en el dominio). Con una sola, `Config.desde_entorno()` y las
    cadenas de migración caen a `DATABASE_URL`; una de las dos que volviera a aparecer apuntando
    a otra base reabriría la instancia de dos bases sin que nadie lo decida.
    """
    import re

    texto = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
    declaradas = re.findall(r"^\s*-\s*(LIBRACLUB_LIBRACORE_DATABASE_URL|LIBRACOMMERCE_MIGRAR_URL)=", texto, re.M)
    assert declaradas == [], f"el compose de dev declara {declaradas}: la instancia es de una sola base"
