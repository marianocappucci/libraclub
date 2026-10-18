"""Qué se sirve del build del frontend y qué cae en la SPA.

Vive aparte de quien monta las rutas **para poder probarlo sin construir la
aplicación**: es una función y una tabla, sin nada que ocurra al importar.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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


#: 🔴 **`index.html` no se cachea, y esto no es una optimización: es lo que hace
#: que un deploy se vea.**
#:
#: Vite le pone un hash en el nombre a cada bundle, así que el archivo nuevo
#: nunca pisa al viejo — pero `index.html` **conserva el nombre** y es el único
#: que dice cuál es el bundle de ahora. Sin `Cache-Control`, el navegador aplica
#: caché heurística y puede servir el `index.html` guardado sin preguntar. El
#: usuario recarga, no ve el cambio, y del lado del servidor está todo bien.
#:
#: `no-cache` **no** es "no guardes": es "guardá, pero revalidá siempre".
SIN_CACHE = "no-cache, must-revalidate"

#: Los assets, al revés: el nombre lleva el hash del contenido, así que **el
#: mismo nombre nunca cambia de contenido**. Un `index.html` que revalida siempre
#: es lo que hace seguro esto: cuando el contenido cambia, cambia el nombre.
PARA_SIEMPRE = "public, max-age=31536000, immutable"


class AssetsInmutables(StaticFiles):
    """`StaticFiles` con la cabecera de caché larga."""

    def file_response(self, *args, **kwargs):
        respuesta = super().file_response(*args, **kwargs)
        respuesta.headers["Cache-Control"] = PARA_SIEMPRE
        return respuesta


def montar_spa(app, dist) -> None:
    """Monta `/assets` y el catch-all del frontend, con sus cabeceras de caché.

    Vive acá, y no en `app/asgi.py`, **para poder probarlo sin construir la
    aplicación**: importar `asgi` ejecuta `crear_app()` (siembra el admin y deja
    otra instancia en `sys.modules`). Es la misma función que llama producción.
    """
    raiz = Path(dist)
    app.mount("/assets", AssetsInmutables(directory=raiz / "assets"), name="frontend-assets")

    # 🔴 `GET` **y `HEAD`**. Con `@app.get` a secas, `HEAD /` daba 405 (`Allow:
    # GET`): FastAPI no deriva el HEAD del GET como hace Starlette con sus
    # rutas. Y HEAD es lo que usan los monitores de uptime (uptime-kuma) y
    # algunos navegadores y proxies para ver si el sitio está vivo: una instancia
    # sana figuraba caída. Starlette descarta el cuerpo de la respuesta a un
    # HEAD, así que es el mismo handler.
    @app.api_route("/{ruta:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(ruta: str):
        if es_ruta_de_api(ruta):
            raise HTTPException(404, "no existe esa ruta")
        archivo = archivo_publico(raiz, ruta)
        if archivo is not None:
            # Los archivos sueltos del dist (favicon, manifest) tampoco llevan
            # hash en el nombre: mismo criterio que el index.
            return FileResponse(
                archivo,
                media_type=TIPOS_PROPIOS.get(archivo.suffix),
                headers={"Cache-Control": SIN_CACHE},
            )
        return FileResponse(raiz / "index.html", headers={"Cache-Control": SIN_CACHE})
