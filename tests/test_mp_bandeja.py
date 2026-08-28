"""La bandeja de MercadoPago y el reparto por referencia.

🔴 **El modo de fallar de esto es mudo.** Si el prefijo con el que la bandeja
filtra dejara de coincidir con el que arma `nueva_referencia`, no se rompería
nada visible: los pagos de reservas —que el webhook del producto ya resolvió—
empezarían a aparecer en la bandeja como si nadie los hubiera conciliado, y
alguien los facturaría una segunda vez. Por eso el primer test ata las dos
puntas en vez de repetir la constante.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app
from app.routers.mp_bandeja import REFERENCIAS_PROPIAS
from app.servicios.pagos import PREFIJO_DE_REFERENCIA, nueva_referencia

USUARIO, CLAVE = "admin", "clave-de-prueba"


def _url_core() -> str:
    url = os.environ["DATABASE_URL"]
    base, _, nombre = url.rpartition("/")
    return f"{base}/{nombre}_core".replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture
def base_de_libracore():
    url = _url_core()
    servidor, _, nombre = url.rpartition("/")
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{nombre}"')
    yield url
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    config = Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
        libracore_database_url=base_de_libracore,
    )
    cliente = TestClient(crear_app(config), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


def test_el_filtro_de_la_bandeja_matchea_las_referencias_de_VERDAD():
    """🔴 Las dos puntas atadas, no la constante repetida.

    El test no compara `REFERENCIAS_PROPIAS` contra el string `"lc-"` —eso sería
    comparar una copia con otra— sino contra una referencia **realmente
    generada**. Si `nueva_referencia` cambiara de formato, esto se pone rojo; si
    sólo se comparara la constante, seguiría verde con el filtro ya inservible.
    """
    referencia = nueva_referencia(123)

    assert any(referencia.startswith(p) for p in REFERENCIAS_PROPIAS), (
        f"la bandeja filtra por {REFERENCIAS_PROPIAS} y las referencias de este "
        f"producto se ven como {referencia!r}: los pagos de reservas entrarían a "
        "la bandeja como si nadie los hubiera resuelto"
    )
    # Y el control: una referencia ajena NO cae en el filtro, o la bandeja
    # quedaría vacía siempre.
    assert not any("venta-77".startswith(p) for p in REFERENCIAS_PROPIAS)


def test_el_prefijo_no_esta_escrito_dos_veces():
    """La constante es la única fuente. Si alguien vuelve a escribir `lc-` a
    mano en la generación, esto no lo ve — pero el test de arriba sí, porque
    compara contra lo generado."""
    assert PREFIJO_DE_REFERENCIA == "lc-"
    assert nueva_referencia(9).startswith(PREFIJO_DE_REFERENCIA)


def test_la_bandeja_esta_montada_y_es_de_admin(api, engine):
    """El mostrador cobra; conciliar lo que entró a la cuenta es del dueño."""
    r = api.get("/api/mp-bandeja")
    assert r.status_code == 200, r.text

    api.post("/api/usuarios", json={
        "username": "mostrador-mp", "name": "Mostrador",
        "password": "clave-mostrador", "role": "staff",
    })
    config = Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
        libracore_database_url=_url_core(),
    )
    staff = TestClient(crear_app(config), base_url="https://testserver")
    assert staff.post(
        "/auth/login", json={"username": "mostrador-mp", "password": "clave-mostrador"}
    ).status_code == 200
    assert staff.get("/api/mp-bandeja").status_code == 403


def test_sin_base_de_libracore_la_bandeja_lo_DICE(engine, sesion, monkeypatch):
    """503 nombrando la variable, igual que el resto de la facturación: la
    bandeja vive en la base de LibraCore."""
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    config = Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
        libracore_database_url=None,
    )
    cliente = TestClient(crear_app(config), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200

    r = cliente.get("/api/mp-bandeja")
    assert r.status_code == 503, r.text
    assert "LIBRACLUB_LIBRACORE_DATABASE_URL" in r.text
    AuthBase.metadata.drop_all(engine)


# ── El webhook y los cobros que no son de un turno ────────────────────────


def _notificacion(payment_id: str = "999") -> dict:
    return {"type": "payment", "data": {"id": payment_id}}


def test_un_cobro_ajeno_YA_NO_se_pierde(api, monkeypatch):
    """🔑 Hasta el 2026-08-27 esto contestaba 200 y no dejaba rastro.

    Una transferencia al complejo, o cualquier cobro que no salió de un turno,
    llegaba al webhook, no matcheaba ninguna referencia conocida y se
    **perdía**. Ahora se manda a conciliar.

    Se intercepta `ingerir` —la misma función que usan el botón y el cron— y se
    verifica **con qué la llamaron**: es lo único que distingue "mandó a
    conciliar" de "contestó 200 y no hizo nada", que es justo el defecto que
    esto viene a arreglar.
    """
    from app.routers import portal as router_portal

    llamadas = []

    async def ingerir_falso(cfg, *, dias, referencias_a_omitir):
        llamadas.append({"dias": dias, "omitir": referencias_a_omitir})
        return [{"id": 1}]

    monkeypatch.setattr(router_portal.mp_sync, "ingerir", ingerir_falso)
    monkeypatch.setattr(
        router_portal.servicio_pagos, "firma_valida", lambda **kw: True,
    )

    async def pago_ajeno(payment_id, token):
        return {"status": "approved", "external_reference": "transferencia-de-alguien"}

    monkeypatch.setattr(router_portal.mp_api, "obtener_pago", pago_ajeno)
    monkeypatch.setattr(
        router_portal.config_manager, "load",
        lambda: {"mp_webhook_secret": "s", "mp_access_token": "t"},
    )

    r = api.post("/api/portal/webhook", json=_notificacion())
    assert r.status_code == 200, r.text
    assert "bandeja" in r.json()["motivo"], r.json()

    assert len(llamadas) == 1, "no se mandó a conciliar"
    # Y con el reparto puesto: sin esto, la conciliación se traería también los
    # pagos de reservas que el webhook ya resolvió.
    assert llamadas[0]["omitir"] == REFERENCIAS_PROPIAS


def test_un_cobro_de_reserva_NO_va_a_la_bandeja(api, monkeypatch):
    """El control. Esos los resuelve el webhook mismo: mandarlos a conciliar
    haría que alguien los facture una segunda vez."""
    from app.routers import portal as router_portal

    llamadas = []

    async def ingerir_falso(cfg, *, dias, referencias_a_omitir):
        llamadas.append(1)
        return []

    monkeypatch.setattr(router_portal.mp_sync, "ingerir", ingerir_falso)
    monkeypatch.setattr(
        router_portal.servicio_pagos, "firma_valida", lambda **kw: True,
    )

    async def pago_de_reserva(payment_id, token):
        # Con NUESTRO prefijo, pero sin pago registrado: otra instancia sobre la
        # misma cuenta, o una prueba.
        return {"status": "approved", "external_reference": f"{PREFIJO_DE_REFERENCIA}77-abc"}

    monkeypatch.setattr(router_portal.mp_api, "obtener_pago", pago_de_reserva)
    monkeypatch.setattr(
        router_portal.config_manager, "load",
        lambda: {"mp_webhook_secret": "s", "mp_access_token": "t"},
    )

    r = api.post("/api/portal/webhook", json=_notificacion())
    assert r.status_code == 200, r.text
    assert r.json()["motivo"] == "referencia desconocida"
    assert llamadas == [], "un cobro con nuestro prefijo no se manda a conciliar"


def test_si_la_conciliacion_falla_igual_contesta_200(api, monkeypatch):
    """🔴 El cobro ya está hecho del lado de MercadoPago.

    Devolver un error haría que MP reintente durante días por algo que el cron
    nocturno va a traer solo — una tormenta de reintentos por un caso que se
    resuelve en horas.
    """
    from app.routers import portal as router_portal

    async def ingerir_que_explota(cfg, *, dias, referencias_a_omitir):
        raise RuntimeError("MercadoPago no contesta")

    monkeypatch.setattr(router_portal.mp_sync, "ingerir", ingerir_que_explota)
    monkeypatch.setattr(
        router_portal.servicio_pagos, "firma_valida", lambda **kw: True,
    )

    async def pago_ajeno(payment_id, token):
        return {"status": "approved", "external_reference": "otra-cosa"}

    monkeypatch.setattr(router_portal.mp_api, "obtener_pago", pago_ajeno)
    monkeypatch.setattr(
        router_portal.config_manager, "load",
        lambda: {"mp_webhook_secret": "s", "mp_access_token": "t"},
    )

    r = api.post("/api/portal/webhook", json=_notificacion())
    assert r.status_code == 200, r.text
    assert "cron" in r.json()["motivo"]
