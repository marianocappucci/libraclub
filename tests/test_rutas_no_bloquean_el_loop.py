"""Las rutas que tocan la base no frenan el loop de uvicorn.

🔴 LibraClub corre uvicorn con **un solo proceso**. Una ruta `async def` que
llama sincrónico a la base —la `Session` de SQLAlchemy, LibraCore, `openssl` por
subproceso para ARCA— frena el loop entero mientras dura: ningún otro request
avanza, `/health` incluido. En un test común no se ve, porque la ruta contesta
bien: lo que hace mal es retener a los demás. Acá se mide eso y nada más.

Cómo: una llamada de cada ruta se reemplaza por una que duerme con
`time.sleep` —bloquea el hilo donde corre, como la consulta real— y, mientras
duerme, se pide `/health` por el **mismo loop**. Si la ruta corre fuera del
loop, `/health` termina antes de que la llamada lenta se despierte; si lo
bloquea, `/health` no puede ni empezar hasta entonces. Se compara contra el
instante en que la llamada lenta **se despertó**, no contra un umbral de
tiempo, así que el resultado no depende de lo rápida que sea la máquina.

🔑 Lo lento va **adentro** de la corrutina que la ruta llama —`crear_orden_qr`,
el numerador de ARCA, `obtener_pago`, `mp_sync.ingerir`, el ingreso a la caja de
`_completar`—: son corrutinas que mezclan red con la base, y pasar la ruta a
`def` sin sacarlas del loop de uvicorn dejaría el test en rojo igual.

`/health` de este producto hace un `SELECT 1` desde una ruta `def`: corre en el
threadpool, así que sólo se demora si el loop está tomado.

Es la misma medición que `tests/test_rutas_no_bloquean_el_loop.py` de
Contalibra, Restolibra y LibraCore. Cada test se probó contra las rutas como
estaban en `origin/develop`: se ponen rojos.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import threading
import time

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libracore import arca_facturacion, mp_api, mp_sync

from app.config import Config
from app.main import crear_app
from app.servicios import caja as servicio_caja

#: Lo que duerme la llamada reemplazada. Alcanza con que sea mucho más que lo
#: que tarda un `/health` sin carga.
LENTO = 1.0

USUARIO, CLAVE = "admin", "clave-de-prueba"
SECRETO_WEBHOOK = "no-es-un-secreto-real"


class _Lento:
    """Una llamada sincrónica que tarda.

    `time.sleep` y no `asyncio.sleep` es el punto entero: una consulta a la
    base o `openssl` por subproceso no le ceden el control a nadie.
    """

    def __init__(self):
        self.entro = threading.Event()
        self.desperto_en: float | None = None

    def dormir(self):
        self.entro.set()
        time.sleep(LENTO)
        if self.desperto_en is None:
            self.desperto_en = time.monotonic()


def _mientras_duerme(api: TestClient, lento: _Lento, pedir):
    """Corre `pedir(cliente)` con la sesión de `api` y, con la llamada lenta ya
    adentro, un `/health` anónimo por el MISMO loop.

    Devuelve la respuesta del pedido, la de `/health` y el instante en que
    `/health` terminó.
    """

    async def _correr():
        transporte = httpx.ASGITransport(app=api.app)
        async with (
            httpx.AsyncClient(transport=transporte, base_url="https://testserver",
                              cookies=api.cookies) as quien_pide,
            httpx.AsyncClient(transport=transporte, base_url="https://testserver") as anonimo,
        ):
            tarea = asyncio.create_task(pedir(quien_pide))
            # La espera va a un hilo para no ocupar el loop con la espera misma.
            assert await asyncio.to_thread(lento.entro.wait, 10), (
                "la llamada lenta nunca empezó: el parche no intercepta la ruta")
            health = await anonimo.get("/health")
            health_termino = time.monotonic()
            respuesta = await asyncio.wait_for(tarea, 30)
        return respuesta, health, health_termino

    return asyncio.run(_correr())


def _no_bloqueo(lento: _Lento, health, health_termino: float):
    assert health.status_code == 200, health.text
    # Sin esto el test pasaría si el parche no interceptara nada: sin llamada
    # lenta, no hay nada que bloquee.
    assert lento.desperto_en is not None, "la parte lenta no llegó a correr"
    assert health_termino < lento.desperto_en, (
        f"/health terminó {health_termino - lento.desperto_en:.2f}s DESPUÉS de "
        "que se despertara la llamada lenta: la ruta bloqueó el loop mientras dormía"
    )


def _corrutina_lenta(monkeypatch, lento: _Lento, modulo, nombre: str, devuelve=None):
    """Reemplaza `modulo.nombre` por una corrutina que duerme con `time.sleep`
    —sin ceder el loop, como la base entre medio de una llamada a la red— y
    devuelve `devuelve`."""

    async def lenta(*args, **kwargs):
        lento.dormir()
        return devuelve

    monkeypatch.setattr(modulo, nombre, lenta)


# ── Arnés: la app real, con las dos bases ────────────────────────────────


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


def _config(url_core: str | None) -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos", libracore_database_url=url_core,
    )


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(crear_app(_config(base_de_libracore)), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def mp(monkeypatch):
    """MercadoPago de mentira, y rápido. Cada test pone lenta sólo la llamada
    que mide. `pago` es lo que devuelven la búsqueda y la consulta del pago."""
    estado = {"pago": None}

    async def crear_orden_qr(**kwargs):
        return {}

    async def buscar_pago_por_referencia(external_reference, access_token):
        return estado["pago"]

    async def eliminar_orden_qr(user_id, pos_id, access_token):
        return None

    async def obtener_pago(payment_id, access_token):
        return estado["pago"]

    monkeypatch.setattr(mp_api, "crear_orden_qr", crear_orden_qr)
    monkeypatch.setattr(mp_api, "buscar_pago_por_referencia", buscar_pago_por_referencia)
    monkeypatch.setattr(mp_api, "eliminar_orden_qr", eliminar_orden_qr)
    monkeypatch.setattr(mp_api, "obtener_pago", obtener_pago)
    return estado


def _configurar_mp(api):
    """Las credenciales del QR y el secreto del webhook, por la API. El prefijo
    se lee de la firma del router del motor: repetir el string acá confirmaría
    una suposición propia y no la del código."""
    import inspect

    from libracore.mp_config_router import build_mp_config_router

    ruta = inspect.signature(build_mp_config_router).parameters["prefix"].default
    r = api.put(ruta, json={
        "mp_access_token": "APP_USR-token-de-prueba",
        "mp_user_id": "123456789",
        "mp_pos_id": "CAJA01",
        "mp_webhook_secret": SECRETO_WEBHOOK,
        "mp_auto_facturar_ventas": False,
    })
    assert r.status_code == 200, r.text


def _reserva(api, cancha, cliente) -> dict:
    r = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": cliente.id,
        "comienza_at": "2026-09-01T20:00:00-03:00", "duracion_min": 90,
        "precio": "10000.00",
    })
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def gaseosa(api, sucursal):
    r = api.post(f"/api/buffet/productos?sucursal_id={sucursal.id}", json={
        "nombre": "Gaseosa 500ml", "precio": "1200.00", "costo": "700.00",
        "stock_minimo": "6"})
    assert r.status_code == 201, r.text
    producto = r.json()
    api.post(f"/api/buffet/ajustes?sucursal_id={sucursal.id}", json={
        "item_id": producto["item_id"], "cantidad": "24", "motivo": "Entrega"})
    return producto


# ── El QR del mostrador: poner el monto, bajarlo y el poll ───────────────

#: Qué llamada a MercadoPago hace cada ruta del QR. Es la que se pone lenta: las
#: tres corren adentro de una corrutina de `servicios/cobro_qr.py` que, entre
#: medio, lee y escribe la base.
LLAMADA_A_MP = {
    "poner": "crear_orden_qr",
    "bajar": "eliminar_orden_qr",
    "estado": "buscar_pago_por_referencia",
}
CODIGO = {"poner": 201, "bajar": 204, "estado": 200}


@pytest.mark.parametrize("accion", list(LLAMADA_A_MP))
def test_el_qr_del_turno_no_frena_el_loop(
    api, cancha, cliente, tarifa_base, mp, monkeypatch, accion,
):
    """🔑 El poll es el que más pesa: la pantalla lo pide cada 3 segundos
    mientras el cliente escanea."""
    _configurar_mp(api)
    reserva = _reserva(api, cancha, cliente)
    qr = f"/api/reservas/{reserva['id']}/mp-qr"
    if accion != "poner":
        # La orden ya puesta, por el camino rápido: bajarla y consultarla
        # necesitan un pago pendiente.
        puesta = api.post(qr)
        assert puesta.status_code == 201, puesta.text
    lento = _Lento()
    _corrutina_lenta(monkeypatch, lento, mp_api, LLAMADA_A_MP[accion])
    pedir = {
        "poner": lambda c: c.post(qr),
        "bajar": lambda c: c.delete(qr),
        "estado": lambda c: c.get(f"/api/reservas/{reserva['id']}/mp-status"),
    }[accion]

    respuesta, health, fin = _mientras_duerme(api, lento, pedir)

    assert respuesta.status_code == CODIGO[accion], respuesta.text
    if accion == "estado":
        assert respuesta.json()["estado"] == "pendiente"
    _no_bloqueo(lento, health, fin)


@pytest.mark.parametrize("accion", list(LLAMADA_A_MP))
def test_el_qr_de_la_venta_de_buffet_no_frena_el_loop(
    api, sucursal, gaseosa, mp, monkeypatch, accion,
):
    _configurar_mp(api)
    alta = f"/api/buffet/ventas/qr?sucursal_id={sucursal.id}"
    lineas = {"lineas": [{"item_id": gaseosa["item_id"], "cantidad": "2"}]}
    venta_id = None
    if accion != "poner":
        puesta = api.post(alta, json=lineas)
        assert puesta.status_code == 201, puesta.text
        venta_id = puesta.json()["venta_id"]
    lento = _Lento()
    _corrutina_lenta(monkeypatch, lento, mp_api, LLAMADA_A_MP[accion])
    pedir = {
        "poner": lambda c: c.post(alta, json=lineas),
        "bajar": lambda c: c.delete(f"/api/buffet/ventas/{venta_id}/mp-qr"),
        "estado": lambda c: c.get(f"/api/buffet/ventas/{venta_id}/mp-status"),
    }[accion]

    respuesta, health, fin = _mientras_duerme(api, lento, pedir)

    assert respuesta.status_code == CODIGO[accion], respuesta.text
    if accion == "estado":
        assert respuesta.json()["estado"] == "pendiente"
    _no_bloqueo(lento, health, fin)


# ── Facturar el turno ────────────────────────────────────────────────────


def test_facturar_el_turno_no_frena_el_loop(api, cancha, cliente, tarifa_base, monkeypatch):
    """🔑 Lo lento va ADENTRO de `facturar_reserva` —el numerador, que en
    producción autentica contra el WSAA firmando con `openssl`—. Es el caso que
    un `await` desde el loop no resuelve aunque la ruta fuera `def`."""
    reserva = _reserva(api, cancha, cliente)
    lento = _Lento()
    real = arca_facturacion.get_next_numero_with_arca

    async def numerar_con_openssl(*args, **kwargs):
        lento.dormir()
        return await real(*args, **kwargs)

    monkeypatch.setattr(arca_facturacion, "get_next_numero_with_arca", numerar_con_openssl)

    respuesta, health, fin = _mientras_duerme(
        api, lento, lambda c: c.post(f"/api/reservas/{reserva['id']}/facturar"))

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["total"] > 0
    _no_bloqueo(lento, health, fin)


# ── El simulador del cobro por QR (dev y demo) ───────────────────────────


def test_simular_el_cobro_del_turno_no_frena_el_loop(
    api, sucursal, cancha, cliente, tarifa_base, abrir_caja, monkeypatch,
):
    """Lo lento va adentro de `cobro_qr._completar`: el ingreso a la caja, que es
    la base de LibraCore. En dev y demo uvicorn también corre con un solo
    proceso."""
    abierta = abrir_caja(api, sucursal)
    assert abierta.status_code in (200, 201), abierta.text
    reserva = _reserva(api, cancha, cliente)
    lento = _Lento()
    real = servicio_caja.registrar_ingreso

    def ingreso_lento(*args, **kwargs):
        lento.dormir()
        return real(*args, **kwargs)

    monkeypatch.setattr(servicio_caja, "registrar_ingreso", ingreso_lento)

    respuesta, health, fin = _mientras_duerme(
        api, lento, lambda c: c.post(f"/api/reservas/{reserva['id']}/mp-qr/simular"))

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"] == "aprobado"
    _no_bloqueo(lento, health, fin)


# ── El webhook de MercadoPago ────────────────────────────────────────────


def _firmar(payment_id: str, request_id: str, secreto: str) -> str:
    ts = "1700000000"
    plantilla = f"id:{payment_id};request-id:{request_id};ts:{ts}"
    v1 = hmac.new(secreto.encode(), plantilla.encode(), hashlib.sha256).hexdigest()
    return f"ts={ts},v1={v1}"


@pytest.mark.parametrize("de_quien", ["nuestro", "ajeno"])
def test_el_webhook_no_frena_el_loop(
    api, cancha, cliente, tarifa_base, mp, monkeypatch, de_quien,
):
    """🔑 El webhook sigue siendo `async` por el cuerpo crudo, que hace falta
    para la firma; el resto tiene que salir del loop entero.

    - `nuestro`: un pago del mostrador. Lo lento va adentro de `obtener_pago`,
      la consulta a MercadoPago que el webhook hace antes de tocar la base.
    - `ajeno`: un cobro que no salió de un turno. Lo lento va adentro de
      `mp_sync.ingerir`, que escribe la bandeja entre medio de lo que le pide a
      MercadoPago.
    """
    _configurar_mp(api)
    lento = _Lento()
    if de_quien == "nuestro":
        reserva = _reserva(api, cancha, cliente)
        puesta = api.post(f"/api/reservas/{reserva['id']}/mp-qr")
        assert puesta.status_code == 201, puesta.text
        pago = {"id": 112233, "status": "approved",
                "external_reference": puesta.json()["referencia"]}
        _corrutina_lenta(monkeypatch, lento, mp_api, "obtener_pago", pago)
    else:
        mp["pago"] = {"id": 112233, "status": "approved",
                      "external_reference": "transferencia-suelta"}
        _corrutina_lenta(monkeypatch, lento, mp_sync, "ingerir", [])

    cuerpo = json.dumps({"type": "payment", "data": {"id": "112233"}})
    respuesta, health, fin = _mientras_duerme(api, lento, lambda c: c.post(
        "/api/portal/webhook",
        content=cuerpo,
        headers={
            "content-type": "application/json",
            "x-request-id": "req-loop",
            "x-signature": _firmar("112233", "req-loop", SECRETO_WEBHOOK),
        },
    ))

    assert respuesta.status_code == 200, respuesta.text
    if de_quien == "nuestro":
        assert respuesta.json() == {"ok": True, "confirmada": True}
    else:
        assert respuesta.json() == {"ok": True, "motivo": "a la bandeja (0 nuevos)"}
    _no_bloqueo(lento, health, fin)
