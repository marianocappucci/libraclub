"""Sesión y engine. Un único lugar donde se construye la conexión."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

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


def obtener_sesion() -> Iterator[Session]:
    if _Sesion is None:
        inicializar()
    sesion = _Sesion()
    try:
        yield sesion
    finally:
        sesion.close()
