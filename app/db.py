"""Sesión y engine. Un único lugar donde se construye la conexión."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import auditoria
from app.config import Config

_config = None
_engine = None
_Sesion = None


def inicializar(config: Config | None = None) -> None:
    global _config, _engine, _Sesion
    _config = config or Config.desde_entorno()
    _engine = create_engine(_config.database_url, pool_pre_ping=True, future=True)
    _Sesion = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def engine():
    if _engine is None:
        inicializar()
    return _engine


def fabrica_de_sesiones():
    """El `sessionmaker`, que es a la vez el `session_factory` que espera
    `libraauth.UserRepository`: un callable que devuelve una `Session` usable
    como context manager."""
    if _Sesion is None:
        inicializar()
    return _Sesion


def obtener_sesion(request: Request = None) -> Iterator[Session]:  # noqa: RUF013
    """La sesión del request, con la `Request` colgada en `info`.

    🔑 Lo de `info` es lo que hace posible la auditoría: el listener de
    `app/auditoria.py` la lee **en el flush** para saber quién está escribiendo.
    Se guarda la Request y no el id porque cuando esta dependencia corre, el
    gate de rol puede no haber corrido todavía — ver el comentario largo en ese
    módulo.

    `request` es opcional para que la función siga sirviendo fuera de FastAPI
    (scripts, semillas): ahí no hay usuario y las columnas quedan en `NULL`, que
    es lo correcto.
    """
    if _Sesion is None:
        inicializar()
    sesion = _Sesion()
    if request is not None:
        sesion.info[auditoria.CLAVE_EN_INFO] = request
    try:
        yield sesion
    finally:
        sesion.close()
