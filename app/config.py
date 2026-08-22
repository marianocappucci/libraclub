"""Configuración por entorno. Ningún secreto vive en el código."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    database_url: str
    entorno: str
    debug: bool
    #: Dónde escribe la app lo que tiene que sobrevivir a un redeploy: hoy, los
    #: ZIP de backup. **Tiene que ser un volumen**, no una carpeta del árbol de
    #: código — en `dev` ese árbol es un bind mount del checkout del servidor, y
    #: un `git pull` con archivos nuevos adentro es un problema.
    directorio_de_datos: str = "./data"
    #: La base de [[libracore]], **separada de la del dominio**.
    #:
    #: 🔴 Separada y no la misma, y no es una preferencia: `init_core_schema()`
    #: crea `usuarios` y `auth_log`, que en este producto **ya existen** con la
    #: forma de `libraauth`. Compartiendo base, el `CREATE TABLE IF NOT EXISTS`
    #: no las pisa —así que nada falla— pero libracore quedaría leyendo tablas
    #: con las columnas de otro motor. Es el mismo arreglo que ya usan
    #: Gestiolibra, MedLibra y VentaLibra.
    #:
    #: `None` mientras no esté configurada: sin ella la app levanta igual y lo
    #: único que no anda es la facturación. Un producto que todavía no factura
    #: no tiene por qué exigir una segunda base para arrancar.
    libracore_database_url: str | None = None

    @classmethod
    def desde_entorno(cls) -> Config:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError(
                "Falta DATABASE_URL. LibraClub corre sobre PostgreSQL; no hay "
                "default a SQLite a propósito (DECISIONS.md ADR-001)."
            )
        if not url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise RuntimeError(
                f"DATABASE_URL debe apuntar a PostgreSQL, no a {url.split(':', 1)[0]!r}. "
                "La garantía de no-superposición de este producto es un constraint "
                "de exclusión GiST, que sólo existe en PostgreSQL."
            )
        return cls(
            database_url=url,
            entorno=os.environ.get("ENTORNO", "dev"),
            debug=os.environ.get("DEBUG", "").lower() in {"1", "true", "si"},
            directorio_de_datos=os.environ.get("DATA_DIR", "./data"),
            libracore_database_url=cls._url_de_libracore(),
        )

    @staticmethod
    def _url_de_libracore() -> str | None:
        """La URL de la base de LibraCore, con el nombre normalizado de la familia.

        `LIBRACLUB_LIBRACORE_DATABASE_URL` es la convención que fijó
        `libracore.db.url_de_instancia` el 2026-08-11 para los seis productos —
        antes cada uno la llamaba distinto y dos de los nombres mentían
        (`..._DB_PATH` guardando una URL).

        Se valida que sea PostgreSQL por el mismo motivo que la del dominio: un
        SQLite acá sería una base de facturación fuera del motor de la familia.
        """
        url = os.environ.get("LIBRACLUB_LIBRACORE_DATABASE_URL", "").strip()
        if not url:
            return None
        if not url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise RuntimeError(
                "LIBRACLUB_LIBRACORE_DATABASE_URL debe apuntar a PostgreSQL, no a "
                f"{url.split(':', 1)[0]!r}. PostgreSQL es el único motor de la familia."
            )
        return url
