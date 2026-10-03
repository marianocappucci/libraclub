"""Fixtures de la suite.

Corre **contra PostgreSQL real**. No hay fallback a SQLite y no lo va a haber:
la garantía central del producto es un constraint de exclusión GiST, que SQLite
no tiene. Una suite verde sobre SQLite estaría midiendo otro producto.
"""

from __future__ import annotations

import atexit
import os
from datetime import date, time
from decimal import Decimal

import libraauth.session_auth as _session_auth
import psycopg
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from libracore.testing.pg_por_worker import BasePorWorker, base_por_worker
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.enums import AlcanceDia, Deporte
from app.models.maestros import Cancha, Cliente, Sucursal
from app.models.tarifas import Tarifa

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Una base por worker de xdist ──────────────────────────────────────────────
#
# La suite corre en varios procesos (`pytest -n 4`, reglas/ci.md del wiki) y todos
# hablaban con la MISMA base: el `DROP SCHEMA` del fixture `engine`, el `TRUNCATE`
# de `sesion` y el `drop_all` de auth de cada `api` se pisaban entre workers. El
# mecanismo (una base `<base>_<worker>`, que se borra al salir) es el de
# `libracore.testing.pg_por_worker`; acá se pisa `DATABASE_URL` con la del worker
# y de ahí en adelante TODO lo que la lee —`_url()`, `Config.desde_entorno()`, los
# `os.environ["DATABASE_URL"]` de cada test— habla con SU base.
#
# 🔴 Y la base de LibraCore sale de esa misma variable: los tests la derivan como
# `<base del dominio>_core` (`_url_core()`), así que **también queda una por
# worker** sin tocarles una línea. Mira `base_de_libracore` más abajo.
#
# `base_por_worker` es idempotente a propósito: el proceso que lanza a los
# workers importa este conftest también, y un test que hace
# `from tests.test_x import ...` carga el módulo bajo dos nombres.
_PG = base_por_worker("libraclub", os.environ.get("DATABASE_URL", ""))
if _PG:
    os.environ["DATABASE_URL"] = _PG.url

#: La base de LibraCore de ESTE worker y su plantilla `armada`. Se la maneja con
#: `BasePorWorker` a mano y no con `base_por_worker("...")`: ese deriva el nombre
#: como `<original>_<worker>` (`libraclub_test_core_gw0`) y los tests —que
#: componen `<base del dominio>_core` por su cuenta— esperan
#: `libraclub_test_gw0_core`. Ver `base_de_libracore`.
_CORE = BasePorWorker(_PG.url_original, f"{_PG.nombre}_core") if _PG else None
if _CORE:
    _marca = f"_LIBRACLUB_CORE_LISTA_{os.environ.get('PYTEST_XDIST_WORKER', 'main')}"
    if _marca not in os.environ:
        _CORE.soltar_todo()  # restos de una corrida interrumpida, plantilla incluida
        atexit.register(_CORE.soltar_todo)
        os.environ[_marca] = "1"

#: Todas las tablas del dominio, en orden de borrado. `TRUNCATE ... CASCADE`
#: entre tests en vez de recrear el schema: recrear cuesta segundos por test y
#: además volvería a correr la migración, que es lo que se quiere probar una vez
#: y no cien.
#: `avisos` va explícita aunque el `CASCADE` la alcanzaría por su FK contra
#: `reservas`: una tabla que sólo se limpia de rebote deja de limpiarse el día
#: que alguien le saca la FK, y el síntoma es un test que ve avisos de otro.
#:
#: 🔴 **`pagos_de_reserva` va explícita porque el `CASCADE` ya NO la alcanza
#: entera.** Desde la revisión `0011` un pago de **venta de buffet** tiene
#: `reserva_id` en `NULL`: no cuelga de ninguna reserva, así que truncar
#: `reservas` en cascada no se lo lleva. Sin esta línea el pago aprobado de un
#: test sobrevive al siguiente, y el que ahí se rompe es el guard de "esta venta
#: ya está cobrada" — con un rojo que habla de la venta de otro test.
TABLAS = (
    "pagos_de_reserva, avisos, reservas, series, tarifas, feriados, "
    "canchas, clientes, sucursales"
)


#: Secreto de firma de sesión para la suite. Fijo y evidente: no es una clave,
#: es una constante de test.
SECRETO_DE_PRUEBA = "libraclub-suite-no-es-un-secreto-real"


@pytest.fixture(autouse=True)
def _config_de_libracore_aislada(tmp_path, monkeypatch):
    """`config_manager` de LibraCore escribe un JSON **en el cwd**, y persiste.

    🔴 Lo encontró el test del buffet, y es un falso verde de manual:
    `_DATA_DIR = os.environ.get("DATA_DIR", os.getcwd())` se resuelve **al
    importar**, así que `CONFIG_PATH` termina siendo `<raíz del repo>/config.json`.
    Un test que hace `save({"empresa_iva_condition": "Responsable Inscripto"})`
    deja ese archivo escrito **para siempre**: la corrida siguiente arranca con
    un emisor distinto, y los tests que dependen del tipo de comprobante pasan a
    probar otra cosa. Dentro de una corrida no se nota —el orden los salva— y
    aparece recién en la segunda.

    Con esto cada test arranca con la config en su default (Monotributista).
    """
    from libracore import config_manager

    monkeypatch.setattr(config_manager, "CONFIG_PATH", str(tmp_path / "config.json"))


@pytest.fixture(autouse=True)
def _secreto_de_sesion(monkeypatch):
    """`SessionAuth` no se construye sin `SECRET_KEY` (salvo `ENV=development`).

    Autouse porque si no, la suite pasa o falla según lo que tenga exportado el
    shell de quien la corre: verde local con `ENV=development` y rojo en el CI,
    con un error que no habla de la causa. Un test tiene que traer su entorno,
    no heredarlo.
    """
    monkeypatch.setenv("SECRET_KEY", SECRETO_DE_PRUEBA)


@pytest.fixture(autouse=True)
def _sin_almacen_de_secretos_colgado():
    """El almacen de secretos de `config_manager` no se filtra entre tests.

    `crear_app()` llama a `config_manager.usar_almacen_de_secretos(...)`
    (libracore v1.108.0), que es un global del proceso. `test_api.py` arma la
    app y en su teardown hace `drop_all` del schema de auth —que incluye
    `secretos_instancia`—, asi que el almacen queda apuntando a una tabla que ya
    no existe. Los tests de servicios que llaman a `config_manager.load()` sin
    armar la app (avisos lee de ahi el nombre del complejo) morian despues con
    `UndefinedTable`: 16 de `test_avisos.py`, que solo pasan corriendo solos.

    Antes y despues de cada test. Sin almacen, `config_manager` lee el JSON.
    """
    from libracore import config_manager

    config_manager.usar_almacen_de_secretos(None)
    yield
    config_manager.usar_almacen_de_secretos(None)


@pytest.fixture(autouse=True)
def _sin_pools_colgados(monkeypatch):
    """Cierra el pool de TODOS los engines que armó el test, no sólo del último.

    🔴 Cada `crear_app()` construye un engine nuevo y lo deja en el módulo `db`;
    el anterior queda con su pool abierto hasta que el recolector lo junte. Con
    suficientes tests que arman una app, eso cruza el límite de conexiones de
    PostgreSQL y el fallo sale como `too many clients already` **en un test
    cualquiera** — el que tuvo la mala suerte de ser el que cruzó el límite, que
    no tiene nada que ver con el problema. Y como depende del recolector, el
    número exacto cambia entre corridas: un rojo que no se reproduce.

    🔴 Con xdist el límite (100, el de la imagen) es de TODOS los workers juntos.
    Antes alcanzaba con cerrar el engine que quedó en `db._engine`, y los demás se
    iban acumulando: `test_falta_uno.py` arma **tres apps por test** (`_jugador()`
    cada una) y dejaba ~3 conexiones colgadas por test, 55 al terminar el archivo
    en una sola corrida; con 4 workers la suma pasa de 100 y mueren ~120 tests con
    `too many clients already`. Por eso se anota cada engine que crea `db` y se
    cierran todos al terminar el test.
    """
    from app import db as _db

    creados = []
    crear = _db.create_engine

    def _registrando(*args, **kwargs):
        motor = crear(*args, **kwargs)
        creados.append(motor)
        return motor

    monkeypatch.setattr(_db, "create_engine", _registrando)
    yield
    for motor in creados:
        motor.dispose()
    if _db._engine is not None:
        _db._engine.dispose()


def _url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip(
            "Falta DATABASE_URL. La suite corre contra PostgreSQL real: "
            "levantá el compose o exportá la URL del sidecar de tests."
        )
    return url


@pytest.fixture(scope="session")
def engine():
    """El engine, con el schema ya migrado.

    Se corre la migración de verdad —y no `Base.metadata.create_all()`— porque
    `create_all` **no crea la extensión `btree_gist` ni el constraint de
    exclusión escrito a mano**. Una suite montada sobre `create_all` daría verde
    sin la garantía que este producto vende.
    """
    motor = create_engine(_url(), future=True)

    # 🔴 Se **reconstruye** el schema, no se migra sobre lo que haya quedado.
    # `alembic upgrade head` sobre una base que ya está en head no hace nada, así
    # que una base a la que le falta algo —porque una corrida anterior se
    # interrumpió a mitad de un DDL— sigue viéndose migrada y la suite corre
    # sobre ella. Pasó el 2026-08-20: una corrida abortada dejó la base **sin el
    # constraint de exclusión** y el test de concurrencia dio "las dos entraron",
    # que es exactamente el falso negativo que este producto no se puede
    # permitir.
    with motor.begin() as conexion:
        conexion.execute(text("SET lock_timeout = '15s'"))
        conexion.execute(text("DROP SCHEMA public CASCADE"))
        conexion.execute(text("CREATE SCHEMA public"))

    cfg = AlembicConfig(os.path.join(RAIZ, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(RAIZ, "migrations"))
    command.upgrade(cfg, "head")
    yield motor
    motor.dispose()


@pytest.fixture
def sesion(engine) -> Session:
    """Una sesión limpia. Las tablas se vacían **antes**, no después.

    Antes y no después para que un test que falla deje sus datos en la base y se
    puedan mirar. Limpiar al final borra justamente la evidencia del único test
    que importaba.
    """
    with engine.begin() as conexion:
        # `lock_timeout` para que un test que dejó una sesión abierta haga fallar
        # a este con un error de lock en vez de **colgar la suite**: `TRUNCATE`
        # pide ACCESS EXCLUSIVE y por defecto espera para siempre. Un CI colgado
        # no dice qué pasó; uno rojo sí.
        conexion.execute(text("SET lock_timeout = '15s'"))
        conexion.execute(text(f"TRUNCATE {TABLAS} RESTART IDENTITY CASCADE"))
    fabrica = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with fabrica() as sesion:
        yield sesion


def _construir_core_armada(url: str) -> None:
    """Deja la base de LibraCore como la deja `crear_app()` sobre una base vacía.

    Es lo que `facturacion.configurar()` hace en cada arranque: el schema de
    LibraCore, el del buffet (LibraCommerce), las tablas del cierre diario y la
    caja por defecto. Medido: ~0,6 s por test, el grueso de lo que cuesta armar
    una app con facturación. Se corre una vez por worker; los tests la reciben
    copiada con `CREATE DATABASE ... TEMPLATE`, y el `configurar()` de su propia
    `crear_app()` es idempotente sobre ella (`CREATE TABLE IF NOT EXISTS`, y sólo
    crea la caja por defecto si no hay).

    🔴 `configurar()` deja apuntados a la plantilla `libracore.db.core` y
    `_hay_base` —globales del proceso—: se restauran, o el primer test que lea
    LibraCore sin armar su app hablaría con una base que se borra enseguida.
    """
    from libracore.db import core as libracore_core

    from app.servicios import facturacion

    mp = pytest.MonkeyPatch()
    try:
        for nombre in ("_db_path", "_database_url", "_timeout", "_extra_pragmas"):
            mp.setattr(libracore_core, nombre, getattr(libracore_core, nombre))
        mp.setattr(facturacion, "_hay_base", facturacion._hay_base)
        facturacion.configurar(url.replace("postgresql+psycopg://", "postgresql://", 1))
    finally:
        mp.undo()


@pytest.fixture
def base_de_libracore():
    """La base de LibraCore de este worker, ya armada, para un test que factura.

    Parte de una copia de la plantilla `armada` (`_construir_core_armada`) en vez
    de una base vacía que `crear_app()` tenía que llenar. La URL es la que
    derivan los tests de la del dominio (`<base>_core`), que con xdist es la del
    worker. Se borra al terminar, como siempre: un test que arma su app contra
    `<base>_core` sin pedir esta fixture tiene que encontrar la base AUSENTE, no
    los datos del test anterior.
    """
    if _CORE is None:
        pytest.skip("Falta DATABASE_URL: la suite corre contra PostgreSQL real.")
    url = os.environ["DATABASE_URL"]
    base, _, nombre = url.rpartition("/")
    url_core = f"{base}/{nombre}_core".replace("postgresql+psycopg://", "postgresql://")
    assert nombre + "_core" == _CORE.nombre, (nombre, _CORE.nombre)
    _CORE.restaurar("armada", _construir_core_armada)
    yield url_core
    servidor, _, nombre_core = url_core.rpartition("/")
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre_core}" WITH (FORCE)')


@pytest.fixture
def sucursal(sesion) -> Sucursal:
    item = Sucursal(nombre="Complejo Centro", punto_venta_arca=1)
    sesion.add(item)
    sesion.commit()
    return item


@pytest.fixture
def cancha(sesion, sucursal) -> Cancha:
    item = Cancha(
        sucursal_id=sucursal.id,
        nombre="Cancha 1",
        deporte=Deporte.PADEL,
        duracion_turno_min=90,
    )
    sesion.add(item)
    sesion.commit()
    return item


@pytest.fixture
def cliente(sesion) -> Cliente:
    item = Cliente(nombre="Juan Pérez", telefono="2255-123456")
    sesion.add(item)
    sesion.commit()
    return item


@pytest.fixture
def tarifa_base(sesion, sucursal) -> Tarifa:
    """Una tarifa que cubre todo el día, para que crear una reserva no dependa
    de haber cargado la franja justa."""
    item = Tarifa(
        sucursal_id=sucursal.id,
        nombre="General",
        alcance_dia=AlcanceDia.TODOS,
        hora_desde=time(0, 0),
        hora_hasta=time(23, 59),
        precio=Decimal("10000.00"),
        sena_porcentaje=50,
    )
    sesion.add(item)
    sesion.commit()
    return item


@pytest.fixture
def un_martes() -> date:
    """Una fecha fija y conocida, martes.

    Fija a propósito: un test que use `hoy()` pasa o falla según el día de la
    semana en que corra el CI, y el que lo vea fallar un martes no va a poder
    reproducirlo.
    """
    return date(2026, 9, 1)  # martes


# ── Términos y Condiciones: aceptados para el resto de la suite ─────────────
#
# Desde libraauth v0.31.0 el motor corta con 403 **cualquier** llamada gateada
# por rol mientras la instancia no haya aceptado la versión vigente del
# contrato. Sin esta excepción, la suite entera se pone roja de golpe: cada
# test que loguea y pide datos recibe el 403 del gate en vez de lo que iba a
# medir, y el rojo no dice nada sobre el dominio.
#
# 🔴 **Esto NO apaga el gate donde importa.** Lo que la suite no puede es medir
# el dominio a través de un corte que no está probando; el corte tiene su propio
# archivo, `test_terminos_gate.py`, que se marca con `sin_aceptar_terminos` y
# queda afuera de esta excepción. Si alguien borrara el cableado de
# `app.state.terminos`, esa marca es lo único que se pondría rojo — el resto de
# la suite seguiría verde, porque no lo mira.


@pytest.fixture(autouse=True)
def _terminos_ya_aceptados(request):
    if request.node.get_closest_marker("sin_aceptar_terminos"):
        yield
        return

    from libraauth.terminos import TerminosRepository

    # 🔴 **`MonkeyPatch()` propio y no el fixture `monkeypatch`.** El fixture es
    # uno solo por test y lo comparten todas las fixtures que lo pidan, asi que
    # un `monkeypatch.undo()` en el cuerpo de un test —que existe, y es
    # legitimo— deshace TAMBIEN este parche y le prende el gate a la mitad del
    # test. El sintoma no se parece a la causa: la llamada siguiente devuelve
    # 403 y el test explota con un `KeyError` sobre la clave que esperaba en el
    # JSON. Lo encontro `test_despues_de_un_fallo_el_boton_puede_emitirlo` de
    # VentaLibra, que era el unico de las seis suites que llama `undo()`.
    mp = pytest.MonkeyPatch()
    mp.setattr(TerminosRepository, "esta_aceptada", lambda self: True)
    yield
    mp.undo()


# ── Captcha ALTCHA: aprobado para el resto de la suite ──────────────────────
#
# Desde libraauth v0.40.0 el router de `/auth` se monta con `captcha=True`: el
# login y forgot-password exigen la solución de un desafío. La suite postea a
# `/auth/login` en decenas de lugares —cada fixture `api`, `api_staff`, los
# tests de usuarios, de la demo, del reset—, y resolver un desafío en cada uno
# no prueba nada de este producto.
#
# 🔴 **El captcha lo prueba libraauth; acá sólo se cablea.** Lo que es de este
# producto —que `GET /auth/captcha` exista y que un login sin captcha rebote— lo
# fija `test_captcha_login.py`, que vuelve a poner la función real con
# `CAPTCHA_DE_ORIGINAL`. Si alguien sacara `captcha=True` del router, ese
# archivo es lo que se pondría rojo: el resto de la suite seguiría verde.

#: La función real de libraauth, capturada al importar el conftest —antes de
#: cualquier parche—, para que un test pueda volver a ponerla.
CAPTCHA_DE_ORIGINAL = _session_auth._captcha_de


class _CaptchaQueAprueba:
    """Doble del `Captcha` de libraauth: `verificar` aprueba cualquier payload.

    `emitir` delega en un `Captcha` real y barato, así `GET /auth/captcha` sigue
    devolviendo un desafío con la forma de siempre aunque la suite no lo use.
    """

    def __init__(self) -> None:
        from libraauth.captcha import Captcha

        self._real = Captcha("clave-de-prueba", costo=1, contador_min=1, contador_rango=5)

    def emitir(self) -> dict:
        return self._real.emitir()

    def verificar(self, payload: str) -> bool:
        return True


_CAPTCHA_DE_PRUEBA = _CaptchaQueAprueba()


@pytest.fixture(autouse=True)
def _captcha_aprobado(monkeypatch):
    """Todo login y forgot-password de la suite pasa el captcha.

    Se parchea la función de módulo `libraauth.session_auth._captcha_de` y no
    `app.state.captcha`: el router la resuelve por nombre en cada request, y la
    app se arma con `crear_app()` en decenas de lugares distintos — un parche
    sobre una app no alcanzaría a las otras.
    """
    monkeypatch.setattr("libraauth.session_auth._captcha_de", lambda request: _CAPTCHA_DE_PRUEBA)


@pytest.fixture
def abrir_caja():
    """Abre el turno **sobre una caja**, creándola si esa sede no tiene ninguna.

    🔑 Desde el 2026-08-28 el turno se abre sobre un mostrador: el arqueo del
    cierre es el de ESE cajón. El helper existe para que los tests que sólo
    querían "un turno abierto" no tengan que repetir el alta de la caja — pero
    la crea **por la API**, no por el servicio, así el camino que ejercitan es
    el real.

    Devuelve la respuesta del POST, para que los tests que miran el código de
    estado —el 409 de la segunda apertura— sigan pudiendo.
    """
    def _abrir(api, sucursal, monto_inicial="0", notas=""):
        sid = getattr(sucursal, "id", sucursal)
        cajas = api.get(f"/api/cajas?sucursal_id={sid}").json()
        if not cajas:
            alta = api.post("/api/cajas", json={
                "nombre": "Mostrador", "sucursal_id": sid,
            })
            assert alta.status_code == 201, alta.text
            cajas = [alta.json()]
        return api.post("/api/caja/turnos", json={
            "monto_inicial": monto_inicial, "notas": notas, "caja_id": cajas[0]["id"],
        })

    return _abrir
