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


#: Las credenciales las sirve `libracore.mp_config_router` desde el 2026-08-30.
#: El endpoint propio que vivia aca devolvia el ACCESS TOKEN EN CLARO; el del
#: motor lo devuelve enmascarado. El prefijo es el mismo, y el interruptor se
#: sigue guardando en `mp_auto_facturar_reservas` --lo que se cobra con este QR
#: es un turno de cancha, no una venta-- gracias a `campo_auto_facturar`.
RUTA_MP = "/config/mercadopago"


def _configurar_mp(api, auto_facturar=False):
    r = api.put(RUTA_MP, json={
        "mp_access_token": "APP_USR-token-de-prueba",
        "mp_user_id": "123456789",
        "mp_pos_id": "CAJA01",
        "mp_webhook_secret": SECRETO_WEBHOOK,
        "mp_auto_facturar_ventas": auto_facturar,
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
    #
    # 🔴 Se afirma sobre `cobro_qr.esta_configurado()` y no sobre la respuesta
    # del endpoint: el router del motor no devuelve un `configurado`. Ese
    # calculo es del mostrador, y la pantalla lo repite del lado del cliente.
    # Preguntarle al servicio es preguntarle a quien de verdad decide.
    for faltante in ("mp_user_id", "mp_pos_id"):
        datos = {
            "mp_access_token": "APP_USR-x", "mp_user_id": "1", "mp_pos_id": "CAJA01",
            "mp_auto_facturar_ventas": False,
        }
        datos[faltante] = ""
        api.put(RUTA_MP, json=datos)
        assert cobro_qr.esta_configurado() is False, faltante

    # Control positivo: con los tres, sí. Sin esto, un `esta_configurado()` que
    # devolviera siempre False pasaría el test.
    api.put(RUTA_MP, json={
        "mp_access_token": "APP_USR-x", "mp_user_id": "1", "mp_pos_id": "CAJA01",
        "mp_auto_facturar_ventas": False,
    })
    assert cobro_qr.esta_configurado() is True


def test_el_token_vacio_NO_borra_el_que_estaba(api):
    """🔴 La pantalla muestra el token ENMASCARADO, no el token. Si mandar el
    campo vacio lo borrara, guardar el POS ID desconectaria la cuenta sin que
    nadie lo pidiera."""
    _configurar_mp(api)
    api.put(RUTA_MP, json={
        "mp_access_token": "", "mp_user_id": "123456789", "mp_pos_id": "CAJA02",
    })
    assert config_manager.load()["mp_access_token"] == "APP_USR-token-de-prueba"
    assert config_manager.load()["mp_pos_id"] == "CAJA02"


def test_el_secreto_del_webhook_vacio_tampoco(api):
    """Sin la firma el webhook del portal NO procesa nada: borrarla sin querer
    deja de confirmar todas las reservas pagadas, y nada lo avisa."""
    _configurar_mp(api)
    api.put(RUTA_MP, json={
        "mp_access_token": "", "mp_webhook_secret": "",
        "mp_user_id": "123456789", "mp_pos_id": "CAJA01",
    })
    assert config_manager.load()["mp_webhook_secret"] == SECRETO_WEBHOOK


def test_el_token_no_vuelve_en_claro_por_la_API(api):
    """El endpoint propio lo devolvia entero en el JSON de una pantalla."""
    _configurar_mp(api)
    visible = api.get(RUTA_MP).json()
    assert visible["mp_access_token"] != "APP_USR-token-de-prueba"
    assert visible["mp_access_token_cargado"] is True


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


def test_el_qr_cobra_LO_QUE_FALTA_cuando_ya_hubo_una_sena(
    api, sucursal, cancha, cliente, tarifa_base, abrir_caja, mp,
):
    """El defecto que esto arregla le cobraba el turno DOS VECES al cliente.

    Hasta el 2026-08-28 el QR ponia el total pelado. Un turno de $10.000 con
    $4.000 de sena en efectivo, cobrado despues por QR, ponia **$10.000** en el
    cartel: entraban $14.000 por un turno de $10.000 y el sobrante recien
    aparecia en el cierre, horas despues y sin saber de quien era.

    Y no era un caso raro: tomar sena y cobrar el saldo es el flujo normal de un
    complejo, y la pantalla del detalle ofrecia el boton igual.
    """
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")

    assert api.post(
        f"/api/reservas/{reserva['id']}/cobros",
        json={"monto": "4000", "medio_pago": "efectivo", "detalle": "Sena"},
    ).status_code == 201

    r = api.post(f"/api/reservas/{reserva['id']}/mp-qr")
    assert r.status_code == 201, r.text
    assert r.json()["monto"] == 6000.0, (
        "el QR tiene que cobrar los $6.000 que faltan, no los $10.000 del turno"
    )
    assert mp.ordenes[0]["total"] == 6000.0, (
        "y lo que se le pone al cartel de MercadoPago es ese mismo numero"
    )


def test_sin_nada_cobrado_el_qr_sigue_poniendo_el_total(
    api, sucursal, cancha, cliente, tarifa_base, abrir_caja, mp,
):
    """El control del caso normal, que es la mayoria.

    Sin esto, el test de arriba pasaria con un QR que pone cualquier numero mas
    chico que el total --- incluido uno roto que reste de mas.
    """
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")

    r = api.post(f"/api/reservas/{reserva['id']}/mp-qr")
    assert r.status_code == 201, r.text
    assert r.json()["monto"] == 10000.0
    assert mp.ordenes[0]["total"] == 10000.0


def test_un_turno_YA_COBRADO_no_se_pone_en_el_qr(
    api, sucursal, cancha, cliente, tarifa_base, abrir_caja, mp,
):
    """Poner cero en el cartel es cobrarle de nuevo a quien ya pago.

    El `CheckConstraint monto > 0` de la tabla lo frenaria igual, pero con un
    500 que no le dice nada al operador. Sale 409 --- el pedido esta bien
    formado; lo que no admite la operacion es el estado del turno.
    """
    _configurar_mp(api)
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")

    assert api.post(
        f"/api/reservas/{reserva['id']}/cobros",
        json={"monto": "10000", "medio_pago": "efectivo"},
    ).status_code == 201

    r = api.post(f"/api/reservas/{reserva['id']}/mp-qr")
    assert r.status_code == 409, r.text
    assert "cobrado" in r.text.lower()
    assert mp.ordenes == [], "no se le manda nada a MercadoPago"


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
    # 🔑 El nombre en la API es el de la familia --`mp_auto_facturar_ventas`,
    # porque la pantalla es una sola-- y el de la BASE es el de este producto.
    assert api.get(RUTA_MP).json()["mp_auto_facturar_ventas"] is True
    assert cobro_qr.auto_facturar_prendida() is True
    assert config_manager.load().get("mp_auto_facturar_reservas") is True


# -- El simulador, solo fuera de produccion --------------------------------
#
# Existe porque sin credenciales de MercadoPago NO SE PUEDE probar el circuito:
# `poner_en_el_qr` falla al llamar a `crear_orden_qr`, asi que no llega a existir
# el pago que despues habria que sellar. El portal ya tenia el suyo desde antes
# ---`POST /api/portal/pagos/{id}/simular`--- y este copia su criterio.


def test_en_produccion_el_simulador_NO_SE_CONSTRUYE():
    """🔴 El test que más importa de este archivo.

    El simulador acredita un cobro sin que haya entrado un peso: montado en la
    instancia de un complejo, cualquiera con la URL cierra turnos gratis. Lo que
    lo impide es que la **fábrica devuelve `None`** y el router no se monta — no
    un `if` adentro del handler, que mal escrito deja el endpoint existiendo.

    ⚠️ **Se mide la fábrica y no las rutas de la app.** La primera versión
    construía una app con `entorno="prod"` y miraba `app.routes`: el assert
    principal pasaba, pero **el control —que la ruta real siguiera estando—
    fallaba**, con un set de cinco rutas que eran las de FastAPI por defecto. O
    sea que la app que estaba mirando no era la que creía, y un assert sobre un
    objeto que no se entiende no mide nada. La fábrica es una función pura: se
    mide directo.
    """
    from app.routers.reservas import construir_router_de_simulacion_qr

    for entorno in ("prod", "produccion", "producción", "production", "PROD"):
        assert construir_router_de_simulacion_qr(entorno) is None, (
            f"con entorno={entorno!r} el simulador se construye: acredita "
            f"cobros que nadie pagó"
        )


def test_fuera_de_produccion_si_se_construye():
    """El otro lado del control.

    Sin esto, una fábrica que devolviera `None` **siempre** pasaría el test de
    arriba — y el simulador no existiría en ningún lado.
    """
    from app.routers.reservas import construir_router_de_simulacion_qr

    for entorno in ("dev", "development", "demo", "test", ""):
        router = construir_router_de_simulacion_qr(entorno)
        assert router is not None, f"con entorno={entorno!r} no se construye"
        rutas = [r.path for r in router.routes]
        assert "/api/reservas/{reserva_id}/mp-qr/simular" in rutas, rutas


def test_el_simulador_cobra_y_deja_el_movimiento_en_la_caja(
    api, sucursal, cancha, cliente, tarifa_base, abrir_caja,
):
    """El circuito completo, sin credenciales.

    Es lo que el humano no podia probar: sin MercadoPago cargado no hay forma de
    poner la orden ni de acreditarla.
    """
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")

    r = api.post(f"/api/reservas/{reserva['id']}/mp-qr/simular")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "aprobado"
    assert r.json()["simulado"] is True
    assert r.json()["monto"] == 10000.0

    # Y la plata esta en la caja del turno abierto, con el medio del QR.
    resumen = api.get("/api/caja/turnos/actual").json()["resumen"]
    assert resumen["pagos_por_medio"].get("mercadopago") == 10000.0, (
        f"la plata no entro a la caja: {resumen['pagos_por_medio']}"
    )
    # El turno queda sin pendiente: es lo que el operador va a ver.
    assert api.get(f"/api/reservas/{reserva['id']}/cobros").json()["pendiente"] == 0.0


def test_el_simulador_exige_caja_abierta(
    api, sucursal, cancha, cliente, tarifa_base,
):
    """Sin turno abierto la plata quedaria fuera del arqueo --- y el simulador
    no es excusa para saltear eso. Mismo 409 que el cobro real."""
    reserva = _reserva(api, cancha, cliente, precio="10000.00")
    r = api.post(f"/api/reservas/{reserva['id']}/mp-qr/simular")
    assert r.status_code == 409, r.text


def test_el_simulador_no_cobra_dos_veces(
    api, sucursal, cancha, cliente, tarifa_base, abrir_caja,
):
    """El indice `uq_pagos_reserva_aprobado` lo frena en la base, pero eso seria
    un 500. Sale 409, que es lo que le dice al operador que ya esta cobrado."""
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente, precio="10000.00")
    assert api.post(f"/api/reservas/{reserva['id']}/mp-qr/simular").status_code == 200
    segunda = api.post(f"/api/reservas/{reserva['id']}/mp-qr/simular")
    assert segunda.status_code == 409, segunda.text


# -- La sonda: como la pantalla de la Caja se entera ------------------------
#
# El boton de simular no puede aparecer en produccion, y la pantalla no tiene
# como saberlo mirando el bundle: es el MISMO bundle en dev y en produccion. Lo
# pregunta al servidor, y la respuesta es la existencia de la ruta.


def test_la_sonda_vive_adentro_del_router_del_simulador():
    """🔴 El punto entero del diseño, y por eso se asertan las DOS rutas juntas.

    La alternativa descartada era que `/api/reservas/mp/estado` devolviera un
    booleano calculado con el criterio de produccion. Eso son dos puertas al
    mismo cuarto: el dia que dejen de coincidir, la pantalla ofrece un boton que
    no existe, o lo esconde donde hace falta. Acá la sonda esta adentro del
    router, asi que no hay criterio que repetir --- y este test lo fija: si
    alguien la muda al router principal, la ruta de simular sigue estando pero
    la sonda ya no viaja con ella, y esto se pone rojo.
    """
    from app.routers.reservas import construir_router_de_simulacion_qr

    router = construir_router_de_simulacion_qr("dev")
    assert router is not None
    rutas = {r.path for r in router.routes}
    assert rutas == {
        "/api/reservas/mp-qr/simulacion",
        "/api/reservas/{reserva_id}/mp-qr/simular",
    }, rutas


def test_en_produccion_no_hay_sonda_que_preguntar():
    """El otro lado: si la fabrica devuelve None, no se monta ninguna de las dos.

    Sin este assert, un simulador que montara la sonda por fuera del `if`
    diria "se puede simular" en la instancia de un complejo.
    """
    from app.routers.reservas import construir_router_de_simulacion_qr

    assert construir_router_de_simulacion_qr("prod") is None


def test_la_sonda_contesta_en_la_app_de_dev(api):
    """Que la ruta exista en el router no prueba que la app la sirva.

    El montaje es un `if` aparte en `main.py`, y el prefijo del router podria no
    ser el que el frontend pide. Se mide sobre la app armada, con el cliente
    autenticado que usa el resto del archivo.
    """
    r = api.get("/api/reservas/mp-qr/simulacion")
    assert r.status_code == 200, r.text
    assert r.json() == {"disponible": True}


def test_la_sonda_no_se_come_la_ruta_del_turno(api, cancha, cliente, tarifa_base):
    """El control de la de arriba: `mp-qr` no es un `reserva_id`.

    `/api/reservas/mp-qr/simulacion` y `/api/reservas/{reserva_id}/cobros` tienen
    los dos tres segmentos. Si el convertidor de `reserva_id` no fuera `int`, una
    de las dos se comeria a la otra segun el orden de registro --- y el sintoma
    seria un 422 en la pantalla del turno, no en la sonda.
    """
    reserva = _reserva(api, cancha, cliente, precio="10000.00")
    r = api.get(f"/api/reservas/{reserva['id']}/cobros")
    assert r.status_code == 200, r.text


# -- El predicado de produccion, una sola definicion ------------------------


def test_los_dos_simuladores_miran_el_MISMO_predicado():
    """Hasta el 2026-08-29 la tupla de nombres estaba escrita literal en los dos
    archivos. Sumar un nombre en uno dejaba el otro abierto, en silencio.

    Se mide por comportamiento y no leyendo el fuente: se recorre la lista de
    nombres y se exige que los dos simuladores contesten igual. Un nombre nuevo
    en `NOMBRES_DE_PRODUCCION` queda cubierto solo.
    """
    from app.config import NOMBRES_DE_PRODUCCION, es_produccion
    from app.routers.portal import construir_router_de_simulacion
    from app.routers.reservas import construir_router_de_simulacion_qr

    nombres = [*NOMBRES_DE_PRODUCCION, "PROD", "Produccion", "dev", "demo", "test", ""]
    for nombre in nombres:
        esperado = es_produccion(nombre)
        assert (construir_router_de_simulacion(nombre) is None) is esperado, nombre
        assert (construir_router_de_simulacion_qr(nombre) is None) is esperado, nombre

    # El control: la lista tiene que traer casos de los dos lados, o el bucle
    # de arriba pasaria con un `es_produccion` que devuelve siempre lo mismo.
    assert any(es_produccion(n) for n in nombres)
    assert any(not es_produccion(n) for n in nombres)
