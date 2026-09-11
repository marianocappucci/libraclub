"""Ausentismo: contar y avisar, sin bloquear.

La regla —3 ausencias en 90 días— tiene su borde medido de los dos lados: sin el
test del día 91, `>=` contra `>` en la ventana pasa igual, y sin el de las dos
ausencias un umbral corrido a 2 también.

Todo lo que es ventana se mide con un `momento` explícito. Los dos tests de API
usan la hora real porque el endpoint no recibe `momento`, y por eso sus turnos se
calculan **desde `ahora()`** y no desde una fecha fija: una fecha fija sale de la
ventana de 90 días sola, el día que el calendario la pasa.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app
from app.models.enums import EstadoReserva
from app.servicios import ausentismo as servicio
from app.servicios import reservas as servicio_reservas
from app.tiempo import TZ, a_local, ahora

USUARIO, CLAVE = "admin", "clave-de-prueba"

#: El reloj de los tests de servicio. Fijo, como `CUANDO` de `test_avisos.py`.
MOMENTO = datetime(2026, 9, 10, 12, 0, tzinfo=TZ)


def _a_las_20(dia: datetime) -> datetime:
    """Ese día a las 20:00 locales: adentro del horario por defecto y sin que dos
    turnos de días distintos se pisen en la misma cancha."""
    return a_local(dia).replace(hour=20, minute=0, second=0, microsecond=0)


def _turno(sesion, cancha, cliente, cuando, estado=EstadoReserva.AUSENTE):
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=cuando
    )
    sesion.commit()
    if estado is not EstadoReserva.CONFIRMADA:
        servicio_reservas.cambiar_estado(sesion, reserva.id, estado)
        sesion.commit()
    return reserva


def _ausente_hace(sesion, cancha, cliente, dias: int, desde: datetime = MOMENTO):
    return _turno(sesion, cancha, cliente, _a_las_20(desde - timedelta(days=dias)))


# ── La regla ─────────────────────────────────────────────────────────────


def test_tres_ausencias_en_la_ventana_lo_marcan_con_la_ultima(
    sesion, cancha, cliente, tarifa_base
):
    for dias in (40, 10, 25):
        _ausente_hace(sesion, cancha, cliente, dias)

    resultado = servicio.de_clientes(sesion, momento=MOMENTO)[cliente.id]

    assert resultado.ausentes == 3
    assert resultado.reincidente is True
    # La última es la MÁS RECIENTE, no la última cargada: se cargaron fuera de
    # orden a propósito.
    assert resultado.ultimo == _a_las_20(MOMENTO - timedelta(days=10))


def test_dos_ausencias_no_alcanzan(sesion, cancha, cliente, tarifa_base):
    """El control del umbral: se cuentan, pero no avisan."""
    for dias in (5, 6):
        _ausente_hace(sesion, cancha, cliente, dias)

    resultado = servicio.de_clientes(sesion, momento=MOMENTO)[cliente.id]

    assert resultado.ausentes == 2
    assert resultado.reincidente is False
    assert servicio.reincidentes(sesion, momento=MOMENTO) == []


def test_la_que_quedo_afuera_de_los_90_dias_no_cuenta(
    sesion, cancha, cliente, tarifa_base
):
    """🔑 Exactamente el borde, de los dos lados.

    El turno de hace 90 días justos cuenta y el de 91 no. Sin los dos, correr la
    ventana un día para cualquier lado pasa inadvertido.
    """
    _ausente_hace(sesion, cancha, cliente, 3)
    _ausente_hace(sesion, cancha, cliente, 4)
    # Hace 91 días a las 20:00: afuera.
    _ausente_hace(sesion, cancha, cliente, 91)

    assert servicio.de_clientes(sesion, momento=MOMENTO)[cliente.id].ausentes == 2

    # Y el turno de las 20:00 de hace 90 días entra si el reloj está a esa hora.
    en_el_borde = _a_las_20(MOMENTO - timedelta(days=90))
    _turno(sesion, cancha, cliente, en_el_borde)
    momento = en_el_borde + servicio.VENTANA

    assert servicio.de_clientes(sesion, momento=momento)[cliente.id].ausentes == 3


def test_solo_cuentan_las_ausencias(sesion, cancha, cliente, tarifa_base):
    """Jugar, cancelar o seguir confirmado no es faltar."""
    _ausente_hace(sesion, cancha, cliente, 1)
    _turno(sesion, cancha, cliente, _a_las_20(MOMENTO - timedelta(days=2)),
           estado=EstadoReserva.JUGADA)
    _turno(sesion, cancha, cliente, _a_las_20(MOMENTO - timedelta(days=3)),
           estado=EstadoReserva.CANCELADA)
    _turno(sesion, cancha, cliente, _a_las_20(MOMENTO - timedelta(days=4)),
           estado=EstadoReserva.CONFIRMADA)

    assert servicio.de_clientes(sesion, momento=MOMENTO)[cliente.id].ausentes == 1


def test_las_ausencias_de_otro_no_se_suman(sesion, cancha, cliente, tarifa_base):
    from app.models.maestros import Cliente

    otro = Cliente(nombre="Otro")
    sesion.add(otro)
    sesion.commit()
    for dias in (1, 2, 3):
        _ausente_hace(sesion, cancha, otro, dias)
    _ausente_hace(sesion, cancha, cliente, 4)

    resultado = servicio.de_clientes(sesion, momento=MOMENTO)

    assert resultado[otro.id].ausentes == 3
    assert resultado[cliente.id].ausentes == 1
    assert [a.cliente_id for a in servicio.reincidentes(sesion, momento=MOMENTO)] == [otro.id]


# ── Lo que ve el mostrador ───────────────────────────────────────────────


def _config() -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos", libracore_database_url=None,
    )


@pytest.fixture
def api(engine, sesion, monkeypatch):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(crear_app(_config()), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


def test_la_api_trae_al_reincidente_con_la_regla(api, sesion, cancha, cliente, tarifa_base):
    ahora_ = ahora()
    for dias in (1, 2, 3):
        _ausente_hace(sesion, cancha, cliente, dias, desde=ahora_)

    r = api.get("/api/clientes/ausentismo/reincidentes")

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    # La regla viaja con la respuesta: la pantalla la dice, no la decide.
    assert cuerpo["umbral"] == servicio.UMBRAL == 3
    assert cuerpo["dias"] == servicio.VENTANA.days == 90
    assert len(cuerpo["reincidentes"]) == 1
    fila = cuerpo["reincidentes"][0]
    assert fila["cliente_id"] == cliente.id
    assert fila["ausentes"] == 3
    ultimo = datetime.fromisoformat(fila["ultimo_ausente_at"])
    assert ultimo == _a_las_20(ahora_ - timedelta(days=1))


def test_al_reincidente_se_le_reserva_igual(api, sesion, cancha, cliente, tarifa_base):
    """🔴 Contar y avisar, **sin bloquear**. Decisión del humano.

    Si alguien agregara un chequeo de ausentismo en el alta, este test se pone
    rojo: el reincidente tiene que poder reservar desde el mostrador igual que
    cualquiera.
    """
    ahora_ = ahora()
    for dias in (1, 2, 3):
        _ausente_hace(sesion, cancha, cliente, dias, desde=ahora_)
    assert servicio.de_clientes(sesion)[cliente.id].reincidente, "el control: sí es reincidente"

    turno = _a_las_20(ahora_ + timedelta(days=2))
    r = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": cliente.id,
        "comienza_at": turno.isoformat(), "duracion_min": 90,
    })

    assert r.status_code == 201, r.text
