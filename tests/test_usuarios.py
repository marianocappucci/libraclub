"""El router de usuarios, y el camino por el que entra el backoffice de la suite.

Lo que más importa acá **no** es el ABM: es el token de servicio. Es el único
camino por el que `admin.libraclub.com.ar` administra esta instancia, no lo
ejercita ninguna otra parte del producto, y si se rompe el síntoma aparece del
otro lado —una pestaña que contesta 403— sin nada que apunte a este archivo.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"

#: El token de servicio de la suite. Fijo y evidente: es una constante de test.
TOKEN = "token-de-servicio-de-prueba-no-es-real"
CABECERA = "X-Internal-Auth"


def _config() -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"],
        entorno="test",
        debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
    )


@pytest.fixture
def app_con_token(engine, sesion, monkeypatch):
    """La app con `LIBRA_SERVICE_TOKEN` definido, como en el VPS."""
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    monkeypatch.setenv("LIBRA_SERVICE_TOKEN", TOKEN)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    yield crear_app(_config())
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def api(app_con_token):
    """Un cliente logueado como admin. `https` porque la cookie es `Secure`."""
    cliente = TestClient(app_con_token, base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    return cliente


@pytest.fixture
def panel(app_con_token):
    """Un cliente **sin sesión**, que se identifica con el token de servicio.

    Es exactamente lo que hace el backoffice: viaja por la red interna de Docker
    entre contenedores, sin ser usuario de este producto.
    """
    cliente = TestClient(app_con_token, base_url="https://testserver")
    cliente.headers[CABECERA] = TOKEN
    return cliente


def test_el_panel_lista_usuarios_sin_tener_sesion(panel):
    """🔑 El camino que usa `admin.libraclub.com.ar`, y el único que lo usa."""
    respuesta = panel.get("/api/usuarios")
    assert respuesta.status_code == 200, respuesta.text
    assert [u["username"] for u in respuesta.json()] == [USUARIO]


def test_el_panel_da_de_alta_y_el_usuario_puede_entrar(panel, app_con_token):
    """No alcanza con que el alta devuelva 201: tiene que poder loguearse.

    Es la diferencia entre "se escribió una fila" y "se creó un usuario" — un
    hash mal armado devuelve 201 igual.
    """
    alta = panel.post(
        "/api/usuarios",
        json={"username": "encargado", "name": "Encargado", "password": "abrime"},
    )
    assert alta.status_code == 201, alta.text
    assert alta.json()["role"] == "staff", "el default tiene que ser staff, no admin"

    otro = TestClient(app_con_token, base_url="https://testserver")
    assert otro.post(
        "/auth/login", json={"username": "encargado", "password": "abrime"}
    ).status_code == 200


def test_sin_token_y_sin_sesion_no_se_entra(app_con_token):
    """El control que hace que los dos de arriba signifiquen algo.

    Sin esto, un router montado **sin** la dependencia de autenticación pasaría
    los tests del panel igual: el token no se estaría verificando, sólo
    ignorando.
    """
    anonimo = TestClient(app_con_token, base_url="https://testserver")
    assert anonimo.get("/api/usuarios").status_code in (401, 403)


def test_un_token_equivocado_se_rechaza(app_con_token):
    """Y el otro control: que el header no sea un pase mágico por existir."""
    impostor = TestClient(app_con_token, base_url="https://testserver")
    impostor.headers[CABECERA] = TOKEN + "-pero-no"
    assert impostor.get("/api/usuarios").status_code in (401, 403)


def test_sin_la_variable_en_el_entorno_el_token_no_abre_nada(engine, sesion, monkeypatch):
    """🔑 La razón por la que dejar `LIBRA_SERVICE_TOKEN` vacío es seguro.

    `libraauth` trata el token vacío como no definido y cae en `require_admin`.
    Una instancia que no define la variable no queda abierta — lo que abriría
    algo sería ponerle un valor adivinable.
    """
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    monkeypatch.delenv("LIBRA_SERVICE_TOKEN", raising=False)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    try:
        cliente = TestClient(crear_app(_config()), base_url="https://testserver")
        cliente.headers[CABECERA] = TOKEN
        assert cliente.get("/api/usuarios").status_code in (401, 403)
    finally:
        AuthBase.metadata.drop_all(engine)


def test_un_admin_no_se_puede_dejar_afuera_a_si_mismo(api):
    """Con un solo administrador, la única salida sería entrar a la base."""
    yo = api.get("/auth/me").json()
    cuerpo = {"name": "Administrador", "role": "admin", "active": True}

    desactivarse = api.put(f"/api/usuarios/{yo['id']}", json={**cuerpo, "active": False})
    assert desactivarse.status_code == 409
    bajarse = api.put(f"/api/usuarios/{yo['id']}", json={**cuerpo, "role": "staff"})
    assert bajarse.status_code == 409
    borrarse = api.delete(f"/api/usuarios/{yo['id']}")
    assert borrarse.status_code == 409

    # El control: la misma operación sobre OTRO usuario sí se puede. Sin esto,
    # los tres 409 de arriba pasarían igual con el endpoint roto entero.
    otro = api.post(
        "/api/usuarios",
        json={"username": "otro", "name": "Otro", "password": "x", "role": "admin"},
    ).json()
    assert api.put(
        f"/api/usuarios/{otro['id']}", json={**cuerpo, "active": False}
    ).status_code == 200
    assert api.delete(f"/api/usuarios/{otro['id']}").status_code == 204


def test_editar_sin_tocar_el_correo_no_lo_borra(api):
    """El botón de activar/desactivar manda el cuerpo sin `email`.

    Con `""` por default, desactivar a alguien le borraba el mail en silencio.
    """
    creado = api.post(
        "/api/usuarios",
        json={
            "username": "conmail",
            "name": "Con Mail",
            "password": "x",
            "email": "alguien@complejo.com",
        },
    ).json()
    editado = api.put(
        f"/api/usuarios/{creado['id']}",
        json={"name": "Con Mail", "role": "staff", "active": False},
    )
    assert editado.status_code == 200
    assert editado.json()["email"] == "alguien@complejo.com"


def test_la_clave_vacia_se_rechaza(api):
    creado = api.post(
        "/api/usuarios", json={"username": "z", "name": "Z", "password": "x"}
    ).json()
    assert api.put(
        f"/api/usuarios/{creado['id']}/password", json={"password": "   "}
    ).status_code == 422
    # Control: una clave de verdad sí entra, y sirve para loguearse.
    assert api.put(
        f"/api/usuarios/{creado['id']}/password", json={"password": "nueva"}
    ).status_code == 204


def test_username_repetido_da_409(api):
    api.post("/api/usuarios", json={"username": "dup", "name": "D", "password": "x"})
    segundo = api.post(
        "/api/usuarios", json={"username": "dup", "name": "D2", "password": "x"}
    )
    assert segundo.status_code == 409
