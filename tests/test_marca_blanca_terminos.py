"""Con marca propia la instancia exige los Terminos del revendedor y nunca cae a los de la familia (libraauth ADR-030).

🔴 Se marca `sin_aceptar_terminos` para que el gate corte de verdad. Es lo que se pondria rojo si alguien sacara
`contrato_propio` o `exigir_propio` de `TerminosRepository(...)` en `app/main.py`: el producto seguiria andando y una
instancia de revendedor aceptaria los terminos de Libra en silencio.
"""
import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from libracore import config_manager

from app.config import Config
from app.main import crear_app

pytestmark = pytest.mark.sin_aceptar_terminos

USUARIO, CLAVE = "admin", "clave-de-prueba"
TEXTO = "Terminos del revendedor, version de prueba.\n"


@pytest.fixture(autouse=True)
def _marca_propia_del_test(tmp_path, monkeypatch):
    monkeypatch.setattr(config_manager, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(config_manager, "MARCA_DIR", str(tmp_path / "marca"))


@pytest.fixture
def logueado(engine, sesion, monkeypatch, base_de_libracore, tmp_path):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    cfg = Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos=str(tmp_path), libracore_database_url=base_de_libracore,
    )
    cliente = TestClient(crear_app(cfg), base_url="https://testserver")
    assert cliente.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


def _marca_propia() -> None:
    cfg = config_manager.load()
    cfg["marca"] = {"nombre": "Club Modelo"}
    config_manager.save(cfg)


def _terminos_propios() -> None:
    cfg = config_manager.load()
    cfg["terminos_propios"] = {"version": "rev-1.0", "vigente_desde": "01-01-2026"}
    config_manager.save(cfg)
    os.makedirs(config_manager.MARCA_DIR, exist_ok=True)
    with open(os.path.join(config_manager.MARCA_DIR, "terminos.md"), "w", encoding="utf-8", newline="") as f:
        f.write(TEXTO)


def test_sin_marca_propia_rigen_los_terminos_de_la_familia(logueado):
    estado = logueado.get("/terminos").json()
    assert estado["pendiente"] is True
    assert estado["version"] != "rev-1.0"


def test_con_marca_propia_y_sin_terminos_propios_la_instancia_queda_frenada(logueado):
    _marca_propia()
    r = logueado.get("/api/usuarios")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "terminos_pendientes"
    # Nadie puede aceptar nada: no hay contrato, ni siquiera el de la familia.
    estado = logueado.get("/terminos").json()
    assert estado["sin_contrato"] is True
    aceptar = logueado.post("/terminos/aceptar", json={"version": "1.0", "hash_texto": "0" * 64})
    assert aceptar.status_code >= 400
    assert logueado.get("/api/usuarios").status_code == 403


def test_con_terminos_propios_se_acepta_el_contrato_del_revendedor(logueado):
    _marca_propia()
    _terminos_propios()
    estado = logueado.get("/terminos").json()
    assert estado["version"] == "rev-1.0"
    assert estado["pendiente"] is True
    r = logueado.post("/terminos/aceptar", json={"version": estado["version"], "hash_texto": estado["hash_texto"]})
    assert r.status_code == 200, r.text
    assert logueado.get("/api/usuarios").status_code == 200
