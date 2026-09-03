"""De dónde sale la URL de la base del dominio.

🔴 **El defecto que cierra esto no se veía en ninguna instancia viva.**
`libracore.provisioning.nuevo_cliente` escribe en el compose los nombres que
dice `nombres_aceptados("libraclub")` —o sea sólo `LIBRACLUB_DATABASE_URL`— y
`Config.desde_entorno()` leía `DATABASE_URL` a secas. Una instancia **recién
creada** moría al arrancar con "Falta DATABASE_URL"; las existentes andan
porque tienen el compose de cuando se crearon, con la genérica.

Los dos nombres tienen que funcionar, y por eso hay un test por cada uno más el
del orden: durante la transición una instancia puede tener las dos puestas.
"""
from __future__ import annotations

import pytest

from app.config import Config

DOMINIO_NUEVO = "postgresql+psycopg://u:p@h:5432/libraclub"
DOMINIO_VIEJO = "postgresql+psycopg://u:p@h:5432/libraclub_vieja"
CORE = "postgresql+psycopg://u:p@h:5432/libraclub_core"


@pytest.fixture(autouse=True)
def _sin_variables(monkeypatch):
    """Cada test trae su entorno; heredarlo haría que el resultado dependa de
    quién corre la suite."""
    for v in ("DATABASE_URL", "LIBRACLUB_DATABASE_URL",
              "LIBRACLUB_LIBRACORE_DATABASE_URL", "DATA_DIR", "ENTORNO"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("LIBRACLUB_LIBRACORE_DATABASE_URL", CORE)


def test_una_instancia_NUEVA_arranca_con_el_nombre_normalizado(monkeypatch):
    """El caso que estaba roto: es el único nombre que escribe el generador."""
    monkeypatch.setenv("LIBRACLUB_DATABASE_URL", DOMINIO_NUEVO)
    assert Config.desde_entorno().database_url == DOMINIO_NUEVO


def test_las_instancias_VIVAS_siguen_andando_con_la_generica(monkeypatch):
    """Las del VPS tienen `DATABASE_URL` en su compose. Dejar de aceptarla
    las tumbaría en el próximo deploy."""
    monkeypatch.setenv("DATABASE_URL", DOMINIO_VIEJO)
    assert Config.desde_entorno().database_url == DOMINIO_VIEJO


def test_con_las_dos_puestas_gana_el_nombre_normalizado(monkeypatch):
    """Durante la transición una instancia puede tener las dos. La que manda es
    la nueva, que es la que el generador va a seguir escribiendo."""
    monkeypatch.setenv("LIBRACLUB_DATABASE_URL", DOMINIO_NUEVO)
    monkeypatch.setenv("DATABASE_URL", DOMINIO_VIEJO)
    assert Config.desde_entorno().database_url == DOMINIO_NUEVO


def test_sin_ninguna_de_las_dos_falla_nombrando_las_dos(monkeypatch):
    """Fail-closed, y el mensaje dice qué definir.

    Sin esto, la app arrancaría con la cadena vacía y el error llegaría lejos
    del origen, hablando de una conexión y no de una variable.
    """
    with pytest.raises(RuntimeError, match="LIBRACLUB_DATABASE_URL"):
        Config.desde_entorno()


def test_una_variable_vacia_cuenta_como_no_puesta(monkeypatch):
    """Un `FOO=` en un compose es casi siempre una interpolación que no salió.

    Tomarlo como bueno manda a conectarse a la cadena vacía. Se prueba con la
    genérica **vacía y la normalizada puesta**: así se ve que no la pisa.
    """
    monkeypatch.setenv("LIBRACLUB_DATABASE_URL", DOMINIO_NUEVO)
    monkeypatch.setenv("DATABASE_URL", "   ")
    assert Config.desde_entorno().database_url == DOMINIO_NUEVO


def test_una_url_que_no_es_postgres_se_rechaza(monkeypatch):
    """PostgreSQL es el único motor de la familia: un SQLite acá es un error de
    configuración, no un modo de correr."""
    monkeypatch.setenv("LIBRACLUB_DATABASE_URL", "sqlite:///libraclub.db")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Config.desde_entorno()
