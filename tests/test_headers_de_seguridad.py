"""Los headers de seguridad, montados en ESTE producto.

El middleware vive en libracore y ya tiene sus propios tests. Lo que este
archivo cuida es que **esté cableado acá**. Es la diferencia que se cobró caro
en septiembre: el middleware existía desde antes y seis de los ocho productos no
lo montaban, así que la política estaba escrita y no se aplicaba a nadie.

El cliente se arma acá y no se toma de `conftest.py` porque este repo no tiene
una fixture de cliente HTTP compartida — la de `test_api.py` es local a ese
módulo. Se replica su construcción, sin login: el middleware envuelve todas las
respuestas, así que un 401 sirve igual que un 200.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from libracore.security_headers import CSP, CSP_SPA

from app.config import Config
from app.main import crear_app


@pytest.fixture
def http(engine, sesion, monkeypatch):
    # `crear_app` no levanta sin una contrasena de admin inicial —
    # `libraauth.bootstrap` lo exige a proposito, para que una instancia no nazca
    # con un admin sin clave. La fixture de `test_api.py` hace lo mismo.
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", "clave-de-prueba")
    cfg = Config(
        database_url=os.environ["DATABASE_URL"],
        entorno="test",
        debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
    )
    return TestClient(crear_app(cfg), base_url="https://testserver")


def test_las_respuestas_traen_los_headers_de_seguridad(http):
    r = http.get("/health")
    assert r.headers["Content-Security-Policy"] == CSP_SPA
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "geolocation=()" in r.headers["Permissions-Policy"]
    assert "includeSubDomains" in r.headers["Strict-Transport-Security"]


def test_es_la_politica_de_SPA_y_no_la_de_las_apps_Jinja(http):
    csp = http.get("/health").headers["Content-Security-Policy"]
    assert "jsdelivr" not in csp
    assert "jsdelivr" in CSP, "control positivo: la de Jinja sí lo tiene"
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


def test_tambien_en_una_respuesta_de_error(http):
    """El middleware se agrega último para quedar más externo. Si estuviera
    adentro, una ruta inexistente saldría sin headers."""
    r = http.get("/una-ruta-que-no-existe-en-ningun-producto")
    assert r.headers["Content-Security-Policy"] == CSP_SPA
