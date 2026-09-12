"""El captcha y el bloqueo por intentos fallidos del portal, cableados de verdad.

🔴 El resto de `test_portal.py` corre con el captcha aprobado (fixture
`_captcha_aprobado`, autouse, en `tests/conftest.py`): el algoritmo lo prueba
libraauth. Lo que es de ESTE producto, y lo que fija este archivo —igual que
`test_captcha_login.py` para `/auth`—, es el cableado:

1. Que `/api/portal/login` y `/api/portal/registro` exijan el captcha, y que
   uno que falta o no vale NO sume intento fallido.
2. Que el bloqueo por intentos fallidos —la MISMA cuenta que usa `/auth/login`,
   por IP, sobre `auth_log`— también corte estas dos rutas, y que corte ANTES
   del captcha.
3. Que lo que se anota en `auth_log` diga `detalle="portal"` y traiga la IP.

Comparten el `Captcha` de proceso con `/auth`: `GET /auth/captcha` es el único
desafío que existe, y sirve para las dos superficies.
"""

from __future__ import annotations

import os

import pytest
from altcha import Challenge, Payload, solve_challenge
from fastapi.testclient import TestClient
from libraauth.captcha import Captcha
from libraauth.models import AuthEvent
from libraauth.models import Base as AuthBase
from libraauth.session_auth import CAPTCHA_INVALIDO
from sqlalchemy import select

from app.config import Config
from app.main import crear_app
from app.routers.portal import DETALLE_PORTAL, EVENTO_REGISTRO_PORTAL, MAXIMO_INTENTOS_FALLIDOS
from tests.conftest import CAPTCHA_DE_ORIGINAL

MAIL, PASS = "jugador@ejemplo.com", "una-clave-larga"


def _config() -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos-captcha", libracore_database_url=None,
    )


@pytest.fixture
def api(engine, sesion, monkeypatch):
    """Un cliente con el captcha REAL de libraauth, barato (como en
    `test_captcha_login.py`): costo y contador mínimos para que resolverlo
    tarde milisegundos y no el segundo que cuesta en el navegador.
    """
    monkeypatch.setattr("libraauth.session_auth._captcha_de", CAPTCHA_DE_ORIGINAL)
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", "clave-de-prueba")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    app = crear_app(_config())
    app.state.captcha = Captcha("clave-de-prueba", costo=1, contador_min=1, contador_rango=5)
    yield TestClient(app, base_url="https://testserver")
    AuthBase.metadata.drop_all(engine)


def _resolver_captcha(api) -> str:
    """La solución de un desafío nuevo. Cada una sirve una sola vez
    (anti-replay): hay que pedir una por intento."""
    desafio = Challenge.from_dict(api.get("/auth/captcha").json())
    return Payload(desafio, solve_challenge(desafio)).to_base64()


def _registrar(api, mail=MAIL, password=PASS, nombre="Juan Jugador"):
    return api.post("/api/portal/registro", json={
        "email": mail, "password": password, "nombre": nombre, "telefono": "111",
        "captcha": _resolver_captcha(api),
    })


def _eventos(sesion) -> list[dict]:
    """Los eventos de `auth_log`, como dicts —no como instancias ORM—, escritos
    por la sesión propia del ENDPOINT (no por ésta), con su propio commit.

    🔑 Dos trampas de la misma transacción, encadenadas:

    1. Sin cerrar la transacción de lectura de ESTA sesión, el teardown de
       `api` (`AuthBase.metadata.drop_all(engine)`) se queda esperando para
       siempre el lock que esa transacción sostiene sobre `auth_log` — y como
       `api` depende de `sesion`, su teardown corre ANTES que el de `sesion`,
       así que nadie lo libera. Por eso el `sesion.rollback()` de abajo.
    2. Pero `rollback()` (a diferencia de `commit()`) SIEMPRE expira los
       objetos de la sesión, sin importar `expire_on_commit`. Si esto
       devolviera las instancias `AuthEvent` y el test leyera `.detalle`
       DESPUÉS del rollback, ese acceso dispara un refresh —una consulta
       nueva por `id`— que abre otra transacción sin cerrar, y la sesión
       vuelve a quedar exactamente en el mismo problema. Por eso acá se arma
       el dict ANTES del rollback: son valores planos, no instancias vivas.

    Verificado: sin el rollback, o devolviendo las instancias en vez de
    dicts, la suite se cuelga en el primer test que llama a `_eventos`.
    """
    filas = sesion.execute(select(AuthEvent).order_by(AuthEvent.id)).scalars().all()
    datos = [
        {"evento": f.evento, "username": f.username, "ip": f.ip, "detalle": f.detalle}
        for f in filas
    ]
    sesion.rollback()
    return datos


# ── El captcha ─────────────────────────────────────────────────────────────


def test_login_sin_captcha_rebota_y_no_suma_fallido(api, sesion):
    _registrar(api)

    sin_captcha = api.post("/api/portal/login", json={"email": MAIL, "password": PASS})
    assert sin_captcha.status_code == 400, sin_captcha.text
    assert sin_captcha.json()["detail"] == CAPTCHA_INVALIDO

    # 🔑 Si el 400 de arriba hubiera sumado un intento fallido, repetirlo
    # `MAXIMO_INTENTOS_FALLIDOS` veces más bloquearía el intento bueno de abajo.
    for _ in range(MAXIMO_INTENTOS_FALLIDOS + 2):
        rebote = api.post("/api/portal/login", json={"email": MAIL, "password": PASS})
        assert rebote.status_code == 400, rebote.text

    bueno = api.post("/api/portal/login", json={
        "email": MAIL, "password": PASS, "captcha": _resolver_captcha(api),
    })
    assert bueno.status_code == 200, bueno.text

    eventos = [e["evento"] for e in _eventos(sesion)]
    assert "login_fallido" not in eventos, eventos
    assert "login_bloqueado" not in eventos, eventos


def test_registro_sin_captcha_rebota_y_no_crea_la_cuenta(api, sesion):
    sin_captcha = api.post("/api/portal/registro", json={
        "email": MAIL, "password": PASS, "nombre": "Juan Jugador", "telefono": "111",
    })
    assert sin_captcha.status_code == 400, sin_captcha.text
    assert sin_captcha.json()["detail"] == CAPTCHA_INVALIDO
    # El 400 del captcha no dejó nada en `auth_log`: ni el intento fallido, ni
    # el evento propio del alta.
    assert _eventos(sesion) == []

    # La cuenta no existe: entrar con la clave que se iba a usar da 401 (mismo
    # mensaje que "no existe"), no 200.
    con_captcha = api.post("/api/portal/login", json={
        "email": MAIL, "password": PASS, "captcha": _resolver_captcha(api),
    })
    assert con_captcha.status_code == 401, con_captcha.text

    # Y lo único que quedó anotado es el fallido de ESTE login (la cuenta no
    # existe), no algo del registro que el captcha ya había rechazado.
    eventos = _eventos(sesion)
    assert len(eventos) == 1, eventos
    assert eventos[0]["evento"] == "login_fallido"


def test_registro_con_el_captcha_resuelto_crea_la_cuenta(api):
    r = _registrar(api)
    assert r.status_code == 201, r.text
    assert r.json()["email"] == MAIL


# ── El bloqueo por intentos fallidos (mismo mecanismo que /auth/login) ──────


def test_tras_N_fallidos_bloquea_aunque_la_clave_sea_correcta(api, sesion):
    _registrar(api)

    for _ in range(MAXIMO_INTENTOS_FALLIDOS):
        malo = api.post("/api/portal/login", json={
            "email": MAIL, "password": "no-es-la-clave", "captcha": _resolver_captcha(api),
        })
        assert malo.status_code == 401, malo.text

    # La clave es la correcta y el captcha ni siquiera se manda: si esto diera
    # 400 (captcha inválido) en vez de 429, el bloqueo NO estaría cortando
    # antes que el captcha, que es justo el orden que exige el enunciado.
    bloqueado = api.post("/api/portal/login", json={"email": MAIL, "password": PASS})
    assert bloqueado.status_code == 429, bloqueado.text
    assert "Demasiados intentos fallidos" in bloqueado.json()["detail"]

    eventos = [e["evento"] for e in _eventos(sesion)]
    assert eventos.count("login_fallido") == MAXIMO_INTENTOS_FALLIDOS, eventos
    assert eventos.count("login_bloqueado") == 1, eventos


def test_el_bloqueo_tambien_corta_el_registro(api, sesion):
    """Una IP bloqueada no registra cuentas tampoco (mismo corte que el login)."""
    _registrar(api)
    for _ in range(MAXIMO_INTENTOS_FALLIDOS):
        api.post("/api/portal/login", json={
            "email": MAIL, "password": "no-es-la-clave", "captcha": _resolver_captcha(api),
        })

    bloqueado = api.post("/api/portal/registro", json={
        "email": "otro@ejemplo.com", "password": PASS, "nombre": "Otro",
        "captcha": _resolver_captcha(api),
    })
    assert bloqueado.status_code == 429, bloqueado.text


# ── Lo que queda anotado en `auth_log` ──────────────────────────────────────


def test_el_fallido_queda_en_auth_log_con_detalle_portal_y_la_ip(api, sesion):
    _registrar(api)
    api.post("/api/portal/login", json={
        "email": MAIL, "password": "no-es-la-clave", "captcha": _resolver_captcha(api),
    })

    fallidos = [e for e in _eventos(sesion) if e["evento"] == "login_fallido"]
    assert len(fallidos) == 1, fallidos
    assert fallidos[0]["detalle"] == DETALLE_PORTAL
    assert fallidos[0]["username"] == MAIL
    assert fallidos[0]["ip"]  # TestClient: "testclient", pero no vacío.


def test_el_login_bueno_anota_login_con_detalle_portal(api, sesion):
    _registrar(api)
    ok = api.post("/api/portal/login", json={
        "email": MAIL, "password": PASS, "captcha": _resolver_captcha(api),
    })
    assert ok.status_code == 200, ok.text

    logins = [e for e in _eventos(sesion) if e["evento"] == "login"]
    assert len(logins) == 1, logins
    assert logins[0]["detalle"] == DETALLE_PORTAL
    assert logins[0]["username"] == MAIL


def test_el_alta_anota_un_evento_propio_y_no_login(api, sesion):
    """🔴 Nadie probó una contraseña en un alta: no es un `login`."""
    _registrar(api)

    eventos = _eventos(sesion)
    assert len(eventos) == 1, eventos
    assert eventos[0]["evento"] == EVENTO_REGISTRO_PORTAL
    assert eventos[0]["detalle"] == DETALLE_PORTAL
    assert eventos[0]["username"] == MAIL
    assert eventos[0]["evento"] != "login"
