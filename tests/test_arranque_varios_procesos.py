"""El arranque de LibraClub con varios procesos (`uvicorn --workers N`; hoy N = 1).

El candado y sus 2 workers de verdad los prueba el motor (`libracore/tests/test_varios_procesos.py`). Lo que se cuida
acá es que **las siembras del arranque estén adentro del candado**: sin `una_vez_al_arrancar`, dos workers que
arrancan juntos contestan los dos «no existe» y crean el admin (o la caja de cada sucursal) dos veces.
"""

from __future__ import annotations

import contextlib

import pytest
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth

from app import main as principal
from tests.test_api import CLAVE, USUARIO, _config


@pytest.fixture
def base_de_auth(engine, sesion, monkeypatch):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    yield
    AuthBase.metadata.drop_all(engine)


def test_las_siembras_del_arranque_corren_adentro_de_una_vez_al_arrancar(base_de_auth, monkeypatch):
    eventos = []

    @contextlib.contextmanager
    def espia(nombre, **kw):
        eventos.append(("entra", nombre, kw.get("destino")))
        try:
            yield
        finally:
            eventos.append(("sale", nombre))

    monkeypatch.setattr(principal, "una_vez_al_arrancar", espia)
    monkeypatch.setattr(principal, "ensure_default_admin", lambda *a, **k: eventos.append("ensure_default_admin"))
    monkeypatch.setattr(principal, "ensure_demo_user", lambda *a, **k: eventos.append("ensure_demo_user"))

    config = _config()
    principal.crear_app(config)

    # Las cajas iniciales (`asegurar_cajas_de_todas`) sólo corren si la instancia factura: acá no hay base de LibraCore.
    assert eventos == [
        ("entra", "libraclub-sembrar", config.database_url), "ensure_default_admin", "ensure_demo_user",
        ("sale", "libraclub-sembrar"),
    ]
