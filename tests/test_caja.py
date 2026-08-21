"""La caja por turno: abrir, cobrar, cerrar, y que el arqueo diga la verdad.

El motor es `libracore.db.turnos` y lo prueba LibraCore. Lo que se fija acá es lo
que decide este producto: que el mostrador abra **su** caja, que no se pueda
cobrar fuera de turno, que el esperado se calcule sobre `caja_movimientos` —y no
sobre la tabla `ventas`, que en este producto está vacía— y que nadie cierre la
caja de otro.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app

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


def test_abrir_la_caja_espeja_al_usuario_en_libracore(api):
    """🔴 El arreglo que hace falta porque las dos bases están al revés.

    `turnos_caja.usuario_id` tiene una FK a `usuarios` **de LibraCore**, y en
    este producto los usuarios viven del lado del dominio. Sin el espejo, abrir
    un turno falla con una violación de clave foránea — la FK se aplica de
    verdad en PostgreSQL, está verificado.
    """
    r = api.post("/api/caja/turnos", json={"monto_inicial": "5000"})
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "abierto"
    assert r.json()["monto_inicial"] == 5000.0


def test_no_se_abren_dos_cajas_a_la_vez(api):
    assert api.post("/api/caja/turnos", json={"monto_inicial": "0"}).status_code == 201
    assert api.post("/api/caja/turnos", json={"monto_inicial": "0"}).status_code == 409


def test_sin_turno_abierto_no_se_puede_cobrar(api):
    """🔑 Un cobro sin turno queda fuera de todo arqueo: plata que entró y que
    ningún cierre va a contar. Se corta con 409, no se acepta en silencio."""
    r = api.post("/api/caja/cobros", json={
        "monto": "1000", "concepto": "Seña", "medio_pago": "efectivo",
    })
    assert r.status_code == 409, r.text


def test_un_medio_de_pago_desconocido_no_entra(api):
    api.post("/api/caja/turnos", json={"monto_inicial": "0"})
    r = api.post("/api/caja/cobros", json={
        "monto": "1000", "concepto": "Seña", "medio_pago": "cheque",
    })
    assert r.status_code == 422, r.text


def test_el_arqueo_cuenta_el_efectivo_y_NO_lo_demas(api):
    """🔑 El esperado es lo que tiene que haber **en el cajón**.

    Una transferencia entró, pero no en efectivo: contarla en el esperado haría
    que toda caja con transferencias cierre con faltante. Lo que no es efectivo
    queda en el resumen de la terminal o del banco.
    """
    api.post("/api/caja/turnos", json={"monto_inicial": "1000"})
    api.post("/api/caja/cobros", json={
        "monto": "5000", "concepto": "Cancha 1", "medio_pago": "efectivo"})
    api.post("/api/caja/cobros", json={
        "monto": "9000", "concepto": "Cancha 2", "medio_pago": "transferencia"})

    turno = api.get("/api/caja/turnos/actual").json()["turno"]
    cierre = api.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                      json={"monto_declarado": "6000"})
    assert cierre.status_code == 200, cierre.text
    c = cierre.json()
    # 1000 de inicial + 5000 de efectivo. Los 9000 de transferencia NO entran.
    assert c["monto_esperado_cierre"] == 6000.0
    assert c["diferencia_de_caja"] == 0.0


def test_la_diferencia_se_guarda_y_no_se_corrige(api):
    """Un cierre que no cuadra es un dato: faltó plata, sobró, o alguien no
    cargó un cobro. Ajustarlo al esperado borraría lo que hay que mirar."""
    api.post("/api/caja/turnos", json={"monto_inicial": "1000"})
    api.post("/api/caja/cobros", json={
        "monto": "5000", "concepto": "Cancha 1", "medio_pago": "efectivo"})
    turno = api.get("/api/caja/turnos/actual").json()["turno"]
    c = api.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                 json={"monto_declarado": "5500"}).json()
    assert c["monto_esperado_cierre"] == 6000.0
    assert c["monto_declarado_cierre"] == 5500.0
    assert c["diferencia_de_caja"] == -500.0, "faltaron 500 y tiene que quedar escrito"


def test_un_turno_cerrado_no_se_cierra_de_nuevo(api):
    api.post("/api/caja/turnos", json={"monto_inicial": "0"})
    turno = api.get("/api/caja/turnos/actual").json()["turno"]
    assert api.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                    json={"monto_declarado": "0"}).status_code == 200
    assert api.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                    json={"monto_declarado": "0"}).status_code == 409


def test_nadie_cierra_la_caja_de_otro(api, engine):
    """🔴 Un operador cerrándole la caja a otro deja un arqueo con el nombre
    equivocado: el que contó la plata no es el que figura."""
    api.post("/api/caja/turnos", json={"monto_inicial": "1000"})
    turno = api.get("/api/caja/turnos/actual").json()["turno"]

    api.post("/api/usuarios", json={
        "username": "otro", "name": "Otro", "password": "clave-otro", "role": "staff"})
    otro = TestClient(crear_app(_config(_url_core())), base_url="https://testserver")
    assert otro.post(
        "/auth/login", json={"username": "otro", "password": "clave-otro"}
    ).status_code == 200

    assert otro.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                     json={"monto_declarado": "1000"}).status_code == 403
    # Control: el dueño sí puede.
    assert api.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                    json={"monto_declarado": "1000"}).status_code == 200


def test_el_historial_es_de_admin(api):
    api.post("/api/usuarios", json={
        "username": "mostrador2", "name": "Mostrador", "password": "clave-most", "role": "staff"})
    staff = TestClient(crear_app(_config(_url_core())), base_url="https://testserver")
    staff.post("/auth/login", json={"username": "mostrador2", "password": "clave-most"})
    assert staff.get("/api/caja/turnos").status_code == 403
    assert api.get("/api/caja/turnos").status_code == 200
