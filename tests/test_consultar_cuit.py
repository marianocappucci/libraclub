"""`GET /api/consultar-cuit/{cuit}`: el router del motor, montado en este producto.

Completa el alta de un cliente (nombre, domicilio, condición de IVA) con el padrón de ARCA. Es el mismo router que
usan Contalibra, Restolibra y VentaLibra; acá se fija lo que le toca a LibraClub:

- **Lee la config de ARCA que escribe la pantalla de Configuración** (`/config/arca`, tabla `arca_config` del
  motor, en la base de LibraCore): lo que se carga ahí es lo que usa la consulta.
- **Va con `require_staff`**, la misma guarda que el alta de `clientes` (el mostrador carga al que llama por
  primera vez): sin sesión es 401 y un operador que no es admin entra.
- **Va con `exigir_base`**, como el router de ARCA: sin base de LibraCore dice qué variable falta.
- El cliente de ARCA vive en el motor, así que se simula `libracore.arca_wsaa` y `libracore.arca_wspadron`.
"""

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from libracore.config_manager import ARCHIVOS_POR_AMBIENTE

from app.main import crear_app
from tests.test_facturacion import ARCA, USUARIO, _config, _url_core
from tests.test_facturacion import CLAVE as CLAVE_ADMIN

CERT, CLAVE = ARCHIVOS_POR_AMBIENTE["homologacion"]
URL = "/api/consultar-cuit/"


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    """La app contra la base de LibraCore de este worker, con el admin ya logueado (como en `test_facturacion`)."""
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE_ADMIN)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    cliente = TestClient(crear_app(_config(base_de_libracore)), base_url="https://testserver")
    assert cliente.post("/auth/login", json={"username": USUARIO, "password": CLAVE_ADMIN}).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def arca_cargada(api, tmp_path, monkeypatch):
    """La config de ARCA cargada por la pantalla (`PUT /config/arca`) y el par de homologación en disco."""
    from libracore import config_manager
    from libracore.db import arca_config

    d = tmp_path / "arca_certs"
    d.mkdir()
    for nombre in (CERT, CLAVE):
        (d / nombre).write_text(nombre)
    monkeypatch.setattr(config_manager, "CERTS_DIR", str(d))

    r = api.put("/config/arca", json=ARCA)
    assert r.status_code == 200, r.text
    empresa = r.json()["empresa"]
    arca_config.actualizar_arca_config(
        empresa, certificado_path_homologacion=str(d / CERT), clave_path_homologacion=str(d / CLAVE),
    )


PERSONA = {
    "nombre": "ACME SA",
    "domicilio": "Ruta 8 km 5, Pilar, Buenos Aires",
    "iva_condition": "Responsable Inscripto",
    "estado": "ACTIVO",
}


def _padron(monkeypatch, *, persona=None, falla=None, pedidos=None, usados=None):
    """Simula WSAA y WSPadron; `pedidos` junta los CUIT consultados y `usados` lo que se le pasó al WSAA."""
    from libracore import arca_wsaa, arca_wspadron

    async def _autenticar(cert, clave, ambiente, servicio=""):
        if usados is not None:
            usados.update(cert=cert, clave=clave, ambiente=ambiente, servicio=servicio)
        return {"token": "t", "sign": "s"}

    async def _consultar(cuit_emisor, cuit_consultado, *a, **k):
        if pedidos is not None:
            pedidos.append(cuit_consultado)
        if falla is not None:
            raise falla
        return persona

    monkeypatch.setattr(arca_wsaa, "autenticar", _autenticar)
    monkeypatch.setattr(arca_wspadron, "consultar_persona", _consultar)


@pytest.mark.parametrize("cuit", ["123", "abc", "2011111111912"])
def test_cuit_que_no_tiene_11_digitos_da_400(api, arca_cargada, cuit):
    r = api.get(URL + cuit)
    assert r.status_code == 400
    assert r.json() == {"error": "CUIT inválido. Debe tener 11 dígitos."}


def test_sin_config_de_arca_da_503(api):
    r = api.get(URL + "30711111114")
    assert r.status_code == 503
    assert r.json() == {
        "error": "Configurá los certificados ARCA en Configuración para habilitar la consulta de CUIT."
    }


def test_con_el_padron_simulado_da_200_con_los_campos_del_padron(api, arca_cargada, monkeypatch):
    usados = {}
    _padron(monkeypatch, persona=PERSONA, usados=usados)
    r = api.get(URL + "30711111114")
    assert r.status_code == 200, r.text
    assert r.json() == PERSONA
    # Lo que se cargó por la pantalla de ARCA es lo que usa el padrón: el par de ese ambiente, en su servicio.
    assert usados["ambiente"] == "homologacion"
    assert usados["servicio"] == "ws_sr_padron_a13"
    assert usados["cert"].endswith(CERT)


def test_el_cuit_se_limpia_antes_de_consultar(api, arca_cargada, monkeypatch):
    pedidos = []
    _padron(monkeypatch, persona=PERSONA, pedidos=pedidos)
    assert api.get(URL + "30-71111111-4").status_code == 200
    assert pedidos == ["30711111114"]


@pytest.mark.parametrize("falla, estado, mensaje", [
    (RuntimeError("CUIT no encontrado en el padrón de ARCA."), 404, "CUIT no encontrado en el padrón de ARCA."),
    (RuntimeError("Computador no autorizado a acceder al servicio"), 403, "Consulta a Padrón Alcance 13"),
    (RuntimeError("alguna otra cosa de ARCA"), 502, "alguna otra cosa de ARCA"),
    (ValueError("boom"), 500, "Error al consultar ARCA: boom"),
])
def test_los_errores_del_padron_conservan_estado_y_mensaje(api, arca_cargada, monkeypatch, falla, estado, mensaje):
    _padron(monkeypatch, falla=falla)
    r = api.get(URL + "30711111114")
    assert r.status_code == estado, r.text
    assert mensaje in r.json()["error"]


def test_un_operador_que_no_es_admin_puede_consultar(api, arca_cargada, monkeypatch):
    """La guarda es la del alta de clientes (`require_staff`): quien carga al cliente tiene que poder consultar."""
    _padron(monkeypatch, persona=PERSONA)
    api.post("/api/usuarios", json={
        "username": "mostrador", "name": "Mostrador", "password": "clave-mostrador", "role": "staff"})
    staff = TestClient(crear_app(_config(_url_core())), base_url="https://testserver")
    assert staff.post(
        "/auth/login", json={"username": "mostrador", "password": "clave-mostrador"}).status_code == 200
    # Control: ese usuario no es admin (no toca la config de ARCA).
    assert staff.get("/config/arca").status_code == 403
    r = staff.get(URL + "30711111114")
    assert r.status_code == 200, r.text
    assert r.json() == PERSONA


def test_sin_sesion_es_401_y_no_se_toca_arca(api, arca_cargada, monkeypatch):
    pedidos = []
    _padron(monkeypatch, persona=PERSONA, pedidos=pedidos)
    anonimo = TestClient(api.app, base_url="https://testserver")
    assert anonimo.get(URL + "30711111114").status_code == 401
    assert pedidos == []
