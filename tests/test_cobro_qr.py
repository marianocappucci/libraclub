"""El cobro con QR de MercadoPago en el mostrador, y la factura que sale sola.

Nada de esto habla con MercadoPago: `libracore.mp_api` se reemplaza por dobles
que registran con qué se los llamó. Lo que se mide acá es **este** producto: qué
se pone a cobrar, cuándo entra a la caja, cuándo sale la factura, y qué pasa
cuando el webhook y el poll se cruzan.

🔑 El gate del cobro es el mismo que el de F4: **el QR cobra la cancha más el
buffet**. Si cobrara sólo `reserva.precio`, la factura saldría por más de lo que
entró y el arqueo del turno no cerraría — y el que lo descubre es el cierre,
horas después.
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
from libracore import config_manager, mp_api

from app.config import Config
from app.main import crear_app
from app.servicios import cobro_qr

USUARIO, CLAVE = "admin", "clave-de-prueba"
SECRETO_WEBHOOK = "no-es-un-secreto-real"


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
        #: Lo que devuelven `buscar_pago_por_referencia` y `obtener_pago`.
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

    def aprobado(self, referencia, payment_id=112233):
        self.pago = {
            "id": payment_id, "status": "approved", "external_reference": referencia,
        }


@pytest.fixture
def mp(monkeypatch):
    return _MpFalso().instalar(monkeypatch)


def _configurar_mp(api, auto_facturar=False):
    r = api.put("/config/mercadopago", json={
        "access_token": "APP_USR-token-de-prueba",
        "user_id": "123456789",
        "pos_id": "CAJA01",
        "webhook_secret": SECRETO_WEBHOOK,
        "auto_facturar": auto_facturar,
    })
    assert r.status_code == 200, r.text
    return r.json()



def _reserva(api, cancha, cliente, precio="10000.00", **extra):
    datos = {
        "cancha_id": cancha.id, "cliente_id": cliente.id,
        "comienza_at": "2026-09-01T20:00:00-03:00", "duracion_min": 90,
        "precio": precio,
    }
    datos.update(extra)
    r = api.post("/api/reservas", json=datos)
    assert r.status_code == 201, r.text
    return r.json()


def _consumir_en_la_cancha(api, sucursal, reserva_id, item_id, cantidad="2"):
    """Carga buffet a la reserva, que es lo que hace que el total no sea sólo
    la cancha."""
    r = api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "reserva_id": reserva_id,
        "lineas": [{"item_id": item_id, "cantidad": cantidad}],
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


# ── Sin configurar ───────────────────────────────────────────────────────


def test_sin_credenciales_el_mostrador_sabe_que_no_puede_cobrar(api):
    assert api.get("/api/reservas/mp/estado").json() == {
        "disponible": False, "auto_facturar": False,
    }


def test_sin_credenciales_poner_el_monto_da_400_y_dice_que_falta(
    api, cancha, cliente, tarifa_base, mp,
):
    reserva = _reserva(api, cancha, cliente)
    r = api.post(f"/api/reservas/{reserva['id']}/mp-qr")
    assert r.status_code == 400, r.text
    detalle = r.json()["detail"]
    assert "Access Token" in detalle and "User ID" in detalle and "POS ID" in detalle
    assert mp.ordenes == []


def test_falta_uno_solo_de_los_tres_y_sigue_sin_estar_configurado(api):
    """El token solo no alcanza: el user id y el pos id van en la URL de la
    orden. Sin esta comprobación, una instancia a medio configurar pasa el
    chequeo y MercadoPago devuelve un 404 que no dice qué falta."""
    for faltante in ("access_token", "user_id", "pos_id"):
        datos = {
            "access_token": "APP_USR-x", "user_id": "1", "pos_id": "CAJA01",
            "webhook_secret": "", "auto_facturar": False,
        }
        datos[faltante] = ""
        assert api.put("/config/mercadopago", json=datos).json()["configurado"] is False, faltante

    # Control positivo: con los tres, sí. Sin esto, un `esta_configurado()` que
    # devolviera siempre False pasaría el test.
    assert api.put("/config/mercadopago", json={
        "access_token": "APP_USR-x", "user_id": "1", "pos_id": "CAJA01",
        "webhook_secret": "", "auto_facturar": False,
    }).json()["configurado"] is True


# ── Qué se pone a cobrar ─────────────────────────────────────────────────


def test_el_qr_cobra_la_cancha_MAS_el_buffet(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa, mp,
):
    """🔴 El gate. Si cobrara sólo `reserva.precio`, la factura saldría por más
    de lo que entró y el arqueo del turno no cerraría."""
    _configurar_mp(api)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")
    _consumir_en_la_cancha(api, sucursal, reserva["id"], gaseosa["item_id"], "2")

    r = api.post(f"/api/reservas/{reserva['id']}/mp-qr")
    assert r.status_code == 201, r.text
    assert r.json()["monto"] == 12400.0, "10.000 de cancha + 2 gaseosas de 1.200"

    orden = mp.ordenes[0]
    assert orden["total"] == 12400.0
    assert orden["user_id"] == "123456789"
    assert orden["pos_id"] == "CAJA01"
    nombres = [i["nombre"] for i in orden["items"]]
    assert any("Alquiler de Cancha 1" in n for n in nombres)
    assert "Gaseosa 500ml" in nombres


def test_un_turno_sin_precio_no_se_puede_cobrar(api, cancha, cliente, mp):
    _configurar_mp(api)
    reserva = _reserva(api, cancha, cliente, precio="0")

    r = api.post(f"/api/reservas/{reserva['id']}/mp-qr")
    assert r.status_code == 422, r.text
    assert mp.ordenes == []


def test_cada_intento_usa_una_referencia_distinta(api, cancha, cliente, tarifa_base, mp):
    """Reusarla haría que un pago rechazado que MercadoPago acredita tarde
    vuelva como aprobado para el intento siguiente."""
    _configurar_mp(api)
    reserva = _reserva(api, cancha, cliente)

    primera = api.post(f"/api/reservas/{reserva['id']}/mp-qr").json()["referencia"]
    segunda = api.post(f"/api/reservas/{reserva['id']}/mp-qr").json()["referencia"]
    assert primera != segunda
    assert primera.startswith(f"lc-{reserva['id']}-")


def test_bajar_del_qr_saca_la_orden_de_la_caja(api, cancha, cliente, tarifa_base, mp):
    """Una orden que queda puesta le cobra ese monto al próximo que escanee."""
    _configurar_mp(api)
    reserva = _reserva(api, cancha, cliente)
    api.post(f"/api/reservas/{reserva['id']}/mp-qr")

    assert api.delete(f"/api/reservas/{reserva['id']}/mp-qr").status_code == 204
    assert mp.bajas == [("123456789", "CAJA01")]

    # Idempotente: bajarla de nuevo no vuelve a pegarle a MercadoPago.
    api.delete(f"/api/reservas/{reserva['id']}/mp-qr")
    assert len(mp.bajas) == 1


# ── El poll ──────────────────────────────────────────────────────────────


def test_sin_orden_puesta_el_poll_lo_dice(api, cancha, cliente, tarifa_base, mp):
    _configurar_mp(api)
    reserva = _reserva(api, cancha, cliente)
    assert api.get(f"/api/reservas/{reserva['id']}/mp-status").json()["estado"] == "sin_orden"


def test_mientras_nadie_escanee_el_poll_dice_pendiente(api, cancha, cliente, tarifa_base, mp):
    _configurar_mp(api)
    reserva = _reserva(api, cancha, cliente)
    api.post(f"/api/reservas/{reserva['id']}/mp-qr")

    r = api.get(f"/api/reservas/{reserva['id']}/mp-status")
    assert r.json() == {"estado": "pendiente", "payment_id": None, "factura_id": None}


def test_un_pago_rechazado_no_acredita_nada(
    api, cancha, cliente, tarifa_base, mp, abrir_caja, sucursal,
):
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente)
    referencia = api.post(f"/api/reservas/{reserva['id']}/mp-qr").json()["referencia"]
    mp.pago = {"id": 999, "status": "rejected", "external_reference": referencia}

    r = api.get(f"/api/reservas/{reserva['id']}/mp-status")
    assert r.json()["estado"] == "rechazado"
    assert api.get("/api/caja/turnos/actual").json()["resumen"]["total_ventas"] == 0.0


def test_al_acreditarse_entra_a_la_caja_del_turno(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa, mp, abrir_caja,
):
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")
    _consumir_en_la_cancha(api, sucursal, reserva["id"], gaseosa["item_id"], "2")
    referencia = api.post(f"/api/reservas/{reserva['id']}/mp-qr").json()["referencia"]
    mp.aprobado(referencia)

    r = api.get(f"/api/reservas/{reserva['id']}/mp-status")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "aprobado"
    assert r.json()["payment_id"] == "112233"

    resumen = api.get("/api/caja/turnos/actual").json()["resumen"]
    assert resumen["pagos_por_medio"]["mercadopago"] == 12400.0


def test_el_poll_repetido_no_cobra_dos_veces(
    api, cancha, cliente, tarifa_base, mp, abrir_caja, sucursal,
):
    """🔴 La pantalla pollea cada 3 segundos. Sin la marca de
    `caja_movimiento_id`, cada tick sería otro ingreso en el arqueo."""
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")
    referencia = api.post(f"/api/reservas/{reserva['id']}/mp-qr").json()["referencia"]
    mp.aprobado(referencia)

    for _ in range(4):
        assert api.get(f"/api/reservas/{reserva['id']}/mp-status").json()["estado"] == "aprobado"

    resumen = api.get("/api/caja/turnos/actual").json()["resumen"]
    assert resumen["pagos_por_medio"]["mercadopago"] == 10000.0
    # Y no se le vuelve a preguntar a MercadoPago después del primer sí.
    assert len(mp.busquedas) == 1


def test_un_turno_ya_pagado_no_se_vuelve_a_poner_en_el_qr(
    api, cancha, cliente, tarifa_base, mp, abrir_caja, sucursal,
):
    """Volver a poner el monto dejaría el pago ya cobrado sin nada que lo ate al
    turno: la referencia nueva no lo encuentra y la vieja ya no se consulta."""
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente)
    referencia = api.post(f"/api/reservas/{reserva['id']}/mp-qr").json()["referencia"]
    mp.aprobado(referencia)
    api.get(f"/api/reservas/{reserva['id']}/mp-status")

    r = api.post(f"/api/reservas/{reserva['id']}/mp-qr")
    assert r.status_code == 409, r.text
    assert len(mp.ordenes) == 1


def test_sin_turno_abierto_el_cobro_no_se_pierde(
    api, cancha, cliente, tarifa_base, mp, abrir_caja, sucursal,
):
    """🔑 El pago **ya está acreditado** cuando esto salta.

    Cobrar sin turno dejaría la plata fuera del arqueo, así que el poll corta
    con 409 — pero el pago queda sellado. Al abrir el turno, el tick siguiente
    completa la caja: no hay que volver a cobrarle a nadie.
    """
    _configurar_mp(api)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")
    referencia = api.post(f"/api/reservas/{reserva['id']}/mp-qr").json()["referencia"]
    mp.aprobado(referencia)

    r = api.get(f"/api/reservas/{reserva['id']}/mp-status")
    assert r.status_code == 409, r.text

    abrir_caja(api, sucursal)
    r = api.get(f"/api/reservas/{reserva['id']}/mp-status")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "aprobado"
    assert api.get("/api/caja/turnos/actual").json()["resumen"]["pagos_por_medio"][
        "mercadopago"
    ] == 10000.0


# ── La factura automática ────────────────────────────────────────────────


def test_con_la_automatica_prendida_el_turno_sale_facturado(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa, mp, abrir_caja,
):
    _configurar_mp(api, auto_facturar=True)
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")
    _consumir_en_la_cancha(api, sucursal, reserva["id"], gaseosa["item_id"], "2")
    referencia = api.post(f"/api/reservas/{reserva['id']}/mp-qr").json()["referencia"]
    mp.aprobado(referencia)

    r = api.get(f"/api/reservas/{reserva['id']}/mp-status")
    assert r.status_code == 200, r.text
    assert r.json()["factura_id"] is not None

    factura = api.get(f"/api/reservas/{reserva['id']}/factura").json()
    assert factura is not None
    assert factura["total"] == 12400.0, "la factura cubre la cancha y el buffet"


def test_sin_la_automatica_el_mismo_cobro_no_factura(
    api, cancha, cliente, tarifa_base, mp, abrir_caja, sucursal,
):
    """El control negativo del test de arriba: sin esto, un `facturar` sin
    condición pasaría los dos."""
    _configurar_mp(api, auto_facturar=False)
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")
    referencia = api.post(f"/api/reservas/{reserva['id']}/mp-qr").json()["referencia"]
    mp.aprobado(referencia)

    assert api.get(f"/api/reservas/{reserva['id']}/mp-status").json()["factura_id"] is None
    assert api.get(f"/api/reservas/{reserva['id']}/factura").json() is None


def test_la_automatica_no_reemite_sobre_un_turno_ya_facturado(
    api, cancha, cliente, tarifa_base, mp, abrir_caja, sucursal,
):
    """Dos comprobantes por el mismo turno son dos veces el mismo ingreso ante
    ARCA, y no hay forma de anular uno sin nota de crédito."""
    _configurar_mp(api, auto_facturar=True)
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")
    a_mano = api.post(f"/api/reservas/{reserva['id']}/facturar")
    assert a_mano.status_code == 201, a_mano.text

    referencia = api.post(f"/api/reservas/{reserva['id']}/mp-qr").json()["referencia"]
    mp.aprobado(referencia)
    r = api.get(f"/api/reservas/{reserva['id']}/mp-status")
    assert r.json()["factura_id"] == a_mano.json()["id"], "la misma, no una segunda"


# ── El webhook: mismo endpoint, otro canal ───────────────────────────────


def _firmar(payment_id: str, request_id: str, secreto: str) -> str:
    ts = "1700000000"
    plantilla = f"id:{payment_id};request-id:{request_id};ts:{ts}"
    v1 = hmac.new(secreto.encode(), plantilla.encode(), hashlib.sha256).hexdigest()
    return f"ts={ts},v1={v1}"


def test_el_webhook_sella_el_pago_del_mostrador_pero_no_toca_la_caja(
    api, cancha, cliente, tarifa_base, mp, abrir_caja, sucursal,
):
    """🔑 **El movimiento de caja va contra el turno de QUIEN COBRA**, y el
    webhook no sabe quién es: llega de MercadoPago, sin sesión. Un ingreso sin
    `turno_id` queda fuera de todo arqueo.

    Así que el webhook sella y el poll —con el cajero ahí— completa. Este test
    fija las dos mitades: que el webhook encuentre el pago del mostrador por
    referencia (es la misma tabla y el mismo `external_reference` que el portal)
    y que **no** haya cobrado nada por su cuenta.
    """
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")
    referencia = api.post(f"/api/reservas/{reserva['id']}/mp-qr").json()["referencia"]
    mp.aprobado(referencia)

    cuerpo = json.dumps({"type": "payment", "data": {"id": "112233"}})
    r = api.post(
        "/api/portal/webhook",
        content=cuerpo,
        headers={
            "content-type": "application/json",
            "x-request-id": "req-1",
            "x-signature": _firmar("112233", "req-1", SECRETO_WEBHOOK),
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    assert api.get("/api/caja/turnos/actual").json()["resumen"]["total_ventas"] == 0.0, (
        "el webhook no puede cobrar: no sabe en qué turno"
    )

    # Y el poll siguiente completa, sin volver a preguntarle a MercadoPago.
    antes = len(mp.busquedas)
    estado = api.get(f"/api/reservas/{reserva['id']}/mp-status")
    assert estado.json()["estado"] == "aprobado"
    assert len(mp.busquedas) == antes, "ya estaba sellado"
    assert api.get("/api/caja/turnos/actual").json()["resumen"]["pagos_por_medio"][
        "mercadopago"
    ] == 10000.0


# ── La configuración ─────────────────────────────────────────────────────


def test_guardar_mercadopago_no_borra_el_resto_de_la_configuracion(api, base_de_libracore):
    """🔴 `config_manager.save()` mergea contra los DEFAULTS: guardar un dict con
    sólo las claves de MercadoPago dejaría el resto de `config.json` en su valor
    por defecto. El PUT contesta 200 y la pérdida recién se nota después."""
    guardada = api.put("/api/config/empresa", json={
        "empresa_nombre": "Complejo Centro", "empresa_direccion": "Av. Siempreviva 742",
        "empresa_cuit": "30712345679", "empresa_telefono": "", "empresa_email": "",
        "empresa_iibb": "", "empresa_iva_condition": "Responsable Inscripto",
        "empresa_inicio_actividades": "",
    })
    assert guardada.status_code == 200, guardada.text

    _configurar_mp(api, auto_facturar=True)

    empresa = api.get("/api/config/empresa").json()
    assert empresa["empresa_nombre"] == "Complejo Centro"
    assert empresa["empresa_iva_condition"] == "Responsable Inscripto"


def test_el_toggle_de_la_automatica_sobrevive_a_recargar_la_config(api):
    """`mp_auto_facturar_reservas` no está en los DEFAULTS de LibraCore: viaja
    como `extra_defaults`. Se verifica contra el `config.json` en disco —con un
    `load()` pelado— y no sólo contra el default en memoria."""
    _configurar_mp(api, auto_facturar=True)
    assert api.get("/config/mercadopago").json()["auto_facturar"] is True
    assert cobro_qr.auto_facturar_prendida() is True
    assert config_manager.load().get("mp_auto_facturar_reservas") is True
