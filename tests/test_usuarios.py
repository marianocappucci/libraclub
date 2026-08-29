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


# -- La credencial del panel del cliente ------------------------------------
#
# El panel de un dueño multisucursal da de alta y de baja empleados en SUS
# instancias desde un solo lugar. Hasta libraauth v0.35.0 su credencial
# autorizaba una sola ruta, `/api/resumen`, de solo lectura.
#
# 🔴 **La credencial del panel es POR INSTANCIA**, a diferencia del token de
# servicio, que es uno por producto y lo comparten todas sus instancias. Esa es
# toda la razon de que exista este camino en vez de darle al panel el otro.

TOKEN_PANEL = "token-de-panel-de-prueba-no-es-real"
CABECERA_PANEL = "X-Panel-Auth"


@pytest.fixture
def app_con_panel(engine, sesion, monkeypatch):
    """La app con `LIBRA_PANEL_TOKEN` definido, como en una instancia que
    participa de un panel."""
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    monkeypatch.setenv("LIBRA_PANEL_TOKEN", TOKEN_PANEL)
    monkeypatch.delenv("LIBRA_SERVICE_TOKEN", raising=False)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    yield crear_app(_config())
    AuthBase.metadata.drop_all(engine)


def test_el_panel_da_de_alta_un_empleado(app_con_panel):
    """Lo que el aprovisionamiento necesita: crear el usuario **sin sesion**.

    El panel no tiene cookie de esta instancia y no la va a tener: llega con su
    credencial y nada mas.
    """
    cliente = TestClient(app_con_panel, base_url="https://testserver")
    r = cliente.post(
        "/api/usuarios",
        headers={CABECERA_PANEL: TOKEN_PANEL},
        json={"username": "encargado", "name": "Encargado",
              "password": "clave-del-encargado", "role": "staff"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["username"] == "encargado"

    # Y lo ve listado, que es lo que la pantalla del panel necesita para
    # mostrar donde esta dado de alta cada empleado.
    listado = cliente.get("/api/usuarios", headers={CABECERA_PANEL: TOKEN_PANEL})
    assert listado.status_code == 200, listado.text
    assert "encargado" in [u["username"] for u in listado.json()]


def test_y_lo_da_de_baja(app_con_panel):
    """El pedido era darlos de alta **y de baja** desde un solo lugar."""
    cliente = TestClient(app_con_panel, base_url="https://testserver")
    creado = cliente.post(
        "/api/usuarios",
        headers={CABECERA_PANEL: TOKEN_PANEL},
        json={"username": "temporal", "name": "Temporal",
              "password": "clave-temporal", "role": "staff"},
    ).json()
    r = cliente.delete(f"/api/usuarios/{creado['id']}",
                       headers={CABECERA_PANEL: TOKEN_PANEL})
    assert r.status_code == 204, r.text


def test_EL_PANEL_NO_ABRE_EL_RESTO_DE_LAS_RUTAS_DE_ADMIN(app_con_panel):
    """🔴 El test que justifica que el guard se aplique router por router.

    De `require_admin_o_servicio` cuelgan siete lugares en este producto.
    Ampliar aquel guard le habria dado al panel todos de una, sin que nadie lo
    pidiera. `/api/admin/resumen` es uno de esos, y tiene que seguir cerrado.

    ⚠️ Ojo con no confundirlo con `/api/resumen`, que **si** es del panel: ese
    lo monta la factory de LibraCore con su propio guard y es de solo lectura.
    Son dos rutas distintas con nombres parecidos.

    ⚠️ Y la ruta es `/admin/resumen`, **sin** `/api`: el router de admin lleva
    su propio prefijo. La primera version de este test pegaba en
    `/api/admin/resumen` y recibia un 404, que se confunde con "cerrado" y
    habria dejado pasar la ampliacion sin avisar.
    """
    cliente = TestClient(app_con_panel, base_url="https://testserver")
    # El control positivo: la credencial es buena y abre lo que tiene que abrir.
    assert cliente.get(
        "/api/usuarios", headers={CABECERA_PANEL: TOKEN_PANEL}
    ).status_code == 200
    # Y no abre lo demas. 401 y no 404: la ruta EXISTE y esta cerrada.
    r = cliente.get("/admin/resumen", headers={CABECERA_PANEL: TOKEN_PANEL})
    assert r.status_code == 401, (
        f"la credencial del panel abrio /admin/resumen: {r.status_code}"
    )


def test_sin_la_variable_la_credencial_del_panel_no_sirve(engine, sesion, monkeypatch):
    """Opt-in por ausencia: una instancia que no participa de ningun panel se
    comporta exactamente como antes, sin tocarle el compose."""
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    monkeypatch.delenv("LIBRA_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("LIBRA_SERVICE_TOKEN", raising=False)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    try:
        cliente = TestClient(crear_app(_config()), base_url="https://testserver")
        r = cliente.get("/api/usuarios", headers={CABECERA_PANEL: TOKEN_PANEL})
        assert r.status_code == 401, r.text
    finally:
        AuthBase.metadata.drop_all(engine)


def test_el_token_de_servicio_SIGUE_entrando(app_con_token):
    """No se le saca nada al backoffice: el guard nuevo es el viejo mas el panel.

    Sin este control, cambiar el gate del router podria haberle cerrado la
    puerta a `admin.libraclub.com.ar` ---y el sintoma aparece del otro lado, en
    una pestaña que contesta 403---.
    """
    cliente = TestClient(app_con_token, base_url="https://testserver")
    assert cliente.get("/api/usuarios", headers={CABECERA: TOKEN}).status_code == 200


def test_un_token_de_panel_equivocado_no_entra(app_con_panel):
    cliente = TestClient(app_con_panel, base_url="https://testserver")
    r = cliente.get("/api/usuarios", headers={CABECERA_PANEL: "otra-cosa"})
    assert r.status_code == 401


# -- El hallazgo: ningun token podia editar ni dar de baja -------------------
#
# 🔴 Medido el 2026-08-29: con el token de servicio, `PUT /api/usuarios/{id}` y
# `DELETE` daban **401** mientras `POST`, `GET` y `PUT .../password` andaban. Las
# dos rutas pedian `Depends(get_current_user)`, que corta sin sesion.
#
# O sea que el backoffice del proveedor podia crear usuarios y cambiarles la
# clave, pero **no editarlos ni darlos de baja** ---y el docstring de `editar`
# decia explicitamente que si---. No lo encontro una revision del codigo: lo
# encontro necesitar el `DELETE` para el aprovisionamiento del panel.


def test_EL_TOKEN_DE_SERVICIO_PUEDE_EDITAR_Y_DAR_DE_BAJA(app_con_token):
    """Los seis verbos del router, con el token del backoffice."""
    cliente = TestClient(app_con_token, base_url="https://testserver")
    h = {CABECERA: TOKEN}
    creado = cliente.post("/api/usuarios", headers=h, json={
        "username": "empleado", "name": "Empleado",
        "password": "clave-del-empleado", "role": "staff"}).json()

    editar = cliente.put(f"/api/usuarios/{creado['id']}", headers=h, json={
        "name": "Empleado editado", "role": "staff", "active": True})
    assert editar.status_code == 200, editar.text
    assert editar.json()["name"] == "Empleado editado"

    assert cliente.delete(f"/api/usuarios/{creado['id']}", headers=h).status_code == 204


def test_el_panel_tambien_edita_y_da_de_baja(app_con_panel):
    """Es lo que "dar de alta y de baja desde un solo lugar" necesita."""
    cliente = TestClient(app_con_panel, base_url="https://testserver")
    h = {CABECERA_PANEL: TOKEN_PANEL}
    creado = cliente.post("/api/usuarios", headers=h, json={
        "username": "empleado2", "name": "Empleado 2",
        "password": "clave-del-empleado2", "role": "staff"}).json()

    assert cliente.put(f"/api/usuarios/{creado['id']}", headers=h, json={
        "name": "Empleado 2", "role": "staff", "active": False}).status_code == 200
    assert cliente.delete(f"/api/usuarios/{creado['id']}", headers=h).status_code == 204


def test_Y_UN_ADMIN_SIGUE_SIN_PODER_BORRARSE_A_SI_MISMO(api):
    """🔴 El control de que aflojar la identidad no aflojo la regla.

    La regla mira el usuario **de la sesion**; con un token la identidad no es
    un usuario de este producto (`id: None`) y por eso no aplica. Cambiar de
    donde sale `actual` podria haberla desactivado tambien para las sesiones, y
    con un solo administrador eso deja la instancia sin nadie que administre.
    """
    yo = api.get("/auth/me").json()
    r = api.delete(f"/api/usuarios/{yo['id']}")
    assert r.status_code == 409, r.text
