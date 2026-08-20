"""Qué se sirve del build del frontend y qué cae en la SPA.

Vive aparte de quien monta las rutas **para poder probarlo sin construir la
aplicación**: es una función y una tabla, sin nada que ocurra al importar.
"""

from __future__ import annotations

from pathlib import Path

# `mimetypes` no conoce `.webmanifest`, y sin un tipo que el navegador acepte no
# hay aplicación instalable.
TIPOS_PROPIOS = {".webmanifest": "application/manifest+json"}

#: Prefijos que NO son de la SPA. Una ruta de API que no existe tiene que dar
#: 404, no el `index.html`.
PREFIJOS_DE_API = ("api", "auth", "admin", "salud", "health")


def es_ruta_de_api(ruta: str) -> bool:
    """Sin esto, `/api/lo-que-sea` devuelve el `index.html` con **200**.

    Un endpoint mal escrito en el frontend no falla —recibe HTML y un 200—, y
    cualquier chequeo apuntado a una ruta de API pasa exista o no, que es la
    peor clase de monitoreo: el que no puede dar rojo.
    """
    primero = ruta.strip("/").split("/", 1)[0]
    return primero in PREFIJOS_DE_API


def archivo_publico(dist, ruta: str) -> Path | None:
    """El archivo real de `dist` que corresponde a `ruta`, o None para el index.

    Sólo se sirve lo que existe de verdad adentro de `dist`. El resto cae en la
    SPA, que es lo que hace andar el ruteo del lado del cliente.
    """
    if not ruta or ruta.endswith("/"):
        return None
    raiz = Path(dist).resolve()
    candidato = (raiz / ruta).resolve()
    if raiz not in candidato.parents:
        return None  # un `..` que se escapa de dist
    if candidato.name == "index.html" or not candidato.is_file():
        return None
    return candidato
