"""La devolución de una seña cobrada en el mostrador: un egreso real de caja.

Hasta el 2026-09-11 `cancelacion.py` lo **decía** —«la devolución se hace desde
la caja, no por API»— y no registraba nada: el pago seguía `aprobado`, la caja no
se movía, y la plata que se le devolvía al jugador salía del cajón como un
faltante sin explicación en el arqueo.

Estos tests corren el circuito entero contra las dos bases: el cobro por QR con
el simulador —que llama a las MISMAS funciones que el cobro real—, la
cancelación por la API del mostrador, y el movimiento leído **directo de
`caja_movimientos`**, no de un resumen que lo pudiera estar calculando por otro
lado.
"""

from __future__ import annotations

import os
from datetime import time

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from psycopg.rows import dict_row
from sqlalchemy import select

from app.config import Config
from app.main import crear_app
from app.models.enums import AlcanceDia
from app.models.maestros import FranjaDeAtencion
from app.models.reservas import CanalDePago, EstadoPago, PagoDeReserva
from tests.test_cancelacion import _en

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
    cliente = TestClient(
        crear_app(
            Config(
                database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
                directorio_de_datos="/tmp/libraclub-test-datos",
                libracore_database_url=base_de_libracore,
            )
        ),
        base_url="https://testserver",
    )
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def complejo(sesion, sucursal, tarifa_base):
    """Abierto las 24 h y devolviendo con 24 h de aviso: acá se prueba la caja,
    no el horario ni la política."""
    sesion.add(
        FranjaDeAtencion(
            sucursal_id=sucursal.id, alcance_dia=AlcanceDia.TODOS,
            abre=time(0, 0), cierra=time(0, 0),
        )
    )
    sucursal.horas_de_cancelacion = 24
    sesion.commit()
    return sucursal


def _cobrada_por_qr(api, sesion, cancha, cliente, *, en_horas=48) -> PagoDeReserva:
    """Un turno confirmado y cobrado por el QR del mostrador, con la caja abierta."""
    r = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": cliente.id,
        "comienza_at": _en(en_horas).isoformat(), "duracion_min": 90,
        "precio": "10000.00",
    })
    assert r.status_code == 201, r.text
    reserva_id = r.json()["id"]
    cobro = api.post(f"/api/reservas/{reserva_id}/mp-qr/simular")
    assert cobro.status_code == 200, cobro.text
    sesion.expire_all()
    pago = sesion.scalars(
        select(PagoDeReserva).where(PagoDeReserva.reserva_id == reserva_id)
    ).one()
    assert pago.canal is CanalDePago.MOSTRADOR
    assert pago.caja_movimiento_id is not None, "el control: la seña entró a la caja"
    return pago


def _cancelar(api, pago: PagoDeReserva) -> None:
    r = api.post(
        f"/api/reservas/{pago.reserva_id}/estado",
        json={"estado": "cancelada", "motivo": "Avisó por teléfono"},
    )
    assert r.status_code == 200, r.text


def _movimientos(url_core: str) -> list[dict]:
    with psycopg.connect(url_core) as c:
        c.row_factory = dict_row
        return c.execute(
            "SELECT id, tipo, monto, referencia, medio_pago, turno_id, anulado"
            " FROM caja_movimientos ORDER BY id"
        ).fetchall()


def _egresos(url_core: str) -> list[dict]:
    return [m for m in _movimientos(url_core) if m["tipo"] == "egreso"]


def _recargado(sesion, pago: PagoDeReserva) -> PagoDeReserva:
    sesion.expire_all()
    return sesion.get(PagoDeReserva, pago.id)


# ── El camino feliz ──────────────────────────────────────────────────────


def test_a_tiempo_la_sena_sale_de_la_caja_como_egreso_atado_al_pago(
    api, sesion, cancha, cliente, complejo, abrir_caja, base_de_libracore
):
    abrir_caja(api, complejo)
    pago = _cobrada_por_qr(api, sesion, cancha, cliente)
    turno_id = api.get("/api/caja/turnos/actual").json()["turno"]["id"]

    _cancelar(api, pago)

    guardado = _recargado(sesion, pago)
    assert guardado.estado is EstadoPago.DEVUELTO
    assert guardado.devuelto_at is not None
    assert guardado.detalle_devolucion is None

    egresos = _egresos(base_de_libracore)
    assert len(egresos) == 1, egresos
    egreso = egresos[0]
    # 🔑 Atado al pago por la referencia, que es única por pago: es lo que lo
    # hace encontrable desde la reserva y lo que impide registrarlo dos veces.
    assert egreso["referencia"] == f"devolucion-{pago.referencia}"
    assert float(egreso["monto"]) == float(pago.monto)
    assert egreso["medio_pago"] == "efectivo"
    assert egreso["turno_id"] == turno_id, "tiene que caer en el turno ABIERTO"

    # 🔴 No se borra nada: el ingreso del cobro sigue ahí, vivo. El arqueo cuenta
    # los dos —entró y salió— y no un agujero.
    ingreso = [m for m in _movimientos(base_de_libracore) if m["tipo"] == "ingreso"]
    assert [m["id"] for m in ingreso] == [pago.caja_movimiento_id]
    assert ingreso[0]["anulado"] == 0


def test_el_arqueo_del_turno_ve_la_devolucion(
    api, sesion, cancha, cliente, complejo, abrir_caja
):
    """El efectivo esperado baja lo que salió del cajón: sin esto, el cierre da
    un faltante del tamaño de la seña y nadie sabe por qué."""
    abrir_caja(api, complejo)
    pago = _cobrada_por_qr(api, sesion, cancha, cliente)
    antes = api.get("/api/caja/turnos/actual").json()["resumen"]["pagos_por_medio"]

    _cancelar(api, pago)

    despues = api.get("/api/caja/turnos/actual").json()["resumen"]["pagos_por_medio"]
    assert despues.get("efectivo", 0) == antes.get("efectivo", 0) - float(pago.monto)
    # El bucket del QR no se toca: es lo que se concilia contra MercadoPago.
    assert despues.get("mercadopago") == antes.get("mercadopago")


# ── Cuando no corresponde, o no se puede ─────────────────────────────────


def test_tarde_no_sale_nada_de_la_caja(
    api, sesion, cancha, cliente, complejo, abrir_caja, base_de_libracore
):
    abrir_caja(api, complejo)
    pago = _cobrada_por_qr(api, sesion, cancha, cliente, en_horas=3)

    _cancelar(api, pago)

    assert _recargado(sesion, pago).estado is EstadoPago.APROBADO
    assert _egresos(base_de_libracore) == []


def test_sin_turno_abierto_queda_pendiente_y_no_se_inventa_nada(
    api, sesion, cancha, cliente, complejo, abrir_caja, base_de_libracore
):
    """🔴 Sin caja abierta la devolución no tiene de dónde salir.

    Mismo criterio que MercadoPago sin credenciales: el turno se cancela igual,
    la deuda queda anotada con el motivo y aparece en la lista de pendientes.
    """
    abrir_caja(api, complejo)
    pago = _cobrada_por_qr(api, sesion, cancha, cliente)
    turno_id = api.get("/api/caja/turnos/actual").json()["turno"]["id"]
    cierre = api.post(f"/api/caja/turnos/{turno_id}/cerrar", json={"monto_declarado": "0"})
    assert cierre.status_code == 200, cierre.text

    _cancelar(api, pago)

    guardado = _recargado(sesion, pago)
    assert guardado.estado is EstadoPago.DEVOLUCION_PENDIENTE
    assert "turno de caja abierto" in (guardado.detalle_devolucion or "")
    assert _egresos(base_de_libracore) == []
    pendientes = api.get("/api/devoluciones").json()
    assert [p["id"] for p in pendientes] == [pago.id]


def test_el_reintento_con_la_caja_abierta_la_completa(
    api, sesion, cancha, cliente, complejo, abrir_caja, base_de_libracore
):
    abrir_caja(api, complejo)
    pago = _cobrada_por_qr(api, sesion, cancha, cliente)
    turno_id = api.get("/api/caja/turnos/actual").json()["turno"]["id"]
    api.post(f"/api/caja/turnos/{turno_id}/cerrar", json={"monto_declarado": "0"})
    _cancelar(api, pago)
    assert _recargado(sesion, pago).estado is EstadoPago.DEVOLUCION_PENDIENTE

    abrir_caja(api, complejo)
    nuevo_turno = api.get("/api/caja/turnos/actual").json()["turno"]["id"]
    r = api.post(f"/api/devoluciones/{pago.id}/reintentar")

    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "devuelto"
    assert _recargado(sesion, pago).estado is EstadoPago.DEVUELTO
    egresos = _egresos(base_de_libracore)
    assert len(egresos) == 1
    assert egresos[0]["turno_id"] == nuevo_turno, "sale del turno abierto HOY, no del cerrado"


def test_reintentar_no_saca_la_plata_dos_veces(
    api, sesion, cancha, cliente, complejo, abrir_caja, base_de_libracore
):
    """🔑 El egreso y el estado del pago viven en DOS bases.

    El movimiento se escribe en la de LibraCore, que commitea sola; el
    `DEVUELTO` en la del dominio, al final del request. Si el segundo commit se
    pierde, el pago queda pendiente con el egreso ya hecho — y el reintento no
    puede sacar la plata otra vez. Se simula exactamente eso: egreso hecho, pago
    devuelto a pendiente a mano.
    """
    abrir_caja(api, complejo)
    pago = _cobrada_por_qr(api, sesion, cancha, cliente)
    _cancelar(api, pago)
    assert len(_egresos(base_de_libracore)) == 1, "el control: el primer egreso salió"

    guardado = _recargado(sesion, pago)
    guardado.estado = EstadoPago.DEVOLUCION_PENDIENTE
    guardado.devuelto_at = None
    sesion.commit()

    r = api.post(f"/api/devoluciones/{pago.id}/reintentar")

    assert r.status_code == 200, r.text
    assert _recargado(sesion, pago).estado is EstadoPago.DEVUELTO
    assert len(_egresos(base_de_libracore)) == 1, "la seña salió del cajón UNA vez"
