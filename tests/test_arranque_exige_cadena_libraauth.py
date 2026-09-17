"""El arranque exige la cadena de LibraAuth en vez de crear las tablas.

Desde libraauth v0.45 (2026-09-17) `crear_app()` ya no corre
`AuthBase.metadata.create_all()`: llama a `exigir_schema_al_dia`. Se fija que
sin la cadena la app no arranca y el error nombra el comando que declara
`scripts/panel_admin.py`, con el control de que con la cadena sí arranca.
"""
import re
from pathlib import Path

import pytest
from libraauth.migrar import TABLA_DE_VERSION, SchemaDesactualizado
from libraauth.testing import crear_schema_de_auth
from sqlalchemy import text

from app.main import crear_app

RAIZ = Path(__file__).resolve().parent.parent
COMANDO = "libraauth-migrar upgrade --prefijo libraclub --base dominio"


def test_sin_la_cadena_la_app_no_arranca_y_dice_el_comando(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    crear_schema_de_auth(engine)
    with engine.begin() as c:
        c.execute(text(f"DROP TABLE {TABLA_DE_VERSION}"))
    try:
        with pytest.raises(SchemaDesactualizado) as e:
            crear_app(sembrar_admin=False)
        assert COMANDO in str(e.value)
    finally:
        crear_schema_de_auth(engine)


def test_la_guarda_usa_el_comando_que_declara_el_deploy():
    fuente = (RAIZ / "scripts" / "panel_admin.py").read_text(encoding="utf-8")
    declarado = re.search(r'\("libraauth-migrar",([^)]*)\)', fuente)
    assert declarado, "scripts/panel_admin.py no declara libraauth-migrar"
    partes = ["libraauth-migrar"] + re.findall(r'"([^"]+)"', declarado.group(1))
    assert " ".join(partes) == COMANDO


def test_control_con_la_cadena_arranca(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    crear_schema_de_auth(engine)
    assert crear_app(sembrar_admin=False) is not None
