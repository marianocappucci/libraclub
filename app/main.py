"""Construcción de la aplicación.

`crear_app()` no se ejecuta al importar: el entrypoint es `app/asgi.py`. Es a
propósito — con la app armada al importar, la configuración queda resuelta por
el primer import y un test que quiera otra base ya llega tarde.
"""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI
from libraauth.bootstrap import ensure_default_admin
from libraauth.models import Base as AuthBase
from libraauth.session_auth import build_smtp_settings_router
from libraauth.smtp_settings import SmtpSettingsRepository
from libracore.config_router import (
    build_backup_router,
    build_empresa_admin_router,
    build_empresa_router,
)
from libracore.respaldo import Instancia

from app import db
from app.auth import UserRepository, construir_session_auth, require_admin
from app.config import Config
from app.routers import admin, disponibilidad, maestros, reservas, salud
from app.routers import auth as auth_router

# Con alias: más abajo hay una variable local `usuarios` con el repositorio, y
# sin el alias el import queda pisado.
from app.routers import usuarios as usuarios_router


def _instancia_a_respaldar(config: Config) -> Instancia:
    """Qué se lleva el backup.

    Una sola base y ningún archivo en disco: `usuarios` vive en la misma base
    que el dominio, y no hay logos ni adjuntos todavía. `directorios=[]` no es un
    pendiente — es que el backup **es** exactamente el dump, y no hay forma de
    bajarse una copia a la que le falte algo.

    Cuando entre la facturación (F3) esto cambia: el certificado de ARCA es un
    archivo, y hay que decidir explícitamente si entra al ZIP o no.
    """
    return Instancia(nombre="libraclub", postgres_url=config.database_url)


def crear_app(config: Config | None = None, *, sembrar_admin: bool = True) -> FastAPI:
    # Se resuelve acá y no adentro de `db.inicializar` porque el router de backup
    # necesita la MISMA config: la URL para el dump y el directorio de datos para
    # los ZIP.
    config = config or Config.desde_entorno()
    db.inicializar(config)
    motor = db.engine()

    # Las tablas del motor de auth las crea el motor, con el mismo engine que el
    # dominio: `usuarios` vive en la MISMA base, así que las FK de sus tablas
    # satélite resuelven. Las tablas propias van por Alembic; las de `libraauth`
    # no, porque su schema lo versiona él y no nosotros.
    AuthBase.metadata.create_all(motor)

    usuarios = UserRepository(db.fabrica_de_sesiones())
    if sembrar_admin:
        # Variante **fail-closed**: sin `LIBRACLUB_ADMIN_PASSWORD` la app no
        # levanta, salvo `ENV=development`. La otra (`ensure_admin_user`) inventa
        # una contraseña y la imprime, y no son intercambiables.
        ensure_default_admin(usuarios, env_prefix="LIBRACLUB")

    app = FastAPI(
        title="LibraClub",
        description="Gestión de complejos deportivos — familia Libra",
        version="0.1.0",
    )
    # El router de `libraauth` los lee de acá por nombre: sin estos dos, el login
    # devuelve 500 al primer request y no al arrancar.
    app.state.users = usuarios
    app.state.session_auth = construir_session_auth(usuarios)

    app.include_router(salud.router)
    app.include_router(auth_router.router)
    for router in maestros.TODOS:
        app.include_router(router)
    app.include_router(reservas.router)
    app.include_router(disponibilidad.router)
    app.include_router(usuarios_router.router)
    app.include_router(admin.router)

    # "Datos / Backup": el motor de la familia, con la dependencia de rol de este
    # producto. El prefijo es `/api/config` porque es el que consume la pantalla
    # compartida de `libra-ui`; renombrarlo obligaría a forkear esa pantalla.
    #
    # 🔴 `cerrar_conexiones`/`reabrir_conexiones` no son opcionales: sin ellos el
    # restore contesta `ok` y no tiene efecto hasta que alguien reinicie el
    # contenedor, porque el pool sigue con la conexión vieja. La pantalla diría
    # que salió bien y los datos serían los de antes.
    # Datos de la empresa y logo. Los dos routers son del motor: este producto no
    # reimplementa nada, sólo les pone su dependencia de rol.
    #
    # **Todo admin, también la lectura.** Hasta hoy LibraClub no tenía ninguna
    # pantalla de configuración, así que no hay ningún consumidor de la lectura
    # que haya que dejar abierto — el día que la factura o el ticket necesiten
    # el nombre de la empresa desde una pantalla de staff, se abre ahí y con ese
    # motivo, no antes.
    app.include_router(build_empresa_router(), dependencies=[Depends(require_admin)])
    app.include_router(build_empresa_admin_router(), dependencies=[Depends(require_admin)])

    # `GET`/`PUT`/`DELETE /admin/smtp`. El router ya exige rol admin por dentro,
    # así que no lleva `dependencies`: quien pueda escribir ahí puede redirigir a
    # dónde salen los enlaces de recuperación de contraseña de todos los
    # usuarios.
    #
    # ⚠️ Esto NO enciende la recuperación de contraseña: `app/routers/auth.py`
    # monta el router de `libraauth` **sin** `incluir_password_reset`. Lo que
    # habilita es cargar el SMTP; encender la recuperación es una decisión
    # aparte, con su propia pantalla de "olvidé mi contraseña" en el login.
    app.state.smtp_settings = SmtpSettingsRepository(db.fabrica_de_sesiones())
    app.include_router(build_smtp_settings_router())

    app.include_router(
        build_backup_router(
            _instancia_a_respaldar(config),
            os.path.join(config.directorio_de_datos, "backups"),
            cerrar_conexiones=motor.dispose,
            reabrir_conexiones=motor.dispose,
        ),
        dependencies=[Depends(require_admin)],
    )
    return app
