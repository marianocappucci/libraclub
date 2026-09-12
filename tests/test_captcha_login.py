"""El captcha ALTCHA del login, cableado de verdad.

El resto de la suite corre con el captcha aprobado (fixture `_captcha_aprobado`
del conftest): el algoritmo lo prueba libraauth. Lo que es de ESTE producto, y
lo que fija este archivo, es el cableado:

1. Que `GET /auth/captcha` exista y devuelva un desafío con la forma que espera
   el widget de libra-ui (`parameters` + `signature`), sin caché.
2. 🔴 Que un login SIN captcha rebote con 400, aunque la contraseña sea buena.
   Si alguien sacara `captcha=True` de `app/routers/auth.py`, esto es lo que se
   pone rojo — el resto de la suite no lo mira.
3. Que forgot-password también lo exija: sin él, ese endpoint manda correos a
   pedido de cualquiera.
4. Que con un desafío resuelto se entre (el control: sin él, un login que
   rechazara todo pasaría el punto 2).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from libraauth.captcha import Captcha
from libraauth.models import Base as AuthBase
from libraauth.session_auth import CAPTCHA_INVALIDO

from app.main import crear_app
from tests.conftest import CAPTCHA_DE_ORIGINAL
from tests.test_api import CLAVE, USUARIO, _config


@pytest.fixture
def cliente(engine, sesion, monkeypatch):
    """Un cliente SIN sesión, con el captcha real de libraauth.

    `CAPTCHA_DE_ORIGINAL` deshace el doble del conftest. El `Captcha` que se
    deja en `app.state` es el real, sólo que barato —costo y contador mínimos—
    para que resolverlo tarde milisegundos y no el segundo que cuesta en el
    navegador. `https://testserver` por la cookie `Secure`, como en `test_api`.
    """
    monkeypatch.setattr("libraauth.session_auth._captcha_de", CAPTCHA_DE_ORIGINAL)
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    app = crear_app(_config())
    app.state.captcha = Captcha("clave-de-prueba", costo=1, contador_min=1, contador_rango=5)
    yield TestClient(app, base_url="https://testserver")
    AuthBase.metadata.drop_all(engine)


def test_el_desafio_tiene_la_forma_del_widget_y_no_se_cachea(cliente):
    r = cliente.get("/auth/captcha")
    assert r.status_code == 200, r.text
    desafio = r.json()
    assert isinstance(desafio.get("parameters"), dict)
    assert isinstance(desafio.get("signature"), str)
    assert "no-store" in r.headers.get("cache-control", "")


def test_login_sin_captcha_rebota_aunque_la_clave_sea_buena(cliente):
    r = cliente.post("/auth/login", json={"username": USUARIO, "password": CLAVE})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == CAPTCHA_INVALIDO


def test_forgot_password_sin_captcha_rebota(cliente):
    r = cliente.post("/auth/forgot-password", json={"identificador": USUARIO})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == CAPTCHA_INVALIDO


def test_login_con_el_desafio_resuelto_entra(cliente):
    from altcha import Challenge, Payload, solve_challenge

    desafio = Challenge.from_dict(cliente.get("/auth/captcha").json())
    solucion = Payload(desafio, solve_challenge(desafio)).to_base64()
    r = cliente.post(
        "/auth/login",
        json={"username": USUARIO, "password": CLAVE, "captcha": solucion},
    )
    assert r.status_code == 200, r.text
    # Y la sesión quedó abierta: no alcanza con el 200 del login.
    assert cliente.get("/auth/me").status_code == 200
