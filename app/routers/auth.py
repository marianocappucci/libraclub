"""Monta el router `/auth` (login / logout / me) que expone `libraauth`.

Sin `incluir_password_reset` ni `incluir_demo`: el primero necesita SMTP
configurado y el segundo sólo tiene sentido en una instancia demo, que LibraClub
todavía no tiene. Se encienden cuando exista lo que sostienen, no antes — un
endpoint de recuperación sin SMTP contesta 503 y confunde.
"""

from __future__ import annotations

from libraauth.session_auth import build_json_api_auth_router

router = build_json_api_auth_router()
