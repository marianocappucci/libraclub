"""Donde esta el build del frontend.

Lo usan `asgi.py` (para servirlo) y `main.py` (el manifest de la marca cae al `manifest.webmanifest` del
build).

El dist se hornea fuera de `/app` (`/opt/frontend-dist`) porque el compose de dev monta `./:/app` entero para el
`--reload`, y eso taparia cualquier build copiado adentro. En local cae a `frontend/dist`.
"""

from __future__ import annotations

from pathlib import Path

_DIST_DOCKER = Path("/opt/frontend-dist")
_DIST_LOCAL = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def frontend_dist() -> Path:
    return _DIST_DOCKER if _DIST_DOCKER.is_dir() else _DIST_LOCAL
