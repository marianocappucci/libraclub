"""El gate de Términos, medido en ESTE producto.

🔴 **Por qué hace falta un test acá y no alcanza con el del motor.** El gate se
enciende con una sola línea del armado de la app de este repo
(`app.state.terminos = TerminosRepository(...)`). Si esa línea faltara, libraauth
no falla: `hay_terminos_pendientes` devuelve `False` y la instancia queda sin
gate, en silencio y con toda la suite en verde. Es un opt-in por ausencia, y la
única contramedida es medirlo del lado del consumidor.


Estos tests llevan la marca `sin_aceptar_terminos`, que los deja afuera de la
excepción autouse del `conftest`: son los únicos de la suite que ven el gate
puesto de verdad.
"""
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


@pytest.fixture
def logueado(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-terminos",
        libracore_database_url=base_de_libracore,
    )
    cliente = TestClient(crear_app(cfg), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


@pytest.mark.sin_aceptar_terminos
def test_una_llamada_gateada_corta_hasta_aceptar(logueado):
    respuesta = logueado.get("/api/usuarios")
    assert respuesta.status_code == 403
    assert respuesta.json()["detail"]["code"] == "terminos_pendientes"


@pytest.mark.sin_aceptar_terminos
def test_aceptar_destraba_la_instancia(logueado):
    estado = logueado.get("/terminos").json()
    assert estado["pendiente"] is True
    assert estado["puede_aceptar"] is True

    aceptada = logueado.post("/terminos/aceptar", json={"version": estado["version"]})
    assert aceptada.status_code == 200, aceptada.text
    assert aceptada.json()["pendiente"] is False

    assert logueado.get("/api/usuarios").status_code == 200


@pytest.mark.sin_aceptar_terminos
def test_el_camino_para_salir_del_gate_no_se_gatea_a_si_mismo(logueado):
    """El control que hace útil al primero: con la instancia frenada, lo que
    permite destrabarla tiene que seguir contestando 200. Sin esto, un gate que
    cortara TODO también pasaría el test de arriba — y dejaría la instancia sin
    salida."""
    assert logueado.get("/auth/me").status_code == 200
    assert logueado.get("/terminos").status_code == 200


@pytest.mark.sin_aceptar_terminos
def test_la_fila_probatoria_guarda_version_hash_y_quien(logueado):
    from libraauth.terminos import hash_vigente

    estado = logueado.get("/terminos").json()
    logueado.post("/terminos/aceptar", json={"version": estado["version"]})

    historial = logueado.get("/terminos/historial").json()
    assert len(historial) == 1
    assert historial[0]["version"] == estado["version"]
    assert historial[0]["hash_texto"] == hash_vigente()
