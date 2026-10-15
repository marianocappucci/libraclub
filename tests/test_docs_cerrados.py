"""El Swagger de LibraClub no se publica en producción (ADR-053 de libracore).

Medido el 2026-10-15: `/docs`, `/redoc` y `/openapi.json` daban 200 sin sesión en las instancias
reales y en la demo, con el mapa de todas las rutas. `app/main.py` llama ahora a
`libracore.docs_api.cerrar_docs_de_la_api(app)` justo después de crear la app: sólo `ENV=development`
(la marca de la suite y del compose de desarrollo) o `LIBRA_DOCS_API=1` a propósito los sirven.

El criterio y sus bordes tienen sus pruebas en libracore; acá se fija que **este** producto lo usa,
y se mide contra la app de verdad y sin sesión.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth

from app.config import Config
from app.main import crear_app

RUTAS = ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect")


@pytest.fixture
def produccion(monkeypatch):
    """Lo que tiene una instancia real. Va **después** de la fixture de la app: ésa fija `ENV=development` al armarla.

    Una instancia real tiene `LIBRA_ENTORNO=cliente`, y ni `ENV=development` ni el interruptor del Swagger."""
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("LIBRA_DOCS_API", raising=False)
    monkeypatch.setenv("LIBRA_ENTORNO", "cliente")


def _estados(c) -> dict:
    return {ruta: c.get(ruta).status_code for ruta in RUTAS}


@pytest.fixture
def app_real(engine, sesion, monkeypatch):
    """La app de verdad, sobre la base de la suite, y un cliente **sin sesión** (como un escáner)."""
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", "clave-de-prueba")
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    config = Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
    )
    yield TestClient(crear_app(config), base_url="https://testserver")
    AuthBase.metadata.drop_all(engine)


def test_en_produccion_el_swagger_da_404_sin_sesion(app_real, produccion):
    c = app_real
    assert _estados(c) == dict.fromkeys(RUTAS, 404)
    assert c.get("/openapi.json").json() == {"detail": "Not Found"}


def test_en_la_demo_tambien(app_real, produccion, monkeypatch):
    """Su esquema es el mismo que el de un cliente real y la demo es pública: cerrada igual."""
    monkeypatch.setenv("LIBRA_ENTORNO", "demo")
    assert _estados(app_real) == dict.fromkeys(RUTAS, 404)


def test_en_desarrollo_se_sigue_viendo(app_real, monkeypatch):
    """`ENV=development` lo fija la suite entera: el Swagger se ve y trae las rutas del producto."""
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("LIBRA_DOCS_API", raising=False)
    c = app_real
    esquema = c.get("/openapi.json")
    assert esquema.status_code == 200
    assert set(esquema.json()["paths"]) == set(c.app.openapi()["paths"]) and esquema.json()["paths"]
    assert c.get("/docs").status_code == 200 and c.get("/redoc").status_code == 200


def test_con_la_spa_montada_como_en_produccion_sigue_dando_404_y_no_el_index(app_real, produccion, tmp_path):
    """🔴 El catch-all de la SPA contesta `index.html` con 200 a lo que no existe: la guarda tiene que ganarle."""
    from libracore.spa import montar_spa

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>la SPA</html>")
    c = app_real
    montar_spa(c.app, tmp_path)
    assert _estados(c) == dict.fromkeys(RUTAS, 404)
    assert "la SPA" in c.get("/una-pantalla").text  # el control: la SPA sigue atendiendo lo suyo
