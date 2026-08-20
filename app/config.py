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
    directorio_de_datos: str = "./datos"

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
            directorio_de_datos=os.environ.get("DATA_DIR", "./datos"),
        )
