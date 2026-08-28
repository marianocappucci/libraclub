"""El módulo de caja: mostradores por sucursal, egresos y anulación.

Lo pidió el humano el 2026-08-28, midiéndolo contra Contalibra: *"que tenga los
turnos de caja adentro y gestionar más de una caja"*. Y decidió que **la caja
pertenece a una sucursal y una sede puede tener más de una**.

🔴 **Lo que este módulo arregla no es cosmético.** Antes de esto el arqueo sólo
podía subir —no había forma de registrar plata que sale— y el turno no sabía en
qué sede estaba, así que ningún reporte por sucursal era posible.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app
from app.models.maestros import Sucursal

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
        crear_app(Config(
            database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
            directorio_de_datos="/tmp/libraclub-test-datos",
            libracore_database_url=base_de_libracore,
        )),
        base_url="https://testserver",
    )
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


# ── Los mostradores ───────────────────────────────────────────────────────


def test_una_sede_puede_tener_mas_de_una_caja(api, sucursal):
    """La decisión del humano: el mostrador y el buffet son dos cajones."""
    for nombre in ("Mostrador", "Buffet"):
        r = api.post("/api/cajas", json={"nombre": nombre, "sucursal_id": sucursal.id})
        assert r.status_code == 201, r.text

    listado = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()
    assert {c["nombre"] for c in listado} == {"Mostrador", "Buffet"}


def test_las_cajas_de_una_sede_NO_aparecen_en_la_otra(api, sucursal, sesion):
    """🔴 El aislamiento por sede, que es todo el punto.

    Si el listado no filtrara, el mostrador de una sucursal podría abrir su turno
    sobre el cajón de la otra — y su arqueo saldría contra plata que no tocó.
    """
    otra = Sucursal(nombre="Complejo Norte")
    sesion.add(otra)
    sesion.commit()

    api.post("/api/cajas", json={"nombre": "Mostrador centro", "sucursal_id": sucursal.id})
    api.post("/api/cajas", json={"nombre": "Mostrador norte", "sucursal_id": otra.id})

    del_centro = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()
    assert [c["nombre"] for c in del_centro] == ["Mostrador centro"]
    # El control por el otro lado: la otra sede ve la suya y sólo la suya.
    del_norte = api.get(f"/api/cajas?sucursal_id={otra.id}").json()
    assert [c["nombre"] for c in del_norte] == ["Mostrador norte"]


def test_no_se_da_de_alta_una_caja_en_una_sucursal_que_no_existe(api):
    r = api.post("/api/cajas", json={"nombre": "Fantasma", "sucursal_id": 9999})
    assert r.status_code == 404, r.text


def test_un_medio_que_este_producto_no_cobra_se_rechaza(api, sucursal):
    """🔑 Los medios se validan contra los de ESTE producto, no contra el
    vocabulario del motor: un complejo no cobra con cheque, y ofrecerlo para que
    después el cobro conteste 422 es peor que no ofrecerlo."""
    r = api.post("/api/cajas", json={
        "nombre": "Mostrador", "sucursal_id": sucursal.id, "medios_pago": ["cheque"],
    })
    assert r.status_code == 422, r.text


def test_una_caja_con_movimientos_no_se_borra(api, sucursal, abrir_caja):
    """Borrarla dejaría arqueos apuntando a nada."""
    assert abrir_caja(api, sucursal, "0").status_code == 201
    caja = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()[0]
    api.post("/api/caja/cobros", json={
        "monto": "1000", "concepto": "Turno", "medio_pago": "efectivo",
    })

    r = api.delete(f"/api/cajas/{caja['id']}")
    assert r.status_code == 422, r.text
    assert "movimientos" in r.text


# ── El turno, sobre un mostrador ──────────────────────────────────────────


def test_el_turno_se_abre_sobre_la_caja_elegida(api, sucursal, abrir_caja):
    assert abrir_caja(api, sucursal, "5000").status_code == 201
    caja = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()[0]

    actual = api.get("/api/caja/turnos/actual").json()
    assert actual["turno"]["caja_id"] == caja["id"]
    assert actual["turno"]["caja_nombre"] == caja["nombre"]


def test_no_se_abre_el_turno_sobre_una_caja_que_no_existe(api, sucursal):
    r = api.post("/api/caja/turnos", json={"monto_inicial": "0", "caja_id": 9999})
    assert r.status_code == 404, r.text


def test_no_se_abre_el_turno_sobre_una_caja_dada_de_baja(api, sucursal):
    caja = api.post("/api/cajas", json={
        "nombre": "Vieja", "sucursal_id": sucursal.id,
    }).json()
    api.put(f"/api/cajas/{caja['id']}", json={"nombre": "Vieja", "activo": False})

    r = api.post("/api/caja/turnos", json={"monto_inicial": "0", "caja_id": caja["id"]})
    assert r.status_code == 422, r.text


# ── Los egresos ───────────────────────────────────────────────────────────


def test_un_egreso_BAJA_el_esperado_del_cajon(api, sucursal, abrir_caja):
    """🔴 Antes de esto el arqueo sólo podía subir.

    Sacar plata dejaba el cierre con un faltante sin explicación, indistinguible
    de un error de conteo o de un robo.
    """
    abrir_caja(api, sucursal, "10000")
    api.post("/api/caja/cobros", json={
        "monto": "5000", "concepto": "Turno", "medio_pago": "efectivo",
    })

    r = api.post("/api/caja/egresos", json={
        "monto": "3000", "motivo": "Retiro a banco", "medio_pago": "efectivo",
    })
    assert r.status_code == 200, r.text

    # 5000 que entraron menos 3000 que salieron.
    assert r.json()["efectivo_ventas"] == 2000.0


def test_el_motivo_del_egreso_sale_de_una_lista_cerrada(api, sucursal, abrir_caja):
    """Un motivo libre convierte el arqueo en algo que no se puede sumar por
    categoría, y «varios» termina siendo la mitad de los egresos."""
    abrir_caja(api, sucursal, "0")
    r = api.post("/api/caja/egresos", json={
        "monto": "100", "motivo": "porque sí", "medio_pago": "efectivo",
    })
    assert r.status_code == 422, r.text

    # El control: uno de la lista sí entra.
    motivos = api.get("/api/caja/motivos-de-egreso").json()
    assert motivos, "la lista de motivos llegó vacía"
    ok = api.post("/api/caja/egresos", json={
        "monto": "100", "motivo": motivos[0], "medio_pago": "efectivo",
    })
    assert ok.status_code == 200, ok.text


def test_sin_caja_abierta_no_se_registra_un_egreso(api, sucursal):
    """Igual que el cobro: quedaría fuera de todo arqueo."""
    r = api.post("/api/caja/egresos", json={
        "monto": "100", "motivo": "Retiro a banco", "medio_pago": "efectivo",
    })
    assert r.status_code == 409, r.text


# ── Anular un movimiento ──────────────────────────────────────────────────


def test_se_anula_un_movimiento_del_turno_abierto(api, sucursal, abrir_caja):
    """El caso real: el monto tipeado mal hace treinta segundos.

    ⚠️ **Este test asertaba `movimientos == []`** —o sea, que la fila
    desapareciera— hasta el 2026-08-28. Cambió porque cambió la conducta: ahora
    se **anula** y la fila queda. No es un test que se ablandó para que pase; es
    el que fija la semántica nueva, y por eso pide las dos cosas: que siga en la
    lista **y** que salga del arqueo.
    """
    abrir_caja(api, sucursal, "0")
    api.post("/api/caja/cobros", json={
        "monto": "99999", "concepto": "Mal tipeado", "medio_pago": "efectivo",
    })
    resumen = api.get("/api/caja/turnos/actual").json()["resumen"]
    assert len(resumen["movimientos"]) == 1
    assert resumen["pagos_por_medio"]["efectivo"] == 99999, "el control del total"
    mid = resumen["movimientos"][0]["id"]

    r = api.delete(f"/api/caja/movimientos/{mid}")
    assert r.status_code == 200, r.text
    assert len(r.json()["movimientos"]) == 1, "la fila queda"
    assert r.json()["movimientos"][0]["anulado"] == 1
    assert r.json()["pagos_por_medio"].get("efectivo", 0) == 0, "y sale del arqueo"
    assert r.json()["efectivo_ventas"] == 0.0


def test_no_se_anula_un_movimiento_que_no_es_del_turno_abierto(api, sucursal, abrir_caja):
    """🔴 Un arqueo cerrado es un hecho: esa diferencia la firmó alguien."""
    abrir_caja(api, sucursal, "0")
    api.post("/api/caja/cobros", json={
        "monto": "1000", "concepto": "Turno", "medio_pago": "efectivo",
    })
    mid = api.get("/api/caja/turnos/actual").json()["resumen"]["movimientos"][0]["id"]
    turno = api.get("/api/caja/turnos/actual").json()["turno"]
    api.post(f"/api/caja/turnos/{turno['id']}/cerrar", json={"monto_declarado": "1000"})

    # Turno nuevo: el movimiento de antes ya no es de éste.
    abrir_caja(api, sucursal, "0")
    r = api.delete(f"/api/caja/movimientos/{mid}")
    assert r.status_code == 404, r.text


# -- Anular no borra -------------------------------------------------------
#
# Pedido del humano el 2026-08-28: *"no deberian poder borrarse, tienen que
# quedar registrados"*. Los tests de lo que esto protege del lado de las
# reservas ---el pendiente que vuelve, y que las dos pantallas coincidan---
# estan en `test_cobro_del_turno.py`, donde viven los helpers de reserva.
