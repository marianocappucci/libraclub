"""Session auth de LibraClub — shim sobre `libraauth`.

Existe para que el resto del producto importe de un solo lugar: si mañana cambia
la forma de pedir un rol, se toca acá y no en cada router.
"""

from __future__ import annotations

from fastapi import Depends, Request
from libraauth.repository import UserRepository
from libraauth.session_auth import (
    SessionAuth,
)
from libraauth.session_auth import (
    json_api_get_current_user as _get_current_user,
)
from libraauth.session_auth import (
    # No se envuelve: no es un gate de usuario, provee el objeto de auth.
    json_api_get_session_auth as get_session_auth,
)
from libraauth.session_auth import (
    json_api_require_admin as _require_admin,
)
from libraauth.session_auth import (
    # Rol admin **o** token de servicio. Lo usa el router de usuarios y el
    # resumen del panel del dueño (ADR-009).
    #
    # Falla cerrado por omisión: **sin `LIBRA_SERVICE_TOKEN` en el entorno se
    # comporta igual que `require_admin`**, así que dejarlo sin definir en una
    # instancia no abre nada. Lo que abriría algo sería ponerle un valor
    # adivinable, y por eso no hay uno de ejemplo.
    json_api_require_admin_o_servicio as _require_admin_o_servicio,
)
from libraauth.session_auth import (
    json_api_require_role as _require_role,
)
from libraauth.session_auth import (
    json_api_require_staff as _require_staff,
)

from app import auditoria


def _que_recuerde_al_usuario(gate):
    """Envuelve un gate de `libraauth` para que además deje el usuario anotado.

    🔑 **Acá y no en cada router**: los cinco routers importan sus gates de este
    módulo, así que éste es el único lugar por el que pasa toda ruta
    autenticada. Envolviéndolos acá, una ruta nueva queda auditada por el solo
    hecho de pedir un rol — que es lo que se pide siempre.

    La firma se preserva tal cual (`Request` + la dependencia original), porque
    FastAPI arma la inyección leyendo la firma: cambiarla rompería el gate.
    """

    def _envuelto(request: Request, usuario: dict = Depends(gate)) -> dict:
        auditoria.recordar_usuario(request, usuario)
        return usuario

    return _envuelto


get_current_user = _que_recuerde_al_usuario(_get_current_user)
require_admin = _que_recuerde_al_usuario(_require_admin)
require_staff = _que_recuerde_al_usuario(_require_staff)
require_admin_o_servicio = _que_recuerde_al_usuario(_require_admin_o_servicio)


def require_role(*roles: str):
    """Igual que el de `libraauth`, pero anotando al usuario."""
    return _que_recuerde_al_usuario(_require_role(*roles))


__all__ = [
    "SessionAuth", "UserRepository", "construir_session_auth",
    "get_current_user", "get_session_auth",
    "require_admin", "require_admin_o_servicio", "require_role", "require_staff",
]

#: Nombre de la cookie. Propio por producto: dos instancias de productos
#: distintos bajo el mismo dominio padre se pisarían la sesión si compartieran
#: nombre.
COOKIE = "club_session"


def construir_session_auth(usuarios: UserRepository) -> SessionAuth:
    return SessionAuth(
        dev_secret_fallback="libraclub-dev-secret-not-for-prod",
        get_user_by_username=usuarios.get_by_username,
        check_credentials=usuarios.check_credentials,
        cookie_name=COOKIE,
    )
