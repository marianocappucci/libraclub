"""`libraauth-migrar` tiene que encontrar SU base con el entorno real del contenedor.

El 2026-09-16 la adopción de la cadena de LibraAuth tiró el `-dev`:
`libraauth-migrar --prefijo libraclub --base dominio` salió con `SinURL`, porque
`DATABASE_URL` a secas no figuraba en los nombres que conoce
`libracore.db.url_de_instancia`. Los tests de declaración pasaban: miraban la
tupla, no a dónde resolvía. Éste resuelve con los nombres de variable que
**declara el `docker-compose.yml`**, así que un renombre de un lado o del otro
lo pone en rojo.

No se conecta a nada: `url_de_auth` y `url_de_core` sólo leen el entorno.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PREFIJO = "libraclub"
COMPOSE = Path(__file__).resolve().parent.parent / "docker-compose.yml"


def _entorno_del_compose() -> dict[str, str]:
    """Las variables de base del servicio `-dev`, con la base real de su URL y
    un host de mentira. Se leen del archivo, no se copian acá."""
    texto = COMPOSE.read_text(encoding="utf-8")
    entorno = {}
    for nombre, url in re.findall(r"^\s*-\s*([A-Z_]*DATABASE_URL)=(.+?)\s*$", texto, re.M):
        # la URL trae `${...:?hay que definirla en el .env}`, con espacios
        base = url.rsplit("/", 1)[-1]
        entorno[nombre] = f"postgresql://u:p@h/{base}"
    return entorno


def test_el_compose_declara_las_dos_bases():
    entorno = _entorno_del_compose()
    assert set(entorno) == {"DATABASE_URL", f"{PREFIJO.upper()}_LIBRACORE_DATABASE_URL"}
    assert entorno["DATABASE_URL"].endswith(f"/{PREFIJO}")
    assert entorno[f"{PREFIJO.upper()}_LIBRACORE_DATABASE_URL"].endswith(f"/{PREFIJO}_core")


def test_libraauth_migrar_resuelve_la_base_del_DOMINIO():
    """Las seis tablas de auth viven en el dominio (medido el 2026-09-16)."""
    from libraauth.migrar import url_de_auth

    url = url_de_auth(PREFIJO, "dominio", entorno=_entorno_del_compose())
    assert url.rsplit("/", 1)[-1] == PREFIJO


def test_libracore_migrar_sigue_resolviendo_la_base_del_CORE():
    """Control: sumar `DATABASE_URL` como histórico del dominio no le mueve la base
    a `libracore-migrar`."""
    from libracore.migrar import url_de_core

    url = url_de_core(PREFIJO, entorno=_entorno_del_compose())
    assert url.rsplit("/", 1)[-1] == f"{PREFIJO}_core"


def test_sin_la_variable_del_core_libracore_migrar_FALLA_y_no_cae_al_dominio():
    """El riesgo que libracore v1.103.0 cierra: migrar el schema del motor
    adentro de la base del dominio sin fallar."""
    from libracore.migrar import SinURL, url_de_core

    entorno = {"DATABASE_URL": f"postgresql://u:p@h/{PREFIJO}"}
    with pytest.raises(SinURL):
        url_de_core(PREFIJO, entorno=entorno)


def test_el_command_de_dev_migra_auth_con_base_dominio():
    texto = COMPOSE.read_text(encoding="utf-8")
    assert f"libraauth-migrar upgrade --prefijo {PREFIJO} --base dominio" in texto
