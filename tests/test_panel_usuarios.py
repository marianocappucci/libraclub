"""Los clientes que administran los usuarios de esta instancia, contra la app de verdad.

Quienes llaman, y por dónde:

* **`libra-backoffice`** (`admin.libraclub.com.ar`), con `X-Internal-Auth` =
  `LIBRA_SERVICE_TOKEN` (uno por producto). Su pestaña «Usuarios» hace, contra
  `USERS_PATH` (acá `/api/usuarios`; el default del backoffice es `/users`, así
  que esta instancia lo necesita configurado):
  `GET`, `POST`, `PUT /{id}`, `PUT /{id}/password` (204) y `DELETE /{id}` (204),
  con los cuerpos públicos de `libraauth.usuarios` (`UsuarioAlta`,
  `UsuarioEdicion` mandado con `exclude_none`, `UsuarioClaveNueva`). Desactivar
  es el `PUT` con `active=false`.
* **`libra-panel`** (el panel del dueño multisucursal), con `X-Panel-Auth` =
  `LIBRA_PANEL_TOKEN` (uno por instancia). Hoy sólo da de alta empleados:
  `POST {ruta_de_usuarios}` con `{username, name, password, role}`, espera un
  201 con `username` en el cuerpo y trata el 409 como «ya estaba» (no como falla).

`test_usuarios.py` prueba el guard y los casos sueltos. Acá se ejerce el ciclo
completo **sin sesión** y se mide el **efecto** de cada operación (que la clave
nueva sirva para entrar, que el desactivado no entre), porque un 2xx solo no
dice que el usuario quedó como se pidió. Si una ruta deja de existir o contesta
distinto de lo que esos clientes esperan, el síntoma aparece del otro lado (una
pestaña que dice 404/405 o «no es JSON») sin nada que apunte a este producto.
"""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth, verificar_contrato_de_usuarios
from libraauth.usuarios import UsuarioAlta, UsuarioClaveNueva, UsuarioEdicion

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"
RUTA = "/api/usuarios"

#: Constantes de test, fijas y evidentes: no son claves.
TOKEN_SERVICIO = "token-de-servicio-de-prueba-no-es-real"
TOKEN_PANEL = "token-de-panel-de-prueba-no-es-real"
BACKOFFICE = {"X-Internal-Auth": TOKEN_SERVICIO}
PANEL = {"X-Panel-Auth": TOKEN_PANEL}


@pytest.fixture
def app_con_ambos_tokens(engine, sesion, monkeypatch, tmp_path):
    """La app como en el VPS: token de servicio del producto y credencial de panel."""
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    monkeypatch.setenv("LIBRA_SERVICE_TOKEN", TOKEN_SERVICIO)
    monkeypatch.setenv("LIBRA_PANEL_TOKEN", TOKEN_PANEL)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    config = Config(
        database_url=os.environ["DATABASE_URL"],
        entorno="test",
        debug=False,
        directorio_de_datos=str(tmp_path),
    )
    yield crear_app(config)
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def servidor(app_con_ambos_tokens):
    """Un cliente sin cookie: ni el backoffice ni el panel son usuarios del producto."""
    return TestClient(app_con_ambos_tokens, base_url="https://testserver")


def _entra(app, usuario: str, clave: str) -> int:
    """El status de un login desde un navegador limpio."""
    navegador = TestClient(app, base_url="https://testserver")
    return navegador.post("/auth/login", json={"username": usuario, "password": clave}).status_code


def _alta(servidor, headers, username="empleado", role="staff", clave="clave-inicial") -> dict:
    cuerpo = UsuarioAlta(username=username, name=username.title(), password=clave, role=role)
    r = servidor.post(RUTA, json=cuerpo.model_dump(), headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# -- Las rutas existen y tienen la forma que esperan los clientes -------------


def test_las_cinco_rutas_del_backoffice_existen(app_con_ambos_tokens):
    """Si alguna desaparece del router, acá se ve por el nombre y no por un 404 lejano."""
    # Del esquema OpenAPI y no de `app.routes`: con los routers incluidos de
    # forma perezosa, `routes` no los desarma.
    declaradas = {
        (metodo.upper(), ruta)
        for ruta, operaciones in app_con_ambos_tokens.openapi()["paths"].items()
        for metodo in operaciones
    }
    esperadas = {
        ("GET", RUTA),
        ("POST", RUTA),
        ("PUT", f"{RUTA}/{{user_id}}"),
        ("PUT", f"{RUTA}/{{user_id}}/password"),
        ("DELETE", f"{RUTA}/{{user_id}}"),
    }
    # El nombre del parámetro es de libraauth; se compara sin él.
    forma = {(m, re.sub(r"\{[^}]+\}", "{user_id}", p)) for m, p in declaradas}
    faltan = esperadas - forma
    assert not faltan, f"faltan rutas que el backoffice llama: {sorted(faltan)}"


@pytest.mark.parametrize("headers", [BACKOFFICE, PANEL], ids=["backoffice", "panel"])
def test_el_ciclo_completo_sin_sesion(servidor, headers):
    """El contrato compartido de la familia, con cada credencial y sin cookie."""
    verificar_contrato_de_usuarios(servidor, RUTA, role="staff", headers=headers)


# -- Listar -------------------------------------------------------------------


def test_listar_devuelve_lo_que_lee_la_grilla(servidor):
    _alta(servidor, BACKOFFICE, "uno")
    r = servidor.get(RUTA, headers=BACKOFFICE)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    por_nombre = {u["username"]: u for u in r.json()}
    assert set(por_nombre) == {USUARIO, "uno"}
    assert {"id", "username", "name", "role", "active"} <= por_nombre["uno"].keys()
    # Jamás el hash ni la clave: el listado lo ve cualquiera con el token.
    assert not any("password" in k or "hash" in k for u in por_nombre.values() for k in u)


# -- Crear --------------------------------------------------------------------


def test_el_panel_crea_un_empleado_y_este_entra(servidor, app_con_ambos_tokens):
    """Exactamente el cuerpo de `libra_panel.routers.empleados`: 201 con `username`."""
    r = servidor.post(
        RUTA,
        headers=PANEL,
        json={"username": "encargado", "name": "Encargado", "password": "clave-larga-1", "role": "staff"},
    )
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["username"] == "encargado"  # lo que valida `_usuario_valido` del panel
    assert _entra(app_con_ambos_tokens, "encargado", "clave-larga-1") == 200


@pytest.mark.parametrize("headers", [BACKOFFICE, PANEL], ids=["backoffice", "panel"])
def test_un_usuario_repetido_da_409_y_no_pisa_al_existente(servidor, app_con_ambos_tokens, headers):
    """El panel lee el 409 como «ya estaba» (`EmpleadoYaExiste`), no como falla."""
    _alta(servidor, headers, "repetido", clave="clave-original")
    r = servidor.post(
        RUTA,
        headers=headers,
        json={"username": "repetido", "name": "Otro", "password": "clave-intrusa", "role": "staff"},
    )
    assert r.status_code == 409, r.text
    assert "detail" in r.json()  # `_detalle_de_error` del panel lo muestra
    assert _entra(app_con_ambos_tokens, "repetido", "clave-original") == 200
    assert _entra(app_con_ambos_tokens, "repetido", "clave-intrusa") != 200


def test_un_rol_que_no_existe_se_rechaza(servidor):
    r = servidor.post(
        RUTA,
        headers=BACKOFFICE,
        json={"username": "x", "name": "X", "password": "clave-larga-1", "role": "superheroe"},
    )
    assert r.status_code == 422, r.text


# -- Cambiar rol --------------------------------------------------------------


def test_cambiar_el_rol_queda_guardado_y_se_nota_en_la_sesion(servidor, app_con_ambos_tokens):
    creado = _alta(servidor, BACKOFFICE, "ascendido", role="staff", clave="clave-inicial")
    assert _sesion_de(app_con_ambos_tokens, "ascendido", "clave-inicial")["role"] == "staff"

    # El cuerpo que manda el backoffice: `UsuarioEdicion` con `exclude_none`.
    edicion = UsuarioEdicion(name="Ascendido", role="admin", active=True)
    r = servidor.put(f"{RUTA}/{creado['id']}", headers=BACKOFFICE, json=edicion.model_dump(exclude_none=True))
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"
    assert _sesion_de(app_con_ambos_tokens, "ascendido", "clave-inicial")["role"] == "admin"

    vuelta = UsuarioEdicion(name="Ascendido", role="staff", active=True)
    r = servidor.put(f"{RUTA}/{creado['id']}", headers=BACKOFFICE, json=vuelta.model_dump(exclude_none=True))
    assert r.status_code == 200, r.text
    assert _sesion_de(app_con_ambos_tokens, "ascendido", "clave-inicial")["role"] == "staff"


def _sesion_de(app, usuario: str, clave: str) -> dict:
    navegador = TestClient(app, base_url="https://testserver")
    assert navegador.post("/auth/login", json={"username": usuario, "password": clave}).status_code == 200
    return navegador.get("/auth/me").json()


# -- Cambiar contraseña -------------------------------------------------------


def test_cambiar_la_clave_es_un_204_y_la_vieja_deja_de_servir(servidor, app_con_ambos_tokens):
    creado = _alta(servidor, BACKOFFICE, "cambia", clave="clave-vieja-1")
    assert _entra(app_con_ambos_tokens, "cambia", "clave-vieja-1") == 200

    r = servidor.put(
        f"{RUTA}/{creado['id']}/password",
        headers=BACKOFFICE,
        json=UsuarioClaveNueva(password="clave-nueva-1").model_dump(),
    )
    # 204 sin cuerpo: el backoffice lo pide con `esperar_json=False`.
    assert r.status_code == 204, r.text
    assert r.content == b""
    assert _entra(app_con_ambos_tokens, "cambia", "clave-nueva-1") == 200
    assert _entra(app_con_ambos_tokens, "cambia", "clave-vieja-1") != 200


# -- Desactivar y borrar ------------------------------------------------------


def test_desactivar_impide_entrar_y_reactivar_lo_devuelve(servidor, app_con_ambos_tokens):
    """El toggle de la grilla: `PUT` sin `email`, que no tiene que borrar el correo."""
    r = servidor.post(
        RUTA,
        headers=BACKOFFICE,
        json=UsuarioAlta(
            username="toggle", name="Toggle", password="clave-larga-1", role="staff", email="toggle@complejo.com"
        ).model_dump(),
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]

    def _put(activo: bool):
        cuerpo = UsuarioEdicion(name="Toggle", role="staff", active=activo)
        return servidor.put(f"{RUTA}/{uid}", headers=BACKOFFICE, json=cuerpo.model_dump(exclude_none=True))

    r = _put(False)
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False
    assert r.json()["email"] == "toggle@complejo.com"
    assert _entra(app_con_ambos_tokens, "toggle", "clave-larga-1") in (401, 403)
    # Y en el listado figura desactivado, que es lo que pinta la grilla.
    fila = next(u for u in servidor.get(RUTA, headers=BACKOFFICE).json() if u["id"] == uid)
    assert fila["active"] is False

    assert _put(True).status_code == 200
    assert _entra(app_con_ambos_tokens, "toggle", "clave-larga-1") == 200


def test_borrar_es_un_204_y_el_usuario_ya_no_entra_ni_figura(servidor, app_con_ambos_tokens):
    creado = _alta(servidor, BACKOFFICE, "temporal", clave="clave-larga-1")
    r = servidor.delete(f"{RUTA}/{creado['id']}", headers=BACKOFFICE)
    assert r.status_code == 204, r.text
    assert r.content == b""
    assert _entra(app_con_ambos_tokens, "temporal", "clave-larga-1") != 200
    assert "temporal" not in [u["username"] for u in servidor.get(RUTA, headers=BACKOFFICE).json()]


def test_sobre_un_id_que_no_existe_es_404_en_las_tres_escrituras(servidor):
    """Un 404 de verdad, con JSON: no el `index.html` ni un 405 del catch-all."""
    inexistente = "no-existe-9999"
    pedidos = [
        servidor.put(f"{RUTA}/{inexistente}", headers=BACKOFFICE, json={"name": "X", "role": "staff", "active": True}),
        servidor.put(f"{RUTA}/{inexistente}/password", headers=BACKOFFICE, json={"password": "clave-larga-1"}),
        servidor.delete(f"{RUTA}/{inexistente}", headers=BACKOFFICE),
    ]
    assert [r.status_code for r in pedidos] == [404, 404, 404], [r.text for r in pedidos]


# -- Sin credencial no se administra nada -------------------------------------


@pytest.mark.parametrize(
    "metodo, ruta, cuerpo",
    [
        ("get", RUTA, None),
        ("post", RUTA, {"username": "i", "name": "I", "password": "clave-larga-1", "role": "staff"}),
        ("put", f"{RUTA}/1", {"name": "I", "role": "staff", "active": True}),
        ("put", f"{RUTA}/1/password", {"password": "clave-larga-1"}),
        ("delete", f"{RUTA}/1", None),
    ],
    ids=["listar", "crear", "editar", "clave", "borrar"],
)
@pytest.mark.parametrize(
    "headers",
    [{}, {"X-Internal-Auth": "otro-token"}, {"X-Panel-Auth": "otra-credencial"}],
    ids=["sin-credencial", "servicio-equivocado", "panel-equivocado"],
)
def test_sin_credencial_valida_ninguna_ruta_abre(servidor, metodo, ruta, cuerpo, headers):
    """El control que hace que los demás signifiquen algo: el guard está en las cinco."""
    r = getattr(servidor, metodo)(ruta, headers=headers, **({"json": cuerpo} if cuerpo else {}))
    assert r.status_code in (401, 403), (r.status_code, r.text)
    # Y no quedó nada escrito.
    assert [u["username"] for u in servidor.get(RUTA, headers=BACKOFFICE).json()] == [USUARIO]
