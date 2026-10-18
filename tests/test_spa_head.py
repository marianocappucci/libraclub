"""`HEAD` en la raíz y en la SPA: tiene que contestar como `GET`, sin cuerpo.

Los monitores de uptime (uptime-kuma) y algunos navegadores y proxies sondean
con `HEAD`. El catch-all estaba declarado con `@app.get`, y FastAPI **no**
deriva el `HEAD` del `GET` (Starlette sí, en sus rutas; `APIRoute` no): `HEAD /`
daba 405 con `Allow: GET` y una instancia sana figuraba caída.

Se prueba `montar_spa`, la función que llama `app/asgi.py`, sobre una `FastAPI`
limpia y un `dist` de mentira: importar `app.asgi` ejecuta `crear_app()`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.spa import SIN_CACHE, montar_spa


@pytest.fixture
def cliente(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<html>spa</html>")
    (tmp_path / "manifest.webmanifest").write_text("{}")
    app = FastAPI()
    montar_spa(app, tmp_path)
    return TestClient(app)


@pytest.mark.parametrize("ruta", ["/", "/reservas", "/torneos/3", "/manifest.webmanifest"])
def test_head_responde_como_get_y_sin_cuerpo(cliente, ruta):
    get = cliente.get(ruta)
    head = cliente.head(ruta)
    assert get.status_code == 200
    assert head.status_code == 200, f"HEAD {ruta} dio {head.status_code} (Allow: {head.headers.get('allow')})"
    assert head.content == b""
    assert head.headers["content-type"] == get.headers["content-type"]
    assert head.headers["cache-control"] == SIN_CACHE


def test_head_de_una_ruta_de_api_inexistente_sigue_siendo_404(cliente):
    """El control: HEAD no abre un camino por el que la API devuelva el `index.html`."""
    assert cliente.get("/api/lo-que-sea").status_code == 404
    assert cliente.head("/api/lo-que-sea").status_code == 404


def test_otros_metodos_siguen_sin_entrar_a_la_spa(cliente):
    """Sólo `GET` y `HEAD`: un `POST` a una ruta de la SPA sigue dando 405."""
    assert cliente.post("/reservas").status_code == 405


@pytest.mark.parametrize("ruta", ["/salud", "/health"])
def test_la_sonda_de_salud_tambien_contesta_head(ruta):
    """Un monitor que sondea `/health` con `HEAD` recibía 405 aunque la base anduviera."""
    from app.db import obtener_sesion
    from app.routers import salud

    class _Sesion:
        def execute(self, *_):
            return None

    app = FastAPI()
    app.include_router(salud.router)
    app.dependency_overrides[obtener_sesion] = lambda: _Sesion()
    cliente = TestClient(app)
    assert cliente.get(ruta).status_code == 200
    head = cliente.head(ruta)
    assert head.status_code == 200, f"HEAD {ruta} dio {head.status_code}"
    assert head.content == b""
