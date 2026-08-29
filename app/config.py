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


#: Los nombres con los que este ecosistema escribe "producción" en `ENTORNO`.
#: Están todos porque el valor lo escribe una persona en un `.env`, y el que
#: falte acá es una instancia de producción tratada como si fuera dev.
NOMBRES_DE_PRODUCCION = ("prod", "produccion", "producción", "production")


def es_produccion(entorno: str) -> bool:
    """Si este `ENTORNO` es producción. **Una sola definición, a propósito.**

    🔴 Es el predicado que decide si se montan los simuladores — el del portal,
    que confirma reservas sin que nadie pague, y el del cobro por QR, que
    acredita cobros sin que entre un peso. Hasta el 2026-08-29 la tupla estaba
    escrita **literal en los dos archivos**: dos puertas al mismo cuarto, y
    sumar un nombre en una dejaba la otra abierta sin que nada se pusiera rojo.

    🔑 **Y no aparece una tercera copia para la pantalla.** La Caja necesita
    saber si el simulador existe para ofrecer el botón, pero no vuelve a
    evaluar esto: pregunta por `GET /api/reservas/mp-qr/simulacion`, que vive
    **adentro del router del simulador**. Si el router no se montó, esa ruta
    tampoco existe y el 404 es la respuesta. Una sola puerta.
    """
    return entorno.lower() in NOMBRES_DE_PRODUCCION
