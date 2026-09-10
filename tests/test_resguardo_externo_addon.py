"""El add-on `resguardo_externo`: el enlace de la copia externa, detrás de su gate.

Lo que se fija acá es lo que decide este producto, no el motor —el flujo OAuth
lo prueba LibraCore—:

- que el router esté montado **detrás de `require_addon`**, y que el add-on
  venga **apagado**: sin fila en `modulos`, o con la fila en falso, 403;
- que el 403 sea también la respuesta cuando no se puede leer el estado —sin
  base de LibraCore, o sin la tabla—: la pantalla lo lee como "sin plan", y un
  500 lo mostraría como un error;
- que `plans.ADDONS` lo declare sin meterlo en ningún plan;
- y el contrato con el backoffice: `app.database.get_modulos` / `set_addon`,
  que el backoffice importa por `docker exec` adentro del contenedor.
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
ADDON = "resguardo_externo"
RUTA = "/api/config/resguardo-externo/enlace"


def _url_core() -> str:
    url = os.environ["DATABASE_URL"]
    base, _, nombre = url.rpartition("/")
    return f"{base}/{nombre}_core".replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture
def base_de_libracore():
    url = _url_core()
    servidor, _, nombre = url.rpartition("/")
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{nombre}"')
    yield url
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')


def _config(url_core: str | None, datos) -> Config:
    # `directorio_de_datos` propio por test: el enlace escribe en
    # `<datos>/backups/.resguardo/`, y un directorio compartido dejaría el
    # estado de un test a la vista del siguiente.
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos=str(datos), libracore_database_url=url_core,
    )


def _admin(config: Config) -> TestClient:
    cliente = TestClient(crear_app(config), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    return cliente


@pytest.fixture
def credenciales_de_admin(engine, sesion, monkeypatch):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    # Sin credenciales de proveedor: la lista de proveedores sale vacía, que es
    # lo que tiene cualquier servidor que todavía no registró la app de OAuth.
    for var in ("RESGUARDO_GDRIVE_CLIENT_ID", "RESGUARDO_GDRIVE_CLIENT_SECRET",
                "RESGUARDO_DROPBOX_APP_KEY", "RESGUARDO_DROPBOX_APP_SECRET"):
        monkeypatch.delenv(var, raising=False)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    yield
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def api(credenciales_de_admin, base_de_libracore, tmp_path):
    """Admin logueado, en una instancia CON base de LibraCore y sin tocar `modulos`."""
    return _admin(_config(base_de_libracore, tmp_path))


# ── a/b/c: el gate ───────────────────────────────────────────────────────────


def test_sin_fila_el_addon_viene_APAGADO(api):
    """a) Una instancia recién creada no tiene fila: el add-on está apagado."""
    from app.database import get_modulos

    # Control: que de verdad no haya fila. Sin esto, el 403 podría venir de una
    # fila en falso que dejó otro lado, y el test diría "sin fila" sin probarlo.
    assert ADDON not in get_modulos()

    r = api.get(RUTA)
    assert r.status_code == 403, r.text

    # 🔑 Las cuatro rutas, no sólo la lectura: el gate va en el MONTAJE, y un
    # router que se montara dos veces —o una ruta agregada después— tiene que
    # quedar igual de cerrado. El callback incluido.
    assert api.post(f"{RUTA}/drive").status_code == 403
    assert api.get(f"{RUTA}/callback").status_code == 403
    assert api.delete(RUTA).status_code == 403


def test_con_la_fila_en_falso_sigue_apagado(api):
    """b) Lo que deja el backoffice al destildarlo."""
    from app.database import get_modulos, set_addon

    set_addon(ADDON, False)
    assert get_modulos()[ADDON] is False  # control: la fila existe, en falso

    r = api.get(RUTA)
    assert r.status_code == 403, r.text


def test_prendido_contesta_el_estado_del_enlace(api):
    """c) Prendido, la pantalla recibe lo que necesita para dibujarse."""
    from app.database import set_addon

    set_addon(ADDON, True)
    r = api.get(RUTA)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert "proveedores" in cuerpo and "enlace" in cuerpo
    assert cuerpo["enlace"] is None, "una instancia recién prendida no está enlazada"

    # 🔑 Efecto inmediato, en los dos sentidos: el gate relee la tabla en cada
    # request. Si cacheara, apagarlo desde el backoffice no cortaría nada hasta
    # reiniciar el contenedor.
    set_addon(ADDON, False)
    assert api.get(RUTA).status_code == 403


# ── d: el rol ────────────────────────────────────────────────────────────────


def test_un_usuario_que_no_es_admin_no_entra(api, base_de_libracore, tmp_path):
    """d) El add-on prendido no le abre la puerta a cualquiera: sigue siendo de admin.

    🔴 Se prende ANTES de probar con el staff. Con el add-on apagado el 403 del
    staff saldría del gate del add-on y no del de rol, y el test pasaría con
    `require_admin` borrado del montaje.
    """
    from app.database import set_addon

    set_addon(ADDON, True)
    assert api.get(RUTA).status_code == 200  # control: el admin sí entra

    alta = api.post("/api/usuarios", json={
        "username": "mostrador-resguardo", "name": "Mostrador",
        "password": "clave-most", "role": "staff"})
    assert alta.status_code in (200, 201), alta.text

    config = _config(base_de_libracore, tmp_path)
    staff = TestClient(crear_app(config), base_url="https://testserver")
    assert staff.post("/auth/login", json={
        "username": "mostrador-resguardo", "password": "clave-most"}).status_code == 200
    assert staff.get(RUTA).status_code == 403

    anonimo = TestClient(crear_app(config), base_url="https://testserver")
    assert anonimo.get(RUTA).status_code in (401, 403)


# ── e: falla cerrado, con 403 y no con 500 ───────────────────────────────────


def test_sin_base_de_libracore_es_403_y_no_500(credenciales_de_admin, tmp_path):
    """e) Una instancia sin `LIBRACLUB_LIBRACORE_DATABASE_URL` no tiene de dónde
    leer el add-on. Para la pantalla eso es "sin plan", no un error."""
    api = _admin(_config(None, tmp_path))
    r = api.get(RUTA)
    assert r.status_code == 403, r.text


def test_sin_la_tabla_modulos_es_403_y_no_500(api, base_de_libracore):
    """e) La lectura falla —acá, porque falta la tabla— y el gate corta igual.

    🔑 Se prende primero y se comprueba el 200: así el 403 de después sólo
    puede venir de la falla de lectura, y no de una fila apagada.
    """
    from app.database import set_addon

    set_addon(ADDON, True)
    assert api.get(RUTA).status_code == 200  # control

    with psycopg.connect(base_de_libracore, autocommit=True) as c:
        c.execute("DROP TABLE modulos")

    r = api.get(RUTA)
    assert r.status_code == 403, r.text


# ── f: plans.py ──────────────────────────────────────────────────────────────


def test_resguardo_externo_es_un_addon_y_no_parte_de_un_plan():
    """f) Un add-on no se vende con el plan.

    Si entrara en un plan, subir o bajar de plan lo prendería o apagaría solo; y
    si entrara en `MODULOS`, rompería `set(MODULOS) == premium`, que es lo que
    fija `test_provisioning.py`.
    """
    import plans

    assert ADDON in plans.ADDONS
    assert ADDON not in plans.MODULOS
    assert ADDON not in plans.MODULO_LABELS
    for plan, modulos in plans.PLAN_MODULOS.items():
        assert ADDON not in modulos, f"el plan {plan!r} incluye el add-on"


# ── g: el contrato del backoffice ────────────────────────────────────────────


def test_el_backoffice_lee_lo_que_escribe(api):
    """g) `from app.database import get_modulos, set_addon`, que es textualmente
    lo que corre `libracore.admin.services` por `docker exec`."""
    from app.database import get_modulos, set_addon

    set_addon(ADDON, True)
    assert get_modulos()[ADDON] is True
    set_addon(ADDON, False)
    assert get_modulos()[ADDON] is False


def test_bajo_docker_exec_el_core_se_configura_solo(api, base_de_libracore, monkeypatch):
    """g) El caso real del backoffice: un proceso nuevo, sin `crear_app()`.

    Se simula dejando `libracore.db.core` sin configurar, con la variable del
    core en el entorno —como la tiene el contenedor—. 🔴 Tiene que ser la del
    CORE: la del dominio no tiene la tabla `modulos`.
    """
    from libracore.db import core as libracore_core

    from app.database import get_modulos, set_addon

    monkeypatch.setattr(libracore_core, "_db_path", None)
    monkeypatch.setattr(libracore_core, "_database_url", None)
    monkeypatch.setenv("LIBRACLUB_LIBRACORE_DATABASE_URL", base_de_libracore)
    assert not libracore_core.esta_configurado()  # control: de verdad sin configurar

    set_addon(ADDON, True)
    assert libracore_core.esta_configurado()
    assert get_modulos()[ADDON] is True


def test_bajo_docker_exec_sin_la_variable_falla_nombrandola(monkeypatch):
    """g) Sin base de LibraCore el backoffice tiene que ver un error que diga qué
    falta, no un `False` que parezca "apagado"."""
    from libracore.db import core as libracore_core

    from app.database import get_modulos

    monkeypatch.setattr(libracore_core, "_db_path", None)
    monkeypatch.setattr(libracore_core, "_database_url", None)
    monkeypatch.delenv("LIBRACLUB_LIBRACORE_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="LIBRACLUB_LIBRACORE_DATABASE_URL"):
        get_modulos()
