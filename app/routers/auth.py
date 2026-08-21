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

Sigue **sin** `incluir_password_reset`: eso necesita SMTP configurado, que
LibraClub todavía no tiene. Un endpoint de recuperación sin SMTP contesta 503 y
confunde.

🔴 **El router se construye en una función y no al importar el módulo, a
diferencia del resto de los routers de este producto.** `build_json_api_auth_router`
lee `DEMO_MODE`/`DEMO_USERNAME` *mientras construye*, así que un `router = ...`
a nivel de módulo las congela en el primer import — y el primer import ocurre
antes de que nadie haya podido decidir nada. En producción no se nota, porque
las variables vienen del entorno del proceso; se nota en los tests, donde
`POST /auth/demo` daba **404 con la demo encendida**. Es la misma razón por la
que `crear_app()` tampoco corre al importar: ver el docstring de `main.py`.
"""

from __future__ import annotations

from fastapi import APIRouter
from libraauth.session_auth import build_json_api_auth_router


def construir_router() -> APIRouter:
    return build_json_api_auth_router(incluir_verify=True, incluir_demo=True)
