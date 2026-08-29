"""Fixtures de la suite.

Corre **contra PostgreSQL real**. No hay fallback a SQLite y no lo va a haber:
la garantía central del producto es un constraint de exclusión GiST, que SQLite
no tiene. Una suite verde sobre SQLite estaría midiendo otro producto.
"""

from __future__ import annotations

import os
from datetime import date, time
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.enums import AlcanceDia, Deporte
from app.models.maestros import Cancha, Cliente, Sucursal
from app.models.tarifas import Tarifa

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Todas las tablas del dominio, en orden de borrado. `TRUNCATE ... CASCADE`
#: entre tests en vez de recrear el schema: recrear cuesta segundos por test y
#: además volvería a correr la migración, que es lo que se quiere probar una vez
#: y no cien.
#: `avisos` va explícita aunque el `CASCADE` la alcanzaría por su FK contra
#: `reservas`: una tabla que sólo se limpia de rebote deja de limpiarse el día
#: que alguien le saca la FK, y el síntoma es un test que ve avisos de otro.
TABLAS = "avisos, reservas, series, tarifas, feriados, canchas, clientes, sucursales"


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
def _sin_pools_colgados():
    """Cierra el pool que dejó `crear_app()`, si el test armó una app.

    🔴 Cada `crear_app()` construye un engine nuevo y lo deja en el módulo `db`;
    el anterior queda con su pool abierto hasta que el recolector lo junte. Con
    suficientes tests que arman una app, eso cruza el límite de conexiones de
    PostgreSQL y el fallo sale como `too many clients already` **en un test
    cualquiera** — el que tuvo la mala suerte de ser el que cruzó el límite, que
    no tiene nada que ver con el problema. Y como depende del recolector, el
    número exacto cambia entre corridas: un rojo que no se reproduce.
    """
    yield
    from app import db as _db

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
