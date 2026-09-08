"""El cobro con QR de una **venta suelta del buffet**, que no tiene turno detrás.

Es el mismo cartel de la caja que cobra los turnos (`test_cobro_qr.py`), sobre la
otra cosa que se cobra en el mostrador: la gaseosa que compra alguien que no está
jugando. Nada de esto habla con MercadoPago — `libracore.mp_api` se reemplaza por
dobles que registran con qué se los llamó.

Lo que se fija acá es lo que este camino tiene de propio:

- 🔴 **poner el monto en el QR NO mueve stock ni plata.** La venta queda en
  borrador; si nadie escanea, no pasó nada. Es la diferencia central con el cobro
  en efectivo, que descuenta y cobra en el mismo request.
- 🔴 **el pago no cuelga de ninguna reserva** (`pagos_de_reserva.reserva_id` en
  `NULL`), así que el webhook y `aplicar_pago_aprobado` tienen que atravesarlo sin
  buscar un turno que no existe.
- que al acreditarse entre a la caja **con la misma referencia** que el cobro en
  efectivo de una venta de buffet, para que el arqueo vea una sola clase de
  movimiento.

> ⚠️ El doble de `mp_api` y las fixtures del arnés están **duplicados** de
> `test_cobro_qr.py`. Es a propósito por ahora: ese archivo declara en su
> docstring que sus tests son el control de una extracción anterior, así que no
> se toca de arrastre. Cuando haya un tercer consumidor, el lugar de la clase es
> `conftest.py`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libracore import mp_api

from app.config import Config
from app.main import crear_app
from app.models.reservas import EstadoPago, PagoDeReserva
from app.servicios import pagos as servicio_pagos

USUARIO, CLAVE = "admin", "clave-de-prueba"
SECRETO_WEBHOOK = "no-es-un-secreto-real"

#: Lo que sale la gaseosa de las fixtures, para no repetir el número.
PRECIO_GASEOSA = 1200.0


# ── Arnés ────────────────────────────────────────────────────────────────


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


class _MpFalso:
    """Doble de `libracore.mp_api` que guarda con qué lo llamaron.

    Guarda **todas** las llamadas y no la última: la mitad de estos tests miden
    justamente que una segunda no ocurra.
    """

    def __init__(self):
        self.ordenes = []
        self.busquedas = []
        self.bajas = []
        #: `None` = todavía nadie escaneó el QR.
        self.pago = None

    def instalar(self, monkeypatch):
        async def crear_orden_qr(**kwargs):
            self.ordenes.append(kwargs)
            return {}  # MercadoPago contesta 204 sin cuerpo.

        async def buscar_pago_por_referencia(external_reference, access_token):
            self.busquedas.append(external_reference)
            return self.pago

        async def eliminar_orden_qr(user_id, pos_id, access_token):
            self.bajas.append((user_id, pos_id))

        async def obtener_pago(payment_id, access_token):
            return self.pago

        monkeypatch.setattr(mp_api, "crear_orden_qr", crear_orden_qr)
        monkeypatch.setattr(mp_api, "buscar_pago_por_referencia", buscar_pago_por_referencia)
        monkeypatch.setattr(mp_api, "eliminar_orden_qr", eliminar_orden_qr)
        monkeypatch.setattr(mp_api, "obtener_pago", obtener_pago)
        return self

    def aprobado(self, referencia, payment_id=445566):
        self.pago = {
            "id": payment_id, "status": "approved", "external_reference": referencia,
        }

    def rechazado(self, referencia, payment_id=445567):
        self.pago = {
            "id": payment_id, "status": "rejected", "external_reference": referencia,
        }


@pytest.fixture
def mp(monkeypatch):
    return _MpFalso().instalar(monkeypatch)


def _ruta_mp() -> str:
    """El prefijo del router de configuración del motor, leído de su firma.

    🔴 **No se repite el string.** Un test que declara la ruta que espera
    confirma su propia suposición, no la del código.
    """
    import inspect

    from libracore.mp_config_router import build_mp_config_router

    return inspect.signature(build_mp_config_router).parameters["prefix"].default


def _configurar_mp(api):
    r = api.put(_ruta_mp(), json={
        "mp_access_token": "APP_USR-token-de-prueba",
        "mp_user_id": "123456789",
        "mp_pos_id": "CAJA01",
        "mp_webhook_secret": SECRETO_WEBHOOK,
        "mp_auto_facturar_ventas": False,
    })
    assert r.status_code == 200, r.text


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


def _stock(api, sucursal, item_id) -> float:
    filas = api.get(f"/api/buffet/productos?sucursal_id={sucursal.id}").json()
    return next(f["stock"] for f in filas if f["item_id"] == item_id)


def _poner_en_el_qr(api, sucursal, item_id, cantidad="2"):
    r = api.post(f"/api/buffet/ventas/qr?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": item_id, "cantidad": cantidad}]})
    assert r.status_code == 201, r.text
    return r.json()


def _resumen(api) -> dict:
    return api.get("/api/caja/turnos/actual").json()["resumen"]


# ── Sin configurar ───────────────────────────────────────────────────────


def test_sin_credenciales_no_se_pone_nada_en_el_qr_y_dice_que_falta(
    api, sucursal, gaseosa, mp, abrir_caja,
):
    abrir_caja(api, sucursal)
    r = api.post(f"/api/buffet/ventas/qr?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": gaseosa["item_id"], "cantidad": "1"}]})
    assert r.status_code == 400, r.text
    detalle = r.json()["detail"]
    assert "Access Token" in detalle and "User ID" in detalle and "POS ID" in detalle
    assert mp.ordenes == []
    assert _stock(api, sucursal, gaseosa["item_id"]) == 24.0, (
        "la guarda corre antes de mover stock")
    assert _resumen(api)["total_ventas"] == 0.0


# ── Poner el monto en el QR ──────────────────────────────────────────────


def test_poner_la_venta_en_el_qr_NO_mueve_stock_ni_plata(
    api, sucursal, gaseosa, mp, abrir_caja,
):
    """🔴 **El gate de este camino.** Si el borrador descontara stock, un QR que
    nadie escanea dejaría el buffet faltando dos gaseosas que siguen en la
    heladera — y el que lo descubre es el inventario, semanas después.
    """
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    puesta = _poner_en_el_qr(api, sucursal, gaseosa["item_id"])

    assert puesta["monto"] == 2 * PRECIO_GASEOSA
    assert puesta["numero"].startswith("BUF-")
    assert _stock(api, sucursal, gaseosa["item_id"]) == 24.0, "el borrador no mueve stock"
    assert _resumen(api)["total_ventas"] == 0.0, "todavía nadie pagó"

    # Y la orden que se creó lleva el total y las líneas que se le muestran al
    # cliente en la app de MercadoPago.
    assert len(mp.ordenes) == 1
    orden = mp.ordenes[0]
    assert orden["total"] == 2 * PRECIO_GASEOSA
    assert orden["external_reference"] == puesta["referencia"]
    assert [i["nombre"] for i in orden["items"]] == ["Gaseosa 500ml"]
    assert orden["items"][0]["qty"] == 2.0


def test_la_referencia_lleva_el_prefijo_del_producto(api, sucursal, gaseosa, mp, abrir_caja):
    """🔑 **La bandeja de conciliación del motor omite lo que empieza con este
    prefijo.** Una referencia de buffet con otro prefijo aparecería en la bandeja
    como si nadie la hubiera conciliado, con el cobro ya en la caja: el mismo
    ingreso, contado dos veces.
    """
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    puesta = _poner_en_el_qr(api, sucursal, gaseosa["item_id"])
    assert puesta["referencia"].startswith(servicio_pagos.PREFIJO_DE_REFERENCIA)


def test_el_consumo_de_una_cancha_no_se_cobra_por_este_camino(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa, mp, abrir_caja,
):
    """Lo que se toma en la cancha se cobra con el turno, en un solo escaneo y
    con una sola factura. Dos QR por un mismo grupo es lo que el diseño evita."""
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    r = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": cliente.id,
        "comienza_at": "2026-09-01T20:00:00-03:00", "duracion_min": 90})
    reserva_id = r.json()["id"]

    r = api.post(f"/api/buffet/ventas/qr?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": gaseosa["item_id"], "cantidad": "1"}],
        "reserva_id": reserva_id})
    assert r.status_code == 422, r.text
    assert mp.ordenes == []


# ── El poll, que es donde se completa el cobro ───────────────────────────


def test_al_acreditarse_la_venta_se_confirma_descuenta_stock_y_entra_a_la_caja(
    api, sucursal, gaseosa, mp, abrir_caja,
):
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    puesta = _poner_en_el_qr(api, sucursal, gaseosa["item_id"])
    mp.aprobado(puesta["referencia"])

    estado = api.get(f"/api/buffet/ventas/{puesta['venta_id']}/mp-status")
    assert estado.status_code == 200, estado.text
    assert estado.json()["estado"] == "aprobado"

    assert _stock(api, sucursal, gaseosa["item_id"]) == 22.0, "recién ahora sale del depósito"
    resumen = _resumen(api)
    assert resumen["pagos_por_medio"]["mercadopago"] == 2 * PRECIO_GASEOSA
    assert resumen["efectivo_ventas"] == 0.0, "por QR no entra efectivo"


def test_el_segundo_tick_no_cobra_ni_descuenta_dos_veces(
    api, sucursal, gaseosa, mp, abrir_caja,
):
    """El poll corre cada 3 segundos: pegarle dos veces al mismo pago aprobado es
    el caso normal, no el raro."""
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    puesta = _poner_en_el_qr(api, sucursal, gaseosa["item_id"])
    mp.aprobado(puesta["referencia"])

    primero = api.get(f"/api/buffet/ventas/{puesta['venta_id']}/mp-status").json()
    segundo = api.get(f"/api/buffet/ventas/{puesta['venta_id']}/mp-status").json()
    assert primero["estado"] == segundo["estado"] == "aprobado"

    assert _stock(api, sucursal, gaseosa["item_id"]) == 22.0
    assert _resumen(api)["pagos_por_medio"]["mercadopago"] == 2 * PRECIO_GASEOSA


def test_el_pago_rechazado_no_confirma_la_venta_ni_toca_el_stock(
    api, sucursal, gaseosa, mp, abrir_caja,
):
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    puesta = _poner_en_el_qr(api, sucursal, gaseosa["item_id"])
    mp.rechazado(puesta["referencia"])

    estado = api.get(f"/api/buffet/ventas/{puesta['venta_id']}/mp-status").json()
    assert estado["estado"] == "rechazado"
    assert _stock(api, sucursal, gaseosa["item_id"]) == 24.0
    assert _resumen(api)["total_ventas"] == 0.0


def test_sin_orden_el_poll_lo_dice_en_vez_de_explotar(api, sucursal, gaseosa, mp, abrir_caja):
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    estado = api.get("/api/buffet/ventas/999/mp-status").json()
    assert estado["estado"] == "sin_orden"


def test_sin_turno_abierto_el_poll_da_409_y_el_tick_siguiente_completa(
    api, sucursal, gaseosa, mp, abrir_caja,
):
    """🔑 **El pago ya está sellado cuando esto salta, así que el 409 no pierde
    nada**: el encargado abre el turno y el tick siguiente confirma la venta y
    completa la caja. Cobrar sin turno dejaría la plata fuera de todo arqueo.
    """
    _configurar_mp(api)
    puesta = _poner_en_el_qr(api, sucursal, gaseosa["item_id"])
    mp.aprobado(puesta["referencia"])

    r = api.get(f"/api/buffet/ventas/{puesta['venta_id']}/mp-status")
    assert r.status_code == 409, r.text

    abrir_caja(api, sucursal)
    estado = api.get(f"/api/buffet/ventas/{puesta['venta_id']}/mp-status")
    assert estado.status_code == 200, estado.text
    assert estado.json()["estado"] == "aprobado"
    assert _resumen(api)["pagos_por_medio"]["mercadopago"] == 2 * PRECIO_GASEOSA
    assert _stock(api, sucursal, gaseosa["item_id"]) == 22.0


# ── Bajar el monto del QR ────────────────────────────────────────────────


def test_bajar_la_venta_del_qr_no_deja_stock_movido_ni_plata_anotada(
    api, sucursal, gaseosa, mp, abrir_caja,
):
    """🔴 **Sin esto, el próximo que escanee paga las gaseosas del anterior.**"""
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    puesta = _poner_en_el_qr(api, sucursal, gaseosa["item_id"])

    r = api.delete(f"/api/buffet/ventas/{puesta['venta_id']}/mp-qr")
    assert r.status_code == 204, r.text
    assert mp.bajas == [("123456789", "CAJA01")]
    assert _stock(api, sucursal, gaseosa["item_id"]) == 24.0
    assert _resumen(api)["total_ventas"] == 0.0

    # Y es idempotente: bajar de nuevo no vuelve a llamar a MercadoPago.
    assert api.delete(f"/api/buffet/ventas/{puesta['venta_id']}/mp-qr").status_code == 204
    assert len(mp.bajas) == 1


def test_una_venta_bajada_del_qr_ya_no_se_acredita(api, sucursal, gaseosa, mp, abrir_caja):
    """Control del test de arriba: si `bajar` no cambiara el estado del pago, un
    escaneo tardío la cobraría igual."""
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    puesta = _poner_en_el_qr(api, sucursal, gaseosa["item_id"])
    api.delete(f"/api/buffet/ventas/{puesta['venta_id']}/mp-qr")
    mp.aprobado(puesta["referencia"])

    estado = api.get(f"/api/buffet/ventas/{puesta['venta_id']}/mp-status").json()
    assert estado["estado"] == "vencido"
    assert _stock(api, sucursal, gaseosa["item_id"]) == 24.0
    assert _resumen(api)["total_ventas"] == 0.0


# ── El webhook, que es la otra puerta ────────────────────────────────────


def _firmar(payment_id: str, request_id: str, secreto: str) -> str:
    ts = "1700000000"
    plantilla = f"id:{payment_id};request-id:{request_id};ts:{ts}"
    v1 = hmac.new(secreto.encode(), plantilla.encode(), hashlib.sha256).hexdigest()
    return f"ts={ts},v1={v1}"


def test_el_webhook_sella_un_pago_SIN_reserva_y_el_poll_completa(
    api, sesion, sucursal, gaseosa, mp, abrir_caja,
):
    """🔴 **Es el camino que la revisión `0011` podía romper.** Un pago de buffet
    tiene `reserva_id` en `NULL`, y `aplicar_pago_aprobado` buscaba la reserva
    siempre: sin la rama que lo saltea, el webhook explota con «apunta a una
    reserva que no existe» y MercadoPago reintenta durante días.

    Y como el webhook no sabe quién cobra, **no toca la caja**: sella y el poll
    —con el cajero ahí— completa.
    """
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    puesta = _poner_en_el_qr(api, sucursal, gaseosa["item_id"])
    mp.aprobado(puesta["referencia"], payment_id="778899")

    cuerpo = json.dumps({"type": "payment", "data": {"id": "778899"}})
    r = api.post(
        "/api/portal/webhook",
        content=cuerpo,
        headers={
            "content-type": "application/json",
            "x-request-id": "req-buf",
            "x-signature": _firmar("778899", "req-buf", SECRETO_WEBHOOK),
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    assert _resumen(api)["total_ventas"] == 0.0, "el webhook no puede cobrar: no sabe en qué turno"
    assert _stock(api, sucursal, gaseosa["item_id"]) == 24.0, "ni confirmar la venta"

    # El poll siguiente completa **sin volver a preguntarle a MercadoPago**.
    antes = len(mp.busquedas)
    estado = api.get(f"/api/buffet/ventas/{puesta['venta_id']}/mp-status")
    assert estado.json()["estado"] == "aprobado"
    assert len(mp.busquedas) == antes, "ya estaba sellado"
    assert _resumen(api)["pagos_por_medio"]["mercadopago"] == 2 * PRECIO_GASEOSA
    assert _stock(api, sucursal, gaseosa["item_id"]) == 22.0


# ── El origen del pago, que es uno de dos ────────────────────────────────


def test_un_pago_sin_reserva_y_sin_venta_lo_rechaza_la_base(api, sesion, sucursal):
    """🔴 El CHECK de la revisión `0011`. Sin él, una fila con los dos orígenes
    en `NULL` es un cobro que no cobra nada a nadie, y el que lo descubre es el
    arqueo."""
    from decimal import Decimal

    from sqlalchemy.exc import IntegrityError

    sesion.add(PagoDeReserva(
        reserva_id=None, venta_id=None, monto=Decimal("100.00"),
        estado=EstadoPago.PENDIENTE, referencia="lc-buf-sin-origen",
    ))
    with pytest.raises(IntegrityError):
        sesion.flush()
    sesion.rollback()


def test_no_se_cobra_dos_veces_la_misma_venta(api, sesion, sucursal, gaseosa, mp, abrir_caja):
    """El índice parcial `uq_pagos_venta_aprobado` lo impide en la base, pero el
    servicio corta antes con un error de dominio: fallar en el índice sería un
    500 que no le dice nada al operador."""
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    puesta = _poner_en_el_qr(api, sucursal, gaseosa["item_id"])
    mp.aprobado(puesta["referencia"])
    api.get(f"/api/buffet/ventas/{puesta['venta_id']}/mp-status")

    with pytest.raises(servicio_pagos.PagoInvalido):
        servicio_pagos.crear_pago_de_buffet(sesion, puesta["venta_id"], 1.0)


# ── El simulador de dev ──────────────────────────────────────────────────


def test_el_simulador_deja_la_venta_cobrada_igual_que_el_cobro_real(
    api, sucursal, gaseosa, abrir_caja,
):
    """Sin credenciales el circuito no se puede recorrer de punta a punta, así
    que el simulador cubre los dos pasos: no hay orden que crear ni pago que
    sellar si `poner_venta_en_el_qr` falló al llamar a MercadoPago."""
    abrir_caja(api, sucursal)
    r = api.post(f"/api/buffet/ventas/qr/simular?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": gaseosa["item_id"], "cantidad": "3"}]})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["simulado"] is True
    assert cuerpo["estado"] == "aprobado"
    assert cuerpo["monto"] == 3 * PRECIO_GASEOSA

    assert _stock(api, sucursal, gaseosa["item_id"]) == 21.0
    assert _resumen(api)["pagos_por_medio"]["mercadopago"] == 3 * PRECIO_GASEOSA


def test_el_simulador_sin_turno_abierto_tampoco_cobra(api, sucursal, gaseosa, abrir_caja):
    """🔑 **Lo que NO entra es la plata; el stock sí sale, y es correcto.**

    Cuando `SinTurnoAbierto` salta, el pago ya está aprobado: el cliente pagó y
    se llevó la gaseosa. Confirmar la venta es el hecho más firme de los dos, así
    que `_completar_venta` lo hace primero y deja pendiente sólo el movimiento de
    caja — que es lo que el tick siguiente reintenta, sin contar plata dos veces.
    Al revés —caja primero— un fallo al confirmar dejaría plata anotada sin venta.
    """
    r = api.post(f"/api/buffet/ventas/qr/simular?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": gaseosa["item_id"], "cantidad": "1"}]})
    assert r.status_code == 409, r.text
    assert _stock(api, sucursal, gaseosa["item_id"]) == 23.0, "la venta se confirmó"

    # Y la plata no entró por ningún lado: no hay turno donde anotarla.
    abrir_caja(api, sucursal)
    assert _resumen(api)["total_ventas"] == 0.0


def test_el_simulador_no_existe_en_produccion(engine, sesion, monkeypatch, base_de_libracore):
    """🔴 **Es lo único que separa dev de regalar mercadería.** El router no se
    monta: no alcanza con un `if` adentro del handler."""
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    produccion = Config(
        database_url=os.environ["DATABASE_URL"], entorno="production", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
        libracore_database_url=base_de_libracore,
    )
    cliente = TestClient(crear_app(produccion), base_url="https://testserver")
    cliente.post("/auth/login", json={"username": USUARIO, "password": CLAVE})
    try:
        assert cliente.get("/api/buffet/mp-qr/simulacion").status_code == 404
        assert cliente.post(
            "/api/buffet/ventas/qr/simular?sucursal_id=1", json={"lineas": []},
        ).status_code == 404
    finally:
        AuthBase.metadata.drop_all(engine)


def test_fuera_de_produccion_el_sondeo_del_simulador_existe(api):
    """Control del test de arriba: si la ruta no existiera nunca, aquél pasaría
    igual sin probar el gate del entorno."""
    assert api.get("/api/buffet/mp-qr/simulacion").json() == {"disponible": True}
