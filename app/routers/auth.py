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
from libraauth.captcha import UsadosEnBase
from libraauth.session_auth import build_json_api_auth_router

from app import db

#: Dónde se anotan los desafíos del captcha ya resueltos: la tabla `libraauth_captcha_usados` (libraauth v0.50.0,
#: ADR-023), no la memoria del proceso. Con `uvicorn --workers N` (hoy N = 1) una lista por proceso deja que un
#: desafío resuelto sirva **una vez por worker**. Necesita la migración `0003` de la cadena de libraauth, que corre
#: antes de uvicorn. La fábrica de sesiones se resuelve en cada uso (`lambda`): `db.inicializar()` la rearma cada vez
#: que `crear_app()` corre.
#:
#: 🔑 **Es uno solo para `/auth` y para el portal** (`routers/portal.py`): el portal verifica con
#: `verificar_captcha(request, ..., USADOS_DEL_CAPTCHA)` y, si le toca crear el `Captcha` del proceso, tiene que crearlo
#: con los mismos `usados` o ese worker anota en memoria.
USADOS_DEL_CAPTCHA = UsadosEnBase(lambda: db.fabrica_de_sesiones()())


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
        # `GET /auth/captcha` y el campo `captcha` obligatorio en el login y en
        # forgot-password: el desafío ALTCHA, emitido y verificado acá mismo.
        # **Siempre**, no recién después de N fallos — decisión del humano del
        # 2026-09-11 (ADR-014 de libraauth). Va junto con el bloqueo por IP,
        # no en su lugar: la IP no frena a quien reparte los intentos.
        captcha=True,
        captcha_usados=USADOS_DEL_CAPTCHA,
    )
