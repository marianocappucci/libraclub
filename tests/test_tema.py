"""El tema de la suite en esta instancia (libracore ADR-012, libra-ui ADR-007/008): `GET /api/tema`
público y `PUT /api/tema` del admin o del token de servicio del backoffice.

🔴 El caso que importa para el backoffice es el del token: `require_admin` a secas NO lo acepta (sólo
`require_admin_o_servicio`), y sin esto la pantalla «Apariencia» no podría empujar nada.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"
TOKEN = "token-de-servicio-de-prueba-no-es-real"
CABECERA = "X-Internal-Auth"

TEMA = {"menuActivoFondo": "#FDF2F8", "menuActivoBorde": "#F9A8D4"}
NORMALIZADO = {"menuActivoFondo": "#fdf2f8", "menuActivoBorde": "#f9a8d4"}


@pytest.fixture
def app_con_token(engine, sesion, monkeypatch, tmp_path):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    monkeypatch.setenv("LIBRA_SERVICE_TOKEN", TOKEN)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    config = Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False, directorio_de_datos=str(tmp_path),
    )
    yield crear_app(config)
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def anonimo(app_con_token):
    return TestClient(app_con_token, base_url="https://testserver")


@pytest.fixture
def admin(app_con_token):
    cliente = TestClient(app_con_token, base_url="https://testserver")
    assert cliente.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    return cliente


@pytest.fixture
def panel(app_con_token):
    """Sin sesión, con el token de servicio: es como llega el backoffice."""
    cliente = TestClient(app_con_token, base_url="https://testserver")
    cliente.headers[CABECERA] = TOKEN
    return cliente


def test_la_lectura_es_publica_y_arranca_vacia(anonimo):
    r = anonimo.get("/api/tema")
    assert r.status_code == 200
    assert r.json() == {"tema": {}}
    assert r.headers["cache-control"] == "no-cache"


def test_el_admin_guarda_y_cualquiera_lo_lee_sin_sesion(admin, anonimo):
    r = admin.put("/api/tema", json={"tema": TEMA})
    assert r.status_code == 200, r.text
    assert r.json() == {"tema": NORMALIZADO}
    assert anonimo.get("/api/tema").json() == {"tema": NORMALIZADO}


def test_un_tema_vacio_restaura_los_valores_por_defecto(admin):
    admin.put("/api/tema", json={"tema": TEMA})
    assert admin.put("/api/tema", json={"tema": {}}).status_code == 200
    assert admin.get("/api/tema").json() == {"tema": {}}


def test_sin_sesion_ni_token_no_escribe(anonimo):
    assert anonimo.put("/api/tema", json={"tema": TEMA}).status_code == 401


def test_el_token_de_servicio_del_backoffice_escribe_el_tema(panel, anonimo):
    r = panel.put("/api/tema", json={"tema": TEMA})
    assert r.status_code == 200, r.text
    assert anonimo.get("/api/tema").json() == {"tema": NORMALIZADO}


def test_un_token_equivocado_no_escribe(anonimo):
    r = anonimo.put("/api/tema", json={"tema": TEMA}, headers={CABECERA: "otro"})
    assert r.status_code == 401


def test_lo_que_no_tiene_la_forma_de_un_color_es_422(admin):
    assert admin.put("/api/tema", json={"tema": {"menuActivoFondo": "verde"}}).status_code == 422
    assert admin.get("/api/tema").json() == {"tema": {}}
