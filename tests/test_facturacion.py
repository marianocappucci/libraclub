"""La configuración de ARCA, y la base de LibraCore que la sostiene.

Todavía no se emite ningún comprobante: lo que estos tests fijan es el
**cableado** —que la base de LibraCore sea la suya y no la del dominio, que la
config persista, y que una instancia sin configurar lo diga en vez de romperse—.

🔴 La separación de bases es lo que más importa acá y lo que peor falla:
`init_core_schema()` crea `usuarios` y `auth_log`, que este producto ya tiene con
la forma de `libraauth`. Compartiendo base **nada falla en el arranque** y el
problema aparece meses después, en la primera factura.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"


def _url_core() -> str:
    """La URL de la base de LibraCore para los tests, derivada de la del dominio.

    Se deriva en vez de pedir otra variable para que corra igual en el CI y en
    cualquier máquina: es el mismo servidor, otra base.
    """
    url = os.environ["DATABASE_URL"]
    base, _, nombre = url.rpartition("/")
    return f"{base}/{nombre}_core".replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture
def base_de_libracore():
    """Crea la base de LibraCore y la deja vacía. La borra al terminar."""
    url = _url_core()
    servidor, _, nombre = url.rpartition("/")
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{nombre}"')
    yield url
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')


def _config(url_core: str | None) -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"],
        entorno="test",
        debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
        libracore_database_url=url_core,
    )


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(
        crear_app(_config(base_de_libracore)), base_url="https://testserver"
    )
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


ARCA = {
    "cuit": "30712345679", "punto_venta": 3,
    "certificado_path": "/datos/arca_certs/cert.pem",
    "clave_path": "/datos/arca_certs/clave.key",
    "ambiente": "homologacion",
}


def test_la_config_de_arca_se_guarda_y_se_relee(api):
    assert api.get("/config/arca").json() is None, "arranca sin configurar"

    guardado = api.put("/config/arca", json=ARCA)
    assert guardado.status_code == 200, guardado.text

    # Se relee del servidor y no se mira la respuesta del PUT: lo que se prueba
    # es que persistió, no que el endpoint devolvió lo que le mandaron.
    leido = api.get("/config/arca").json()
    assert leido["cuit"] == ARCA["cuit"]
    assert leido["punto_venta"] == ARCA["punto_venta"]
    assert leido["ambiente"] == "homologacion"


def test_el_ambiente_por_default_es_homologacion(api):
    """🔑 Una instancia recién configurada no puede emitir contra producción.

    Pasar a `produccion` tiene que ser un acto deliberado, no lo que ocurre si
    alguien deja el campo como vino.
    """
    sin_ambiente = {k: v for k, v in ARCA.items() if k != "ambiente"}
    api.put("/config/arca", json=sin_ambiente)
    assert api.get("/config/arca").json()["ambiente"] == "homologacion"


def test_las_tablas_de_libracore_NO_caen_en_la_base_del_dominio(api, engine):
    """El choque que motivó las dos bases.

    `arca_config` tiene que existir del lado de LibraCore y **no** del lado del
    dominio. El control positivo —que exista de un lado— es lo que hace que el
    negativo signifique algo: sin él, "no está en el dominio" se cumpliría
    también si el schema no se hubiera creado en ningún lado.
    """
    from sqlalchemy import text

    with engine.connect() as c:
        en_dominio = c.execute(
            text("SELECT count(*) FROM pg_tables WHERE tablename = 'arca_config'")
        ).scalar_one()
    assert en_dominio == 0, "arca_config no puede estar en la base del dominio"

    # Control positivo: del lado de LibraCore sí está, y responde.
    assert api.put("/config/arca", json=ARCA).status_code == 200


def test_una_instancia_sin_base_de_libracore_lo_DICE(engine, sesion, monkeypatch):
    """503 nombrando la variable que falta, no un 500 genérico.

    Sin esto el síntoma en la pantalla es idéntico al de cualquier otro error, y
    nadie sabría que lo que hay que hacer es agregar una variable de entorno.
    """
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(crear_app(_config(None)), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200

    r = cliente.get("/config/arca")
    assert r.status_code == 503, r.text
    assert "LIBRACLUB_LIBRACORE_DATABASE_URL" in r.text
    AuthBase.metadata.drop_all(engine)


def test_una_url_que_no_es_postgres_no_se_acepta(monkeypatch):
    """Misma regla que la base del dominio: PostgreSQL es el único motor."""
    monkeypatch.setenv("DATABASE_URL", os.environ["DATABASE_URL"])
    monkeypatch.setenv("LIBRACLUB_LIBRACORE_DATABASE_URL", "sqlite:///core.db")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Config.desde_entorno()
