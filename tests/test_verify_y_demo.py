"""Los dos endpoints que existen para la landing: `/auth/verify` y `/auth/demo`.

`POST /auth/verify` es lo que usa el login de `/docs/` de `libraclub_web` para
validar credenciales sin crear sesión. `POST /auth/demo` es el auto-login del
visitante de `demo.libraclub.com.ar`, con código de acceso.

🔴 **Los dos se prenden en dos lugares distintos**, y ninguno de los dos delata
que le falta el otro: el flag en `routers/auth.py` registra la ruta, y `main.py`
cablea el usuario de la demo y el repositorio de códigos. Por eso los tests de
abajo miden el comportamiento —qué contesta— y no que las líneas estén escritas.

Igual que en `test_api.py`, `TestClient` va con `base_url="https://…"`: la
cookie de sesión es `Secure` y sobre `http://` httpx no la reenvía.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"
SECRETO_DOCS = "no-es-el-secreto-real-de-ninguna-instancia"
USUARIO_DEMO = "visitante"
COOKIE = "lb_session"


def _config() -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"],
        entorno="test",
        debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
    )


@pytest.fixture
def entorno(engine, sesion, monkeypatch):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    yield monkeypatch
    AuthBase.metadata.drop_all(engine)


def _cookies_de_sesion(cliente: TestClient) -> list[str]:
    """Los nombres de cookie que dejó la respuesta.

    Se mira por nombre y no contra una constante importada porque el nombre lo
    fija `libraauth`; lo que se afirma es que **no quedó ninguna** sesión.
    """
    return list(cliente.cookies.keys())


# ── /auth/verify ────────────────────────────────────────────────────────────


@pytest.fixture
def cliente_con_secreto(entorno):
    entorno.setenv("DOCS_AUTH_SECRET", SECRETO_DOCS)
    return TestClient(crear_app(_config()), base_url="https://testserver")


def test_verify_acepta_las_credenciales_buenas(cliente_con_secreto):
    r = cliente_con_secreto.post(
        "/auth/verify",
        json={"username": USUARIO, "password": CLAVE},
        headers={"X-Internal-Auth": SECRETO_DOCS},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"valid": True}


def test_verify_rechaza_las_credenciales_malas(cliente_con_secreto):
    """El control del de arriba: sin esto, un verify que dijera `true` a
    cualquier cosa pasaría igual, y el login de `/docs/` sería una puerta
    abierta con formulario."""
    r = cliente_con_secreto.post(
        "/auth/verify",
        json={"username": USUARIO, "password": "otra"},
        headers={"X-Internal-Auth": SECRETO_DOCS},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"valid": False}


def test_verify_no_crea_sesion(cliente_con_secreto):
    """Es un chequeo stateless: si dejara cookie, la landing quedaría con una
    sesión de la app del complejo en un origen que no es el suyo."""
    r = cliente_con_secreto.post(
        "/auth/verify",
        json={"username": USUARIO, "password": CLAVE},
        headers={"X-Internal-Auth": SECRETO_DOCS},
    )
    assert r.json() == {"valid": True}
    assert _cookies_de_sesion(cliente_con_secreto) == []


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="sin-header"),
        pytest.param({"X-Internal-Auth": ""}, id="header-vacio"),
        pytest.param({"X-Internal-Auth": "otro-secreto"}, id="secreto-equivocado"),
    ],
)
def test_verify_exige_el_secreto_compartido(cliente_con_secreto, headers):
    r = cliente_con_secreto.post(
        "/auth/verify",
        json={"username": USUARIO, "password": CLAVE},
        headers=headers,
    )
    assert r.status_code == 401, r.text


def test_verify_falla_cerrado_sin_secreto_configurado(entorno):
    """🔴 El caso que importa: la instancia **sin** `DOCS_AUTH_SECRET`.

    Sin este chequeo, un secreto vacío del lado de la app haría que un header
    vacío coincidiera con él, y cualquiera podría preguntarle a la instancia si
    una contraseña es correcta. Es un oráculo de credenciales sin autenticar.
    """
    entorno.delenv("DOCS_AUTH_SECRET", raising=False)
    cliente = TestClient(crear_app(_config()), base_url="https://testserver")
    for headers in ({}, {"X-Internal-Auth": ""}):
        r = cliente.post(
            "/auth/verify",
            json={"username": USUARIO, "password": CLAVE},
            headers=headers,
        )
        assert r.status_code == 401, f"con headers={headers}: {r.text}"


# ── /auth/demo ──────────────────────────────────────────────────────────────


def test_sin_demo_mode_la_ruta_de_demo_no_atiende(entorno):
    """En la instancia de un complejo el auto-login **no existe**.

    Se afirma "no es 200" y no un código exacto a propósito: LibraClub sirve la
    SPA con un catch-all, así que una ruta inexistente puede contestar 405 (el
    catch-all matchea por GET y el POST cae en método no permitido) en vez de
    404. Lo que no puede pasar nunca es que deje entrar.
    """
    entorno.delenv("DEMO_MODE", raising=False)
    entorno.delenv("DEMO_USERNAME", raising=False)
    cliente = TestClient(crear_app(_config()), base_url="https://testserver")
    r = cliente.post("/auth/demo", json={"codigo": "lo-que-sea"})
    assert r.status_code != 200, r.text
    assert _cookies_de_sesion(cliente) == []


@pytest.fixture
def demo(entorno):
    """Una instancia demo de verdad: las dos variables, el usuario sembrado y
    el repositorio de códigos cableado."""
    entorno.setenv("DEMO_MODE", "1")
    entorno.setenv("DEMO_USERNAME", USUARIO_DEMO)
    entorno.delenv("DEMO_PASSWORD", raising=False)
    app = crear_app(_config())
    return TestClient(app, base_url="https://testserver"), app


def test_la_demo_se_anuncia_como_tal(demo):
    cliente, _ = demo
    r = cliente.get("/auth/demo")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "enabled": True,
        "username": USUARIO_DEMO,
        "requiere_codigo": True,
    }


def test_sin_codigo_no_se_entra_a_la_demo(demo):
    """Este es el test que justifica que la demo pueda estar en internet."""
    cliente, _ = demo
    r = cliente.post("/auth/demo", json={"codigo": ""})
    assert r.status_code == 401, r.text
    assert _cookies_de_sesion(cliente) == []


def test_con_un_codigo_inventado_tampoco(demo):
    cliente, _ = demo
    r = cliente.post("/auth/demo", json={"codigo": "ABCD-EFGH-JKMN"})
    assert r.status_code == 401, r.text
    assert _cookies_de_sesion(cliente) == []


def test_con_un_codigo_emitido_se_entra(demo):
    """El control positivo de los dos de arriba. Sin él, un endpoint que
    rechazara SIEMPRE los haría pasar a los dos y nadie notaría que la demo no
    deja entrar a nadie."""
    cliente, app = demo
    emitido = app.state.demo_codigos.crear(etiqueta="suite")
    r = cliente.post("/auth/demo", json={"codigo": emitido["codigo"]})
    assert r.status_code == 200, r.text
    assert _cookies_de_sesion(cliente) != []


def test_el_visitante_de_la_demo_no_es_admin(demo):
    """🔴 Un visitante con rol admin llega al ABM de usuarios, a las tarifas y
    al backup — o sea, puede cambiar los precios de la muestra y vaciarla."""
    cliente, app = demo
    emitido = app.state.demo_codigos.crear(etiqueta="suite")
    r = cliente.post("/auth/demo", json={"codigo": emitido["codigo"]})
    assert r.status_code == 200, r.text
    assert r.json()["role"] != "admin"


def test_un_codigo_revocado_deja_de_servir(demo):
    cliente, app = demo
    emitido = app.state.demo_codigos.crear(etiqueta="suite")
    app.state.demo_codigos.revocar(emitido["id"])
    r = cliente.post("/auth/demo", json={"codigo": emitido["codigo"]})
    assert r.status_code == 401, r.text
    assert _cookies_de_sesion(cliente) == []
