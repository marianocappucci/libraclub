"""Entrypoint ASGI: `uvicorn app.asgi:app`.

Sirve el build del frontend desde el **mismo origen** que la API, con catch-all a
`index.html` para el ruteo del lado del cliente. El dist se hornea fuera de
`/app` (`/opt/frontend-dist`) porque el compose de dev monta `./:/app` entero
para el `--reload`, y eso taparía cualquier build copiado adentro.
"""

from __future__ import annotations

from pathlib import Path

from app.main import crear_app
from app.spa import montar_spa

app = crear_app()

_DIST_DOCKER = Path("/opt/frontend-dist")
_DIST_LOCAL = Path(__file__).resolve().parent.parent / "frontend" / "dist"
FRONTEND_DIST = _DIST_DOCKER if _DIST_DOCKER.is_dir() else _DIST_LOCAL

if FRONTEND_DIST.is_dir():
    montar_spa(app, FRONTEND_DIST)
