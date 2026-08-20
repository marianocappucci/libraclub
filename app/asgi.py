"""Entrypoint ASGI: `uvicorn app.asgi:app`.

Sirve el build del frontend desde el **mismo origen** que la API, con catch-all a
`index.html` para el ruteo del lado del cliente. El dist se hornea fuera de
`/app` (`/opt/frontend-dist`) porque el compose de dev monta `./:/app` entero
para el `--reload`, y eso taparía cualquier build copiado adentro.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.main import crear_app
from app.spa import TIPOS_PROPIOS, archivo_publico, es_ruta_de_api

app = crear_app()

_DIST_DOCKER = Path("/opt/frontend-dist")
_DIST_LOCAL = Path(__file__).resolve().parent.parent / "frontend" / "dist"
FRONTEND_DIST = _DIST_DOCKER if _DIST_DOCKER.is_dir() else _DIST_LOCAL

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

if FRONTEND_DIST.is_dir():

    class AssetsInmutables(StaticFiles):
        """`StaticFiles` con la cabecera de caché larga."""

        def file_response(self, *args, **kwargs):
            respuesta = super().file_response(*args, **kwargs)
            respuesta.headers["Cache-Control"] = PARA_SIEMPRE
            return respuesta

    app.mount(
        "/assets",
        AssetsInmutables(directory=FRONTEND_DIST / "assets"),
        name="frontend-assets",
    )

    @app.get("/{ruta:path}", include_in_schema=False)
    async def spa(ruta: str):
        if es_ruta_de_api(ruta):
            raise HTTPException(404, "no existe esa ruta")
        archivo = archivo_publico(FRONTEND_DIST, ruta)
        if archivo is not None:
            # Los archivos sueltos del dist (favicon, manifest) tampoco llevan
            # hash en el nombre: mismo criterio que el index.
            return FileResponse(
                archivo,
                media_type=TIPOS_PROPIOS.get(archivo.suffix),
                headers={"Cache-Control": SIN_CACHE},
            )
        return FileResponse(
            FRONTEND_DIST / "index.html", headers={"Cache-Control": SIN_CACHE}
        )
