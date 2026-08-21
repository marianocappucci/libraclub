"""Monta el router `/auth` (login / logout / me / verify / demo) que expone
`libraauth`.

`incluir_verify=True` es lo que hace posible el login de `/docs/` de la landing
(`libraclub_web`): un chequeo de credenciales **server-to-server**, protegido
por el secreto compartido `DOCS_AUTH_SECRET`, que nunca crea cookie de sesión.
Sin este flag la documentación de la landing no puede validar a nadie, y el
login contesta 502 para cualquier credencial — incluso las correctas.

`incluir_demo=True` **no enciende nada por sí solo**: `POST /auth/demo` se
registra únicamente si la instancia además tiene `DEMO_MODE` y `DEMO_USERNAME`.
En la instancia de un complejo la ruta no existe. La otra mitad —el usuario del
visitante y el repositorio de códigos— la cablea `main.py`; son dos decisiones
separadas y cada una falla distinto.

`incluir_password_reset=True` agrega `/auth/forgot-password` y
`/auth/reset-password`. Se encendió el 2026-08-21: hasta entonces este producto
era el único de la familia —con LibraCargo— sin "¿olvidaste tu contraseña?" en
el login, con el argumento de que hacía falta SMTP. **No hacía falta**: sin SMTP
el endpoint contesta 503 y la app levanta igual, que es como corren los otros
seis desde julio.
"""

from __future__ import annotations

from fastapi import APIRouter
from libraauth.session_auth import build_json_api_auth_router


def construir_router() -> APIRouter:
    return build_json_api_auth_router(
        incluir_verify=True,
        # `POST /auth/forgot-password` y `POST /auth/reset-password`. Necesita
        # que `main.py` haya puesto `app.state.password_reset`; sin eso los
        # endpoints existirían y fallarían al primer pedido.
        #
        # 🔑 **Sin SMTP configurado la app levanta igual**: el que avisa es el
        # endpoint, con un 503, recién cuando alguien pide un reset. Por eso se
        # puede encender ahora aunque la instancia todavía no tenga correo — y
        # por eso no encenderlo "hasta tener SMTP" era una espera sin motivo:
        # los otros seis productos de la familia lo tienen así desde julio.
        incluir_password_reset=True,
        incluir_demo=True,
    )
