"""Los secretos de `config.json` viven cifrados, no en el archivo (2026-09-17).

**Estos tests miran el `config.json` CRUDO y la tabla en la base**, no lo que
devuelve `config_manager.load()`. Es a proposito: `load()` devuelve el secreto
en claro por diseño —para que los consumidores no cambien— asi que un assert
sobre `load()` da verde igual con la implementacion vieja, la que escribia el
token en el archivo. Lo unico que distingue una de otra es que quedo en el
disco.

Y se mide a traves del enganche REAL del producto (`app.main.crear_app`), no
armando un almacen a mano: lo que este archivo fija es que LibraClub lo haya
enchufado, que es la mitad que LibraCore no puede garantizar. El almacen queda
expuesto en `app.state.secretos` — ver el comentario en `app/main.py`.
"""
from __future__ import annotations

import json

import pytest
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from sqlalchemy import text

from app.main import crear_app, migrar_secretos
from tests.test_api import CLAVE, USUARIO, _config

TOKEN = "APP_USR-1234567890123456-091712-abcdef0123456789-3392230021"


def _crudo(config_path):
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def _escribir_crudo(config_path, datos):
    """Escribe el archivo como lo dejaba la version vieja, sin pasar por
    `save()` —que ya enruta al almacen y no dejaria el secreto en el archivo—.
    """
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(datos, f)


def _filas_de_secretos(engine):
    with engine.connect() as c:
        return dict(c.execute(text("select clave, valor_cifrado from secretos_instancia")).all())


@pytest.fixture
def api(engine, sesion, monkeypatch, tmp_path):
    """Un cliente ya logueado, con la app real de LibraClub y `config.json`
    aislado en `tmp_path` (mismo criterio que `_config_de_libracore_aislada`
    del conftest, pero apuntando explicitamente al archivo de ESTE test).

    Depende de `sesion` por su limpieza y de `engine` porque hace falta la
    tabla `secretos_instancia`, que crea la revision `0002` de la cadena de
    libraauth via `crear_schema_de_auth` — no un `create_all`.
    """
    from libracore import config_manager as lc_config_manager

    config_path = str(tmp_path / "config.json")
    monkeypatch.setattr(lc_config_manager, "CONFIG_PATH", config_path)
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    cliente_app = crear_app(_config())
    from fastapi.testclient import TestClient

    cliente = TestClient(cliente_app, base_url="https://testserver")
    respuesta = cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    )
    assert respuesta.status_code == 200, respuesta.text
    cliente.config_path = config_path
    yield cliente
    AuthBase.metadata.drop_all(engine)


def test_el_producto_enchufo_el_almacen(api):
    """Sin esto, todo lo demas es la implementacion vieja: `config_manager` sin
    almacen escribe el secreto en el JSON, exactamente como antes."""
    from libracore import config_manager as lc_config_manager

    assert lc_config_manager.almacen_de_secretos() is api.app.state.secretos


def test_guardar_el_token_no_lo_deja_en_el_archivo(api):
    from libracore import config_manager as lc_config_manager

    cfg = lc_config_manager.load()
    cfg["mp_access_token"] = TOKEN
    cfg["empresa_nombre"] = "Complejo de prueba"
    lc_config_manager.save(cfg)

    crudo = _crudo(api.config_path)
    assert crudo["mp_access_token"] == ""
    # Control positivo del mismo barrido: lo que no es secreto si quedo escrito.
    assert crudo["empresa_nombre"] == "Complejo de prueba"
    # Y para los consumidores no cambio nada.
    assert lc_config_manager.load()["mp_access_token"] == TOKEN


def test_en_la_base_tampoco_esta_en_claro(api, engine):
    from libracore import config_manager as lc_config_manager

    cfg = lc_config_manager.load()
    cfg["mp_access_token"] = TOKEN
    lc_config_manager.save(cfg)

    filas = _filas_de_secretos(engine)
    assert "mp_access_token" in filas
    assert TOKEN not in filas["mp_access_token"]
    assert filas["mp_access_token"].startswith("v1:")


def test_el_arranque_migra_lo_que_la_version_vieja_dejo_en_el_archivo(api):
    """🔑 El caso de las instancias vivas: el archivo tiene los secretos en
    claro, se despliega esta version, y el arranque (`migrar_secretos`) los
    mueve solo."""
    from libracore import config_manager as lc_config_manager

    _escribir_crudo(api.config_path, {
        "empresa_nombre": "Complejo de prueba",
        "mp_access_token": TOKEN,
        "mp_webhook_secret": "firma-del-webhook",
        "email_smtp_password": "la-contrasena",
    })
    assert _crudo(api.config_path)["mp_access_token"] == TOKEN  # el punto de partida

    informe = migrar_secretos()

    assert sorted(informe["migradas"]) == [
        "email_smtp_password", "mp_access_token", "mp_webhook_secret",
    ]
    crudo = _crudo(api.config_path)
    for clave in lc_config_manager.CLAVES_SECRETAS:
        assert crudo[clave] == "", f"{clave} sigue en el archivo"
    assert crudo["empresa_nombre"] == "Complejo de prueba"
    assert lc_config_manager.load()["mp_access_token"] == TOKEN
    assert lc_config_manager.load()["mp_webhook_secret"] == "firma-del-webhook"


def test_la_migracion_es_idempotente(api, engine):
    _escribir_crudo(api.config_path, {"mp_access_token": TOKEN})
    migrar_secretos()
    antes = _filas_de_secretos(engine)["mp_access_token"]

    informe = migrar_secretos()

    assert informe == {"migradas": [], "ya_estaban": [], "fallaron": {}}
    # No se reescribio: el blob es el mismo, con el mismo nonce.
    assert _filas_de_secretos(engine)["mp_access_token"] == antes


def test_el_arranque_de_la_app_corre_la_migracion(engine, sesion, monkeypatch, tmp_path):
    """El enganche en `crear_app()` y no solo la funcion: sin la llamada, la
    migracion existe y nadie la corre."""
    from libracore import config_manager as lc_config_manager

    config_path = str(tmp_path / "config.json")
    monkeypatch.setattr(lc_config_manager, "CONFIG_PATH", config_path)
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)

    _escribir_crudo(config_path, {"mp_access_token": TOKEN})
    crear_app(_config())  # el arranque real, sin pasar por `migrar_secretos()` a mano

    assert _crudo(config_path)["mp_access_token"] == ""
    assert lc_config_manager.load()["mp_access_token"] == TOKEN

    AuthBase.metadata.drop_all(engine)


def test_config_no_secreta_mp_auto_facturar_reservas_sobrevive_la_migracion(api):
    """`mp_auto_facturar_reservas` no es un secreto —es el interruptor de
    facturacion automatica del cobro por QR, ver `app/servicios/cobro_qr.py`—
    y la migracion de libracore reescribe el JSON crudo. Confirma que no se
    pierde en el camino."""
    from libracore import config_manager as lc_config_manager

    _escribir_crudo(api.config_path, {
        "mp_access_token": TOKEN,
        "mp_auto_facturar_reservas": True,
    })

    migrar_secretos()

    assert lc_config_manager.load()["mp_auto_facturar_reservas"] is True
