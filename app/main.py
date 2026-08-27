"""Construcción de la aplicación.

`crear_app()` no se ejecuta al importar: el entrypoint es `app/asgi.py`. Es a
propósito — con la app armada al importar, la configuración queda resuelta por
el primer import y un test que quiera otra base ya llega tarde.
"""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI
from libraauth.auditoria import (
    AuditoriaBase,
    AuditoriaRepository,
    agregar_middleware_de_usuario,
    build_logs_router,
    configurar_auditoria,
)
from libraauth.auth_events import AuthEventRepository
from libraauth.bootstrap import ensure_default_admin, ensure_demo_user
from libraauth.demo_codigos import DemoCodigoRepository
from libraauth.models import Base as AuthBase
from libraauth.password_reset import PasswordResetService
from libraauth.session_auth import (
    build_demo_codigos_router,
    build_smtp_settings_router,
    demo_username,
)
from libraauth.smtp_settings import SmtpSettingsRepository, resolver_smtp_config
from libraauth.terminos import TerminosRepository, build_terminos_router
from libracore.config_router import (
    build_backup_router,
    build_empresa_admin_router,
    build_empresa_router,
)
from libracore.respaldo import Instancia

from app import db
from app.auth import UserRepository, construir_session_auth, require_admin
from app.config import Config
from app.routers import admin, disponibilidad, maestros, reservas, salud, torneos
from app.routers import auth as auth_router
from app.routers import buffet as buffet_router
from app.routers import caja as caja_router
from app.routers import cuenta_corriente as cuenta_corriente_router
from app.routers import facturacion as facturacion_router
from app.routers import facturas as facturas_router
from app.routers import mercadopago as mercadopago_router
from app.routers import portal as portal_router
from app.routers import resumen as resumen_router

# Con alias: más abajo hay una variable local `usuarios` con el repositorio, y
# sin el alias el import queda pisado.
from app.routers import usuarios as usuarios_router
from app.servicios import facturacion

#: Qué entra al log de actividad: `{clase del modelo: nombre legible}`.
#:
#: Es una lista **blanca** a propósito: una tabla nueva no entra sola, así que
#: agregar un modelo obliga a decidir si su historial le importa a alguien.
#:
#: `Serie` queda AFUERA y es la única decisión discutible. Una serie es la
#: cancha fija —el molde—, y cada reserva que genera se audita por su cuenta:
#: auditarla además pondría el mismo hecho dos veces, que es justo lo que el
#: motor advierte que no hay que hacer con las tablas que ya son historial de
#: algo. Lo que se pierde: quién cambió el molde. Si esa pregunta aparece, se
#: agrega acá.
AUDITABLES = {
    "Sucursal": "sucursal",
    "Cancha": "cancha",
    "Cliente": "cliente",
    "Tarifa": "tarifa",
    "Feriado": "feriado",
    # Cambiar el horario de atención cambia qué turnos se pueden vender. Es la
    # clase de dato que alguien toca una vez y después nadie recuerda haber
    # tocado, así que queda con nombre y fecha.
    "FranjaDeAtencion": "horario de atención",
    # 🔑 El que motivó todo esto: *"quién movió el turno de las 20:00 a las
    # 21:00 sin avisar"* es una discusión con un cliente, no un bug.
    "Reserva": "reserva",
    # El mismo argumento, en un torneo: "quién cambió el resultado de la
    # semifinal" y "quién movió el partido a la otra cancha" son discusiones con
    # gente, y el resultado se puede corregir después de cargado.
    #
    # `ParcialDePartido` queda AFUERA: es el detalle del partido y se reemplaza
    # entero al corregir, así que anotarlo pondría el mismo hecho dos veces —
    # mismo criterio que `Serie`. `Zona` e `IntegranteDeCompetidor` tampoco: se
    # escriben una vez, en el sorteo y en la inscripción, que ya quedan
    # anotados por el torneo y el competidor.
    "Torneo": "torneo",
    "Competidor": "competidor",
    "PartidoDeTorneo": "partido de torneo",
}


def _instancia_a_respaldar(config: Config) -> Instancia:
    """Qué se lleva el backup.

    🔴 **DOS bases desde que entró la facturación, y las dos tienen que entrar.**
    `libracore` corre contra una base propia —ver `servicios/facturacion.py`—,
    así que un backup del dominio solo **no se puede restaurar**: o volvés las
    reservas y te quedan las facturas de otro momento, o al revés. Y no falla:
    da un ZIP que se descarga y pesa poco, que es la peor forma de perder datos.

    En una instancia sin facturar sigue siendo una sola, y eso está bien: no hay
    nada del otro lado que respaldar.

    `directorios=[]` todavía: no hay logos ni adjuntos. **El certificado de ARCA
    sí es un archivo**, y cuando se suba por pantalla hay que decidir
    explícitamente si entra al ZIP — un backup con la clave privada adentro es un
    archivo que circula por mail.
    """
    extra = [config.libracore_database_url] if config.libracore_database_url else []
    return Instancia(
        nombre="libraclub", postgres_url=config.database_url, postgres_extra=extra,
    )


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
    # La base de LibraCore, si esta instancia factura. Devuelve False y no hace
    # nada cuando no está configurada — la app levanta igual.
    facturacion.configurar(config.libracore_database_url)

    AuthBase.metadata.create_all(motor)
    # El log de actividad cuelga de su propio `Base`, no del de `models.py`: la
    # tabla tiene que quedar en la base del DOMINIO, que es donde ocurren las
    # escrituras que audita y donde vive la transacción. En LibraClub las dos
    # son la misma base, pero se respeta igual — es el contrato del motor.
    AuditoriaBase.metadata.create_all(motor)

    usuarios = UserRepository(db.fabrica_de_sesiones())
    if sembrar_admin:
        # Variante **fail-closed**: sin `LIBRACLUB_ADMIN_PASSWORD` la app no
        # levanta, salvo `ENV=development`. La otra (`ensure_admin_user`) inventa
        # una contraseña y la imprime, y no son intercambiables.
        ensure_default_admin(usuarios, env_prefix="LIBRACLUB")

    # El visitante de la demo pública, **sólo si esta instancia es una demo**:
    # se guía por `DEMO_MODE` + `DEMO_USERNAME`, las mismas dos variables que
    # registran `POST /auth/demo`. En la instancia de un complejo devuelve None
    # y no toca la base.
    #
    # 🔴 Sin esta llamada la ruta existe y no tiene a quién loguear: contesta
    # `503 demo user not provisioned`. Cablear `incluir_demo=True` en el router
    # no alcanza — la ruta y la siembra las conecta el producto, cada una por
    # su lado, y ninguna de las dos delata que falta la otra.
    ensure_demo_user(usuarios)

    app = FastAPI(
        title="LibraClub",
        description="Gestión de complejos deportivos — familia Libra",
        version="0.1.0",
    )
    # El router de `libraauth` los lee de acá por nombre: sin estos dos, el login
    # devuelve 500 al primer request y no al arrancar.
    app.state.users = usuarios
    app.state.session_auth = construir_session_auth(usuarios)

    # 🔴 **Sin esta línea se apagaban DOS cosas, no una.** `auth_events` es
    # opt-in por ausencia: sin `app.state.auth_events`, `registrar_seguro` no
    # anota nada —se pierde el log de accesos— y `contar_fallidos_seguro`
    # devuelve **0**, con lo cual el corte por intentos fallidos del login
    # nunca dispara. O sea que LibraClub venía sin freno al fuerza bruta, con
    # la tabla `auth_log` creada y vacía. Verificado el 2026-08-20.
    app.state.auth_events = AuthEventRepository(db.fabrica_de_sesiones())

    # Log de actividad: quién creó, editó o borró qué, y qué cambió. Cuelga del
    # `flush` de SQLAlchemy, así que una escritura que no pase por acá no
    # existe — no hay forma de olvidarse en un servicio nuevo.
    configurar_auditoria(db.fabrica_de_sesiones(), AUDITABLES)
    app.state.auditoria = AuditoriaRepository(db.fabrica_de_sesiones())
    # El middleware deja el usuario de la request al alcance del flush. Es
    # `ContextVar` y funciona porque lo setea en el contexto **async**; el
    # `request.state` de `app/auditoria.py` existe por lo contrario — ver el
    # comentario largo ahí.
    agregar_middleware_de_usuario(app)

    app.include_router(salud.router)
    # `construir_router()` y no un `router` de módulo: lee `DEMO_MODE` al
    # construirse, y a nivel de módulo quedaría congelado en el primer import.
    # Ver el docstring de `app/routers/auth.py`.
    app.include_router(auth_router.construir_router())

    # Los códigos de acceso de la demo pública. Se emiten desde el backoffice
    # (`admin.libraclub.com.ar`) y los consume `POST /auth/demo`.
    #
    # 🔴 `POST /auth/demo` **falla cerrado** si esta línea no corrió: contesta
    # `503 demo access codes not configured` en vez de dejar entrar sin código.
    # Es incómodo a propósito — la alternativa convertiría un olvido de
    # cableado en una demo abierta a internet, que es exactamente lo que el
    # código de acceso existe para cerrar. Si un día la demo devuelve ese 503,
    # lo que falta es esto.
    #
    # El factory es el mismo `db.fabrica_de_sesiones()` del `UserRepository`
    # porque en LibraClub `usuarios` vive en la MISMA base que el dominio. En
    # Gestiolibra/MedLibra/VentaLibra no es así y ahí va el factory del engine
    # de auth; copiar de allá sin mirar crearía la tabla en el lugar
    # equivocado y ningún código sería válido.
    if demo_username():
        app.state.demo_codigos = DemoCodigoRepository(db.fabrica_de_sesiones())
        app.include_router(build_demo_codigos_router())

    for router in maestros.TODOS:
        app.include_router(router)
    app.include_router(reservas.router)
    # Los torneos. Sin `dependencies`: definir y sortear son de admin —cambian
    # lo que el complejo se comprometió a jugar— e inscribir, programar y cargar
    # resultados son de mostrador. Cada endpoint declara el suyo.
    app.include_router(torneos.router)
    app.include_router(disponibilidad.router)
    app.include_router(usuarios_router.router)
    app.include_router(admin.router)

    # Los dos logs —actividad y accesos— para la pantalla compartida. El router
    # no se gatea a sí mismo: el vocabulario de roles es del producto.
    #
    # 🔴 `prefix="/api/logs"` y NO el `/logs` que trae por default. La SPA tiene
    # su pantalla en `/logs`, y FastAPI resuelve sus rutas **antes** que el
    # catch-all: con el default, entrar a `/logs` en el navegador devolvía el
    # JSON crudo del endpoint en vez de la pantalla. No falla ni avisa — se ve
    # el JSON. Medido el 2026-08-20.
    #
    # `spa.py` no lo salvaba: su `PREFIJOS_DE_API` decide qué NO es de la SPA,
    # pero sólo actúa sobre lo que llega hasta él, y acá el router se lo comía
    # antes. Con el prefijo bajo `/api` se acomoda a la convención del producto,
    # igual que `/api/usuarios` en vez del `/users` del kit.
    app.include_router(
        build_logs_router(AUDITABLES, prefix="/api/logs"),
        dependencies=[Depends(require_admin)],
    )

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
    # `GET`/`PUT /config/arca`, la pestaña de ARCA de la pantalla compartida.
    # Sin `/api` a propósito: es el prefijo que consume el kit — ver el módulo.
    app.include_router(facturacion_router.router, dependencies=[Depends(require_admin)])

    # `GET /api/facturas` y su PDF: el listado de comprobantes emitidos.
    #
    # Admin también para leer, y es distinto del resto de la facturación: la
    # factura de SU reserva la ve el mostrador desde el turno
    # (`GET /api/reservas/{id}/factura`, `require_staff`). Lo que es de admin es
    # ver TODO lo facturado por el complejo de una sentada — mismo criterio que
    # el historial de caja y el log de actividad.
    app.include_router(facturas_router.router, dependencies=[Depends(require_admin)])

    # `GET`/`PUT /config/mercadopago`: con qué cuenta cobra el QR del mostrador.
    # Admin por el mismo motivo que ARCA — quien escriba acá cambia a qué cuenta
    # va la plata del complejo. El mostrador *usa* el QR sin poder leer esto:
    # `GET /api/reservas/mp/estado` le dice si está configurado, y nada más.
    app.include_router(mercadopago_router.router, dependencies=[Depends(require_admin)])

    # La caja por turno. Sin `dependencies` acá: cada endpoint declara su rol —
    # el mostrador abre y cobra en su propia caja, el historial es de admin, y
    # cerrar depende del turno, no sólo de quién pide.

    app.include_router(caja_router.router)

    # La cuenta corriente. Mismo criterio que la caja: el mostrador fía y cobra
    # —es quien está frente al cliente—, y la lista de deudores es de admin.
    app.include_router(cuenta_corriente_router.router)

    # El buffet. Sin `dependencies`: el catálogo y el alta de producto son de
    # admin —definen precio—, y vender y reponer son de mostrador.
    app.include_router(buffet_router.router)

    # `GET /api/resumen`, lo que esta sucursal le contesta al panel del dueño.
    # Gateado por `LIBRA_PANEL_TOKEN` adentro de la factory, no por sesión: el
    # que pregunta es otra máquina.
    #
    # Puede venir `None`: sin base de LibraCore no hay núcleo que contestar, y
    # entonces **no se monta**. Un 404 dice "esta instancia no informa"; un
    # endpoint que contesta ceros diría "informa que no vendió nada".
    # El portal público: `/api/portal`. **El único router sin sesión de staff
    # detrás**, así que las reglas de qué se devuelve viven en
    # `servicios/portal.py` y no en el handler.
    app.include_router(portal_router.router)

    # 🔴 El simulador de pago **no se monta en producción**. Confirma una
    # reserva sin que nadie haya pagado: en la instancia de un complejo,
    # cualquiera con la URL se lleva los viernes a la noche gratis. Devuelve
    # `None` según el entorno, y por eso el `if` está acá y no adentro del
    # handler — un `if` mal escrito adentro deja el endpoint existiendo.
    simulador = portal_router.construir_router_de_simulacion(config.entorno)
    if simulador is not None:
        app.include_router(simulador)

    resumen = resumen_router.construir_router()
    if resumen is not None:
        app.include_router(resumen)

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
    # Terminos y Condiciones del Servicio: la prueba de la aceptacion y lo que
    # enciende el gate. MISMA fabrica de sesiones que el SMTP y los usuarios --
    # la tabla tiene FK a `usuarios`, que no siempre vive en la base del dominio.
    #
    # 🔴 Sin esta linea el gate NO corta y la instancia no falla: se queda sin
    # gate, en silencio. Por eso cada producto tiene un test que lo prueba.
    app.state.terminos = TerminosRepository(db.fabrica_de_sesiones())
    app.state.password_reset = PasswordResetService(
        db.fabrica_de_sesiones(),
        product_name="LibraClub",
        reset_url_base=os.environ.get(
            "LIBRACLUB_RESET_URL_BASE", "https://dev.libraclub.com.ar/reset-password"
        ),
        # CALLABLE, no un valor: se resuelve en cada envío. Con un valor fijo,
        # guardar el SMTP desde la pantalla de Configuración no tendría efecto
        # hasta recrear el contenedor.
        smtp_config=lambda: resolver_smtp_config(db.fabrica_de_sesiones()),
    )
    app.include_router(build_smtp_settings_router())
    # `GET /terminos`, `POST /terminos/aceptar`, `GET /terminos/historial`.
    # NO se gatea desde afuera: es el unico camino para salir del gate.
    app.include_router(build_terminos_router())

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
