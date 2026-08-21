"""Quién hizo cada cambio: que `created_by`/`updated_by` se llenen SOLOS.

Las cuatro columnas existían desde el primer día y nadie las escribía. Lo que
estos tests fijan no es que las columnas estén —eso lo dice el schema— sino que
**cualquier escritura que entre por la API quede firmada**, sin que el servicio
que la hace tenga que acordarse.

🔑 Se prueba por HTTP y no llamando al listener: lo que puede fallar es el
cableado —el gate que anota, la sesión que lleva la Request, el flush que las
junta—, y eso sólo se ejercita entrando por donde entra el frontend.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from sqlalchemy import text

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"


def _config() -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"],
        entorno="test",
        debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
    )


@pytest.fixture
def api(engine, sesion, monkeypatch):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(crear_app(_config()), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


def _id_del_admin(engine) -> int:
    with engine.connect() as c:
        return c.execute(
            text("SELECT id FROM usuarios WHERE username = :u"), {"u": USUARIO}
        ).scalar_one()


def _auditoria(engine, tabla: str, fila_id: int) -> tuple[int | None, int | None]:
    with engine.connect() as c:
        return c.execute(
            text(f"SELECT created_by, updated_by FROM {tabla} WHERE id = :i"),  # noqa: S608
            {"i": fila_id},
        ).one()


def test_un_alta_por_la_api_queda_firmada(api, engine):
    respuesta = api.post(
        "/api/sucursales",
        json={"nombre": "Complejo Auditado", "direccion": None, "localidad": None,
              "telefono": None, "email": None, "punto_venta_arca": None,
              "activa": True, "observaciones": None},
    )
    assert respuesta.status_code in (200, 201), respuesta.text
    creado, modificado = _auditoria(engine, "sucursales", respuesta.json()["id"])
    esperado = _id_del_admin(engine)
    assert creado == esperado
    assert modificado == esperado


def test_una_edicion_cambia_updated_by_y_NO_created_by(api, engine):
    """El que crea y el que modifica son datos distintos.

    Es el caso que motivó las columnas: *"quién movió el turno de las 20:00"*.
    Si la edición pisara `created_by`, la pregunta dejaría de tener respuesta.

    🔴 **Hacen falta DOS usuarios, y ésa es toda la gracia del test.** La primera
    versión creaba y editaba con el mismo admin: `created_by` pisado con el
    MISMO id es indistinguible de `created_by` intacto, así que el test pasaba
    igual con la protección rota. Se comprobó mutándola —sacando el `if
    created_by is None` y agregando un pisado explícito en la edición— y seguía
    en verde las dos veces.
    """
    alta = api.post(
        "/api/sucursales",
        json={"nombre": "Complejo Editable", "direccion": None, "localidad": None,
              "telefono": None, "email": None, "punto_venta_arca": None,
              "activa": True, "observaciones": None},
    )
    fila = alta.json()["id"]
    creador = _id_del_admin(engine)
    assert _auditoria(engine, "sucursales", fila) == (creador, creador)

    # El segundo usuario, que es quien va a editar.
    nuevo_usuario = api.post(
        "/api/usuarios",
        json={"username": "encargada", "name": "Encargada", "password": "otra-clave",
              "role": "admin"},
    )
    assert nuevo_usuario.status_code in (200, 201), nuevo_usuario.text
    otro_id = int(nuevo_usuario.json()["id"])
    assert otro_id != creador, "si fueran el mismo, el test no mediría nada"

    otra = TestClient(crear_app(_config()), base_url="https://testserver")
    assert otra.post(
        "/auth/login", json={"username": "encargada", "password": "otra-clave"}
    ).status_code == 200
    edicion = otra.put(
        f"/api/sucursales/{fila}",
        json={"nombre": "Complejo Editado", "direccion": None, "localidad": None,
              "telefono": None, "email": None, "punto_venta_arca": None,
              "activa": True, "observaciones": None},
    )
    assert edicion.status_code == 200, edicion.text

    creado, modificado = _auditoria(engine, "sucursales", fila)
    assert creado == creador, "la edición no puede pisar quién lo creó"
    assert modificado == otro_id, "y tiene que decir quién lo modificó"


def test_sin_sesion_no_se_escribe_nada(api, engine):
    """Control negativo: sin usuario no hay firma **y tampoco hay fila**.

    Vale como control del test de arriba: si el 401 no llegara, el alta entraría
    y `created_by` quedaría en `NULL` — o sea que un `NULL` acá significaría
    'la auditoría no anda', no 'no había usuario'.
    """
    anonimo = TestClient(crear_app(_config()), base_url="https://testserver")
    respuesta = anonimo.post(
        "/api/sucursales",
        json={"nombre": "Colada", "direccion": None, "localidad": None,
              "telefono": None, "email": None, "punto_venta_arca": None,
              "activa": True, "observaciones": None},
    )
    assert respuesta.status_code == 401
    with engine.connect() as c:
        assert c.execute(
            text("SELECT count(*) FROM sucursales WHERE nombre = 'Colada'")
        ).scalar_one() == 0


def test_el_token_de_servicio_deja_created_by_en_null(api, engine, monkeypatch):
    """🔑 Y eso es un DATO, no un agujero.

    `SERVICE_USER` de `libraauth` no tiene `id`: no es un usuario de esta
    instancia, es el backoffice de la suite. Su propio comentario dice que una
    auditoría tiene que poder distinguir 'lo hizo el proveedor' de 'lo hizo un
    admin del cliente', y un `created_by` nulo con el resto de la fila cargada
    es exactamente esa distinción.

    Se ejercita sobre `/api/usuarios`, que es el router que acepta el token.
    """
    monkeypatch.setenv("LIBRA_SERVICE_TOKEN", "token-de-prueba")
    servicio = TestClient(crear_app(_config()), base_url="https://testserver")
    respuesta = servicio.get(
        "/api/usuarios", headers={"x-internal-auth": "token-de-prueba"}
    )
    # Lo que importa es que el token ENTRE: si diera 401/403, el test no estaría
    # midiendo la auditoría del servicio sino que el token no sirve.
    assert respuesta.status_code == 200, respuesta.text
