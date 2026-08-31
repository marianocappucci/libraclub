"""*Probar conexión* del correo, montado en este producto.

El router es del motor (`libracore.smtp_router`, v1.69.0) y ahí está probado a
fondo. Lo que se prueba acá es lo único que el motor no puede: que **este
producto lo monte**, detrás de su gate de admin, y con **su** resolver — el
mismo `app.smtp.smtp_config` que usa el envío de comprobantes.

🔴 Sin la línea de montaje el botón de la pantalla compartida da 404 y la
instancia no falla por eso: arranca perfecto y el cliente descubre que no puede
probar su correo. Es la misma clase de defecto silencioso que el gate de
términos, que también tiene su test en cada producto.
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
        database_url=os.environ["DATABASE_URL"],
        entorno="test",
        debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
        libracore_database_url=url_core,
    )


@pytest.fixture
def anonimo(engine, sesion, monkeypatch, base_de_libracore):
    """La misma app, sin loguearse.

    Las variables de admin van igual: sin ellas `libraauth` **no levanta la
    app** —es la guarda que impide una instancia sin contraseña de admin—, así
    que su ausencia haría fallar el arranque y no el gate, que es lo que este
    test mide.
    """
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(
        crear_app(_config(base_de_libracore)), base_url="https://testserver")
    yield cliente
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(
        crear_app(_config(base_de_libracore)), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


def test_probar_esta_montado(api):
    """Sin SMTP cargado contesta 400 y dice qué falta — pero contesta.

    🔑 Ese 400 es la prueba de que la ruta existe: sin el montaje sería 404 o
    405 y la instancia arrancaría igual.
    """
    r = api.post("/admin/smtp/probar")

    assert r.status_code == 400, r.text
    assert "Complet" in r.json()["detail"]


def test_una_ruta_inventada_al_lado_no_contesta(api):
    """El control del de arriba: distingue "está montado" de "cualquier cosa
    colgada de /admin/smtp contesta"."""
    assert api.post("/admin/smtp/inventado").status_code in (404, 405)


def test_probar_es_de_administrador(anonimo):
    """Abre una sesión SMTP con las credenciales del cliente: no es de
    cualquiera que esté logueado."""
    assert anonimo.post("/admin/smtp/probar").status_code in (401, 403)
