"""El registro de errores de la familia, montado en ESTE producto (ADR-045 de libracore).

El handler, el `ref`, la limpieza y el archivo los prueba el motor (`tests/test_errores.py`). Lo que se cuida acá es
que **esté cableado**: sin la línea `instalar_registro_de_errores(app, "libraclub")` en `crear_app()` un 500 sigue
yendo sólo al stdout de uvicorn y se pierde en cada recreate del contenedor, y el navegador no tiene a dónde mandar
los suyos (`POST /api/errores-cliente`). Si alguien la saca, los dos tests dan rojo.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from libracore import errores

from app.main import crear_app
from tests.test_api import CLAVE, USUARIO, _config


@pytest.fixture
def app_(engine, sesion, monkeypatch):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    yield crear_app(_config())
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def carpeta_de_errores(tmp_path, monkeypatch):
    """El JSONL a un directorio propio del test y el cache de manejadores vacío (como en los tests del motor)."""
    monkeypatch.setenv("LIBRA_ERRORES_DIR", str(tmp_path / "errores"))
    monkeypatch.setenv("LIBRA_INSTANCIA", "libraclub-test")
    monkeypatch.setenv("LIBRA_ENTORNO", "dev")
    monkeypatch.setattr(errores, "_manejadores", {})
    return tmp_path / "errores"


def _lineas(carpeta):
    archivo = carpeta / "errores.jsonl"
    if not archivo.exists():
        return []
    return [json.loads(x) for x in archivo.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_una_ruta_que_lanza_da_500_con_ref_y_deja_una_linea(app_, carpeta_de_errores):
    def explota():
        raise RuntimeError("falla de prueba")

    app_.add_api_route("/api/__falla_de_prueba", explota)
    # `raise_server_exceptions=False`: el TestClient por defecto relanza la excepción que el handler ya contestó.
    cliente = TestClient(app_, base_url="https://testserver", raise_server_exceptions=False)

    r = cliente.get("/api/__falla_de_prueba")

    assert r.status_code == 500
    cuerpo = r.json()
    assert cuerpo["detail"] == "Error interno"
    assert len(cuerpo["ref"]) == 8
    (linea,) = _lineas(carpeta_de_errores)
    assert linea["ref"] == cuerpo["ref"], "el ref que ve el usuario es el de la línea"
    assert linea["producto"] == "libraclub"
    assert linea["instancia"] == "libraclub-test" and linea["entorno"] == "dev"
    assert linea["tipo"] == "RuntimeError" and linea["status"] == 500 and linea["origen"] == "servidor"


def test_el_navegador_reporta_sin_sesion_y_queda_la_linea(app_, carpeta_de_errores):
    """`POST /api/errores-cliente` es público a propósito (un error del login también importa) y lo monta la misma
    línea."""
    r = TestClient(app_, base_url="https://testserver").post("/api/errores-cliente", json={
        "tipo": "error", "mensaje": "x is undefined", "stack": "TypeError: x\n    at f (/assets/index-abc.js:1:2)",
        "pagina": "/reservas/12/editar", "release": "dev",
    })

    assert r.status_code == 204
    (linea,) = _lineas(carpeta_de_errores)
    assert linea["origen"] == "cliente" and linea["producto"] == "libraclub"
    assert linea["ruta"] == "/reservas/:id/editar"
