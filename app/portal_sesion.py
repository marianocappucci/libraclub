"""La sesión del jugador en el portal. Cookie firmada, igual que la de staff.

🔴 **Cookie DISTINTA de la del backoffice, y ése es el punto.** Si compartieran
nombre, entrar al portal pisaría la sesión del encargado en la misma
computadora del mostrador — y peor, un token del portal podría llegar a los
guards de staff. Son dos poblaciones que no se mezclan: `libra_session` es de
operadores, `libraclub_jugador` es de gente de internet.

Se usa `itsdangerous` con el mismo `SECRET_KEY` de la instancia porque es lo que
hace `libraauth` y no hay motivo para tener dos mecanismos de firma. Lo que
cambia es **qué se firma**: acá el id de la cuenta de jugador, que no existe en
la tabla `usuarios`.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.models.maestros import CuentaDeJugador

COOKIE = "libraclub_jugador"

#: Una semana. Es una cuenta para reservar una cancha, no un home banking: el
#: costo de re-loguear cada día sería que nadie reserve.
MAX_AGE = 86_400 * 7

#: 🔑 El *salt* separa estos tokens de los de `libraauth` aunque compartan
#: `SECRET_KEY`. Sin él, una cookie de staff firmada con el mismo secreto
#: podría deserializar acá — y al revés.
SALT = "libraclub-portal-jugador"


def _firmador() -> URLSafeTimedSerializer:
    secreto = os.environ.get("SECRET_KEY", "")
    if not secreto:
        # Mismo criterio fail-fast que `libraauth._resolve_secret_key`: sin
        # secreto propio, cualquiera con `itsdangerous` forja una sesión.
        if os.environ.get("ENV", "") == "development":
            secreto = "dev-portal-inseguro"
        else:
            raise RuntimeError(
                "SECRET_KEY no está seteado: el portal no puede firmar sesiones."
            )
    return URLSafeTimedSerializer(secreto, salt=SALT)


def crear_cookie(respuesta: Response, cuenta_id: int) -> None:
    respuesta.set_cookie(
        COOKIE,
        _firmador().dumps(cuenta_id),
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=MAX_AGE,
    )


def borrar_cookie(respuesta: Response) -> None:
    respuesta.delete_cookie(COOKIE)


def cuenta_actual(request: Request, sesion: Session) -> CuentaDeJugador | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        cuenta_id = _firmador().loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    cuenta = sesion.get(CuentaDeJugador, cuenta_id)
    # 🔑 Se relee de la base y se chequea `activa` en cada request: una cuenta
    # dada de baja tiene que dejar de entrar **ya**, no cuando su cookie expire
    # dentro de una semana.
    return cuenta if cuenta is not None and cuenta.activa else None


def exigir_jugador(request: Request, sesion: Session) -> CuentaDeJugador:
    cuenta = cuenta_actual(request, sesion)
    if cuenta is None:
        # 401 y no un redirect: el portal es una SPA y el que llama es `fetch`.
        raise HTTPException(401, "Entrá a tu cuenta para continuar.")
    return cuenta
