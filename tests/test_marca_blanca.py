"""La marca blanca esta cableada: la instancia puede tener nombre, color y logo del revendedor (libracore ADR-092).

Lo que se mide aca es el **cableado** del producto, no el motor: que las rutas esten montadas, que escribir las gatee el
rol del producto (admin o token de servicio del backoffice) y que el mail de recuperacion salga con el nombre de la
marca. El comportamiento lo prueba `libracore`.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from libracore import config_manager

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"
TOKEN = "token-de-servicio-de-prueba-no-es-real"
CABECERA = "X-Internal-Auth"
MARCA = {"nombre": "Club Modelo", "nombre_corto": "Modelo", "color": "#c0392b"}


@pytest.fixture(autouse=True)
def _marca_propia_del_test(tmp_path, monkeypatch):
    """La marca vive en el `config.json` y el volumen de la instancia: cada test usa los suyos."""
    monkeypatch.setattr(config_manager, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(config_manager, "MARCA_DIR", str(tmp_path / "marca"))


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
    app = crear_app(config)
    app.state.users.create(username="encargado", name="Encargado", password=CLAVE, role="staff")
    yield app
    AuthBase.metadata.drop_all(engine)


def _cliente(app) -> TestClient:
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def anonimo(app_con_token):
    return _cliente(app_con_token)


def _logueado(app, usuario) -> TestClient:
    c = _cliente(app)
    assert c.post("/auth/login", json={"username": usuario, "password": CLAVE}).status_code == 200
    return c


@pytest.fixture
def admin(app_con_token):
    return _logueado(app_con_token, USUARIO)


@pytest.fixture
def staff(app_con_token):
    return _logueado(app_con_token, "encargado")


@pytest.fixture
def panel(app_con_token):
    """Sin sesion, con el token de servicio: es como llega el backoffice."""
    c = _cliente(app_con_token)
    c.headers[CABECERA] = TOKEN
    return c


def test_sin_marca_la_instancia_es_la_del_producto(anonimo):
    r = anonimo.get("/api/marca")
    assert r.status_code == 200
    assert r.json()["propia"] is False
    assert r.json()["terminos_propios"] is False


def test_el_admin_carga_la_marca_y_cualquiera_la_lee(admin, anonimo):
    assert admin.put("/api/marca", json=MARCA).status_code == 200
    leida = anonimo.get("/api/marca").json()  # sin sesion: el login tambien lleva la marca
    assert leida["propia"] is True
    assert leida["nombre"] == "Club Modelo"
    assert leida["color"] == "#c0392b"


@pytest.mark.parametrize("metodo", ["put", "delete"])
def test_sin_sesion_no_se_escribe_la_marca(anonimo, metodo):
    r = anonimo.request(metodo, "/api/marca", json=MARCA if metodo == "put" else None)
    assert r.status_code in (401, 403)


def test_el_encargado_no_escribe_la_marca(staff):
    assert staff.put("/api/marca", json=MARCA).status_code == 403


def test_sin_sesion_no_se_escriben_los_terminos_propios(anonimo):
    r = anonimo.put("/api/marca/terminos", json={"version": "r-1.0", "vigente_desde": "01-01-2026", "texto": "x"})
    assert r.status_code in (401, 403)


def test_el_token_de_servicio_del_backoffice_escribe_la_marca(panel, anonimo):
    r = panel.put("/api/marca", json=MARCA)
    assert r.status_code == 200, r.text
    assert anonimo.get("/api/marca").json()["nombre"] == "Club Modelo"


def test_un_token_equivocado_no_escribe_la_marca(anonimo):
    assert anonimo.put("/api/marca", json=MARCA, headers={CABECERA: "otro"}).status_code == 401


def test_el_manifest_es_el_de_la_marca_y_no_el_index_de_la_spa(admin, anonimo):
    admin.put("/api/marca", json=MARCA)
    r = anonimo.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    assert r.json()["name"] == "Club Modelo"


def test_el_mail_de_recuperacion_sale_con_el_nombre_de_la_marca(app_con_token, admin):
    reset = app_con_token.state.password_reset
    assert reset.product_name == "LibraClub"
    admin.put("/api/marca", json=MARCA)
    assert reset.product_name == "Club Modelo"
    admin.delete("/api/marca")
    assert reset.product_name == "LibraClub"


def test_el_manifest_le_gana_al_catch_all_de_la_spa(app_con_token, monkeypatch, tmp_path):
    """🔴 Con un build, `app/asgi.py` contesta `index.html` a cualquier ruta que no conozca. Si la marca se montara
    despues, el navegador leeria HTML como manifest. Se importa el entrypoint real con un build de juguete
    (`frontend_dist()` apuntado a el)."""
    import app.main as app_main
    from app import frontend_dist as fd

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa-de-prueba</html>", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text('{"name": "LibraClub", "icons": []}', encoding="utf-8")
    monkeypatch.setattr(fd, "_DIST_DOCKER", tmp_path / "no-existe")
    monkeypatch.setattr(fd, "_DIST_LOCAL", dist)
    # `app.asgi` llama `crear_app()` sin config: aca, la de la suite (como `test_secretos_config_json`).
    config = Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False, directorio_de_datos=str(tmp_path),
    )
    real = app_main.crear_app
    monkeypatch.setattr(app_main, "crear_app", lambda *a, **k: real(config))
    previo = sys.modules.pop("app.asgi", None)
    try:
        asgi = importlib.import_module("app.asgi")
        c = _cliente(asgi.app)
        r = c.get("/manifest.webmanifest")
        assert r.status_code == 200 and r.json()["name"] == "LibraClub", r.text
        assert "manifest" in r.headers["content-type"], r.headers
        assert c.get("/api/marca").json()["propia"] is False
        assert "spa-de-prueba" in c.get("/cualquier/ruta").text
    finally:
        sys.modules.pop("app.asgi", None)
        if previo is not None:
            sys.modules["app.asgi"] = previo
