"""Construcción de la aplicación.

`crear_app()` no se ejecuta al importar: el entrypoint es `app/asgi.py`. Es a
propósito — con la app armada al importar, la configuración queda resuelta por
el primer import y un test que quiera otra base ya llega tarde.
"""

from __future__ import annotations

import logging
import os

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from libraauth.auditoria import (
    AuditoriaBase,
    AuditoriaRepository,
    agregar_middleware_de_usuario,
    build_logs_router,
    configurar_auditoria,
)
from libraauth.auth_events import AuthEventRepository, ip_del_request
from libraauth.bootstrap import ensure_default_admin, ensure_demo_user
from libraauth.demo_codigos import DemoCodigoRepository
from libraauth.migrar import exigir_schema_al_dia
from libraauth.password_reset import PasswordResetService
from libraauth.secretos import SecretosRepository
from libraauth.session_auth import (
    build_demo_codigos_router,
    build_smtp_settings_router,
    demo_username,
)
from libraauth.smtp_settings import SmtpSettingsRepository
from libraauth.terminos import TerminosRepository, build_terminos_router
from libracommerce.erp import offline_stock
from libracore import config_manager as _lc_config_manager
from libracore.arca_router import build_arca_router
from libracore.avisos_router import build_avisos_router
from libracore.caja_router import build_cierre_diario_router
from libracore.candados import una_vez_al_arrancar
from libracore.cola_arca import pedidos_a_emitir
from libracore.cola_arca_router import build_cola_del_nodo_router
from libracore.config_router import (
    build_backup_router,
    build_empresa_admin_router,
    build_empresa_router,
)
from libracore.consultar_cuit_router import build_consultar_cuit_router
from libracore.db.core import get_connection as lc_get_connection
from libracore.docs_api import cerrar_docs_de_la_api
from libracore.errores import instalar_registro_de_errores
from libracore.estado_del_sistema import build_estado_del_sistema_router
from libracore.marca_router import build_marca_admin_router, build_marca_router, es_marca_propia, nombre_de_marca
from libracore.mp_config_router import build_mp_config_router
from libracore.nodo_conexion_router import build_conexion_del_nodo_router
from libracore.nodo_offline import SinConexion, SoloEnElCentral
from libracore.resguardo_enlace import build_resguardo_enlace_router
from libracore.respaldo import Instancia
from libracore.corte_de_servicio import CorteDeServicioMiddleware
from libracore.security_headers import CSP_SPA, SecurityHeadersMiddleware
from libracore.smtp_router import build_smtp_probe_router
from libracore.tema_router import build_tema_admin_router, build_tema_router
from libracore.terminos_propios import leer_terminos_propios
from libraedge.pantalla_del_central import create_canje_router, create_nodos_router

from app import db, offline
from app.addons import require_addon
from app.auth import (
    UserRepository,
    construir_session_auth,
    get_current_user,
    require_admin,
    require_admin_o_servicio,
    require_staff,
)
from app.config import Config, misma_base
from app.frontend_dist import frontend_dist
from app.models.maestros import Sucursal
from app.routers import (
    admin,
    clientes_en_conflicto,
    conflictos,
    disponibilidad,
    eventos,
    maestros,
    reservas,
    salud,
    sincronizacion_offline,
    torneos,
)
from app.routers import ausentismo as ausentismo_router
from app.routers import auth as auth_router
from app.routers import avisos as avisos_router
from app.routers import buffet as buffet_router
from app.routers import caja as caja_router
from app.routers import cajas as cajas_router
from app.routers import cuenta_corriente as cuenta_corriente_router
from app.routers import devoluciones as devoluciones_router
from app.routers import facturas as facturas_router
from app.routers import mp_bandeja as mp_bandeja_router
from app.routers import portal as portal_router
from app.routers import resumen as resumen_router

# Con alias: más abajo hay una variable local `usuarios` con el repositorio, y
# sin el alias el import queda pisado.
from app.routers import usuarios as usuarios_router
from app.routers.facturacion import exigir_base
from app.servicios import buffet as servicio_buffet
from app.servicios import caja as servicio_caja
from app.servicios import cierre_diario as servicio_cierre_diario
from app.servicios import facturacion
from app.servicios import facturacion as servicio_facturacion
from app.smtp import smtp_config

_log = logging.getLogger(__name__)

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
    # El evento agrupa categorías: quién le cambió las fechas o las canchas mueve
    # a todos los torneos de adentro.
    "Evento": "evento",
    "Competidor": "competidor",
    "PartidoDeTorneo": "partido de torneo",
}


def _instancia_a_respaldar(config: Config) -> Instancia:
    """Qué se lleva el backup.

    🔴 **Con DOS bases, las dos tienen que entrar.** Hoy no queda ninguna así
    (ADR-020), pero una instancia con la variable del core apuntando a otra base
    corre `libracore` contra una base propia —ver
    `servicios/facturacion.py`—, así que un backup del dominio solo **no se puede
    restaurar**: o volvés las reservas y te quedan las facturas de otro momento,
    o al revés. Y no falla: da un ZIP que se descarga y pesa poco, que es la peor
    forma de perder datos.

    🔑 **Con una sola base** (ADR-020: dominio y core juntos) el dump de la
    principal ya lo trae todo, y declararla dos veces haría que las dos cayeran
    en `libraclub.dump` —`Instancia` lo rechaza al arrancar—. Por eso el core va
    como extra sólo si es OTRA base. En una instancia sin facturar tampoco hay
    nada del otro lado que respaldar.

    `directorios=[]` todavía: no hay logos ni adjuntos. **El certificado de ARCA
    sí es un archivo**, y cuando se suba por pantalla hay que decidir
    explícitamente si entra al ZIP — un backup con la clave privada adentro es un
    archivo que circula por mail.
    """
    otra_base = config.libracore_database_url and not misma_base(
        config.database_url, config.libracore_database_url
    )
    extra = [config.libracore_database_url] if otra_base else []
    return Instancia(
        nombre="libraclub", postgres_url=config.database_url, postgres_extra=extra,
    )


def migrar_secretos() -> dict:
    """Saca de `config.json` los secretos que quedaron en claro. Idempotente.

    Corre en cada `crear_app()`, así la migración de una instancia viva **es su
    deploy**. Loguea NOMBRES de claves, nunca valores: un log con el secreto lo
    muda del archivo a una superficie peor, porque los logs se copian y se
    mandan.

    Si cifrar falla, el `config.json` **no se toca** —la instancia sigue
    cobrando con la credencial que tiene— y se loguea como error, que es lo
    que después ve la sonda `auditar_secretos.py`.
    """
    informe = _lc_config_manager.migrar_secretos_al_almacen()
    if informe["migradas"]:
        _log.warning(
            "secretos movidos de config.json al almacen cifrado: %s",
            ", ".join(informe["migradas"]),
        )
    if informe["ya_estaban"]:
        _log.warning(
            "config.json tenia una copia vieja de %s; se vacio (el almacen manda)",
            ", ".join(informe["ya_estaban"]),
        )
    if informe["fallaron"]:
        _log.error(
            "no se pudieron cifrar y QUEDAN EN CLARO en config.json: %s",
            ", ".join(f"{k} ({v})" for k, v in informe["fallaron"].items()),
        )
    return informe


async def _contestar_409_de_nodo(request: Request, exc: SinConexion | SoloEnElCentral) -> JSONResponse:
    return JSONResponse({"detail": exc.detalle()}, status_code=409)


async def _contestar_409_sin_ubicacion(request: Request, exc: servicio_buffet.SinUbicacion) -> JSONResponse:
    """En un nodo, el depósito del buffet tiene que venir del central: si falta, 409 con lo que hay que hacer."""
    return JSONResponse({"detail": str(exc)}, status_code=409)


#: Los routers cuyos datos manda el central: en un nodo se leen del espejo y se escriben sólo en el central (409
#: `solo_en_el_central`). Lo mismo en el central: no hace nada. Ver `app/offline.py`.
_DEL_CENTRAL = [Depends(offline.escritura_solo_en_el_central)]


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
    facturacion.configurar(config.libracore_database_url, url_del_dominio=config.database_url)

    # 🔴 Las tablas de auth las crea la cadena de LibraAuth (`libraauth-migrar
    # upgrade --prefijo libraclub --base dominio`, declarada en `scripts/panel_admin.py`),
    # no el arranque. Desde libraauth v0.45 (2026-09-17) el arranque la EXIGE: si no
    # corrió, la app no levanta y el error dice el comando. Hasta ese día acá había
    # un `AuthBase.metadata.create_all(motor)` que tapaba cualquier camino que se
    # olvidara de migrar.
    exigir_schema_al_dia(motor, prefijo="libraclub", base="dominio")
    # El log de actividad cuelga de su propio `Base`, no del de `models.py`: la
    # tabla tiene que quedar en la base del DOMINIO, que es donde ocurren las
    # escrituras que audita y donde vive la transacción. En LibraClub las dos
    # son la misma base, pero se respeta igual — es el contrato del motor.
    AuditoriaBase.metadata.create_all(motor)

    usuarios = UserRepository(db.fabrica_de_sesiones())

    # 🔴 Los secretos de terceros de `config.json` —el access token y la firma
    # de webhook de MercadoPago, y la contraseña SMTP— dejan de vivir en texto
    # plano (libracore v1.108.0 + libraauth v0.46.0, 2026-09-17). Se enchufa
    # ACÁ, justo después de `usuarios`, porque `db.fabrica_de_sesiones()` es el
    # MISMO session factory que ese `UserRepository`: apunta a la base
    # DOMINIO, la que `exigir_schema_al_dia()` (arriba) ya garantizó que está
    # en la revisión `0002` de la cadena de libraauth — la que crea
    # `secretos_instancia`. Va DESPUÉS de esa línea a propósito: escribir en la
    # tabla antes de saber que existe convertiría un schema viejo en un 500 en
    # vez del error que dice el comando.
    #
    # LibraCore no importa libraauth: recibe el almacén. Por eso el enganche es
    # del producto, que es el único que tiene los dos paquetes.
    #
    # Se re-arma en cada `crear_app()` y no una vez a nivel de módulo —como en
    # los productos donde `_Sesion` nace al importar— porque acá el
    # `sessionmaker` nace ADENTRO de esta función (`db.inicializar()` corrió
    # unas líneas más arriba): un enganche a nivel de módulo apuntaría a un
    # `_Sesion` que todavía no existe.
    _secretos = SecretosRepository(db.fabrica_de_sesiones())
    _lc_config_manager.usar_almacen_de_secretos(_secretos)
    migrar_secretos()

    # 🔴 Las siembras de abajo son «si no existe, crear», y con `uvicorn --workers N` (ADR-044 de libracore; hoy N =
    # 1) cada worker corre este arranque: las dos preguntas «¿existe?» se contestan «no» antes de que ninguna haya
    #   creado. `una_vez_al_arrancar` las serializa (el segundo espera al primero y ve lo que dejó), y por eso cada
    #   una **sigue preguntando adentro**: el candado las ordena, no las saltea. `destino` es la base del dominio:
    #   `libracore.db` puede no estar configurada (una instancia sin facturación arranca igual).
    with una_vez_al_arrancar("libraclub-sembrar", destino=config.database_url):
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

        # Una caja por sucursal, para las instancias que ya venían andando.
        #
        # 🔑 **Sin esto, subir esta versión deja al mostrador sin poder abrir el
        # turno**: desde ahora el turno se abre SOBRE una caja, no habría ninguna
        # para elegir, y crearla es de admin. Es idempotente — en el segundo
        # arranque no crea nada.
        #
        # Va detrás de `hay_base()` porque las cajas viven en LibraCore: una
        # instancia sin facturación configurada arranca igual, sin cajas y sin caja
        # que abrir, exactamente como antes de este cambio.
        if servicio_facturacion.hay_base():
            with db.fabrica_de_sesiones()() as sesion_bootstrap:
                sedes = [
                    (fila.id, fila.nombre)
                    for fila in sesion_bootstrap.query(Sucursal).filter_by(activa=True).all()
                ]
            creadas = servicio_caja.asegurar_cajas_de_todas(sedes)
            if creadas:
                _log.info("Se crearon %s cajas iniciales, una por sucursal", creadas)

    app = FastAPI(
        title="LibraClub",
        description="Gestión de complejos deportivos — familia Libra",
        version="0.1.0",
    )
    cerrar_docs_de_la_api(app)
    # Lo que un nodo de LibraEdge contesta con un 409 y no con un 500 (ADR-022): una guarda de las reservas que
    # levanta desde un servicio al que no llega ninguna traducción por ruta (torneos, series). El mismo cuerpo que
    # los routers del motor: `{"detail": {"codigo", "mensaje"}}`.
    for excepcion in (SinConexion, SoloEnElCentral):
        app.add_exception_handler(excepcion, _contestar_409_de_nodo)
    # Las reservas que se dan en un nodo (PR 12, ADR-022) se enchufan al outbox. Fuera de un nodo no hacen nada.
    offline.configurar_reservas()
    # Y los clientes que se dan de alta en el nodo (addendum de ADR-022).
    offline.configurar_clientes()
    # El router de `libraauth` los lee de acá por nombre: sin estos dos, el login
    # devuelve 500 al primer request y no al arrancar.
    app.state.users = usuarios
    app.state.session_auth = construir_session_auth(usuarios)
    # Para que un test pueda verificar el enganche sin pasar por
    # `config_manager` (que devuelve el secreto en claro por diseño y daría
    # verde igual con la implementación vieja) — ver `tests/test_secretos_config_json.py`.
    app.state.secretos = _secretos

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

    # 🔴 Los headers de seguridad. Se agrega **al final** a proposito: en
    # Starlette el ultimo middleware agregado es el mas externo, asi que asi
    # envuelve a todas las respuestas, incluidas las de error que devuelven los
    # de adentro.
    #
    # `CSP_SPA` y no la CSP por defecto: esa habilita `cdn.jsdelivr.net` para las
    # apps Jinja2, y este producto no carga nada externo. Ver libracore.
    # El corte de servicio (ADR-096 de libracore): una instancia suspendida deja de atender. Antes que
    # SecurityHeadersMiddleware, para que la respuesta del corte salga con las cabeceras de seguridad.
    app.add_middleware(CorteDeServicioMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, csp=CSP_SPA)
    # El registro de errores de la familia (ADR-045 de libracore): un 500 deja una línea en
    # `DATA_DIR/errores/errores.jsonl` y responde con un `ref`; monta `POST /api/errores-cliente` para los errores del
    # navegador. Una sola línea, **al construir la app**: Starlette no deja sumar handlers después.
    instalar_registro_de_errores(app, "libraclub")
    # El central se niega a mover el stock de una sucursal con nodo (libracommerce ADR-071):
    # `DepositoDeSucursalConNodo` no es un `ValueError` (los routers los pasan a 422) y acá es un 409
    # `deposito_de_sucursal_con_nodo`. Una vez, al construir.
    offline_stock.instalar_manejador_409(app)
    app.add_exception_handler(servicio_buffet.SinUbicacion, _contestar_409_sin_ubicacion)

    app.include_router(salud.router)
    # La sincronización del nodo offline (LibraEdge, ADR-023): `/sync/v1/push`, `/pull`, `/ticket-arca` y
    # `/carga-inicial`. Se monta siempre: sin un nodo registrado no hay ningún secreto válido y todo contesta 401. La
    # autenticación es el secreto del nodo, no la sesión: por eso no lleva guarda de rol (en la matriz son rutas
    # «PÚBLICA, secreto del nodo»).
    app.include_router(sincronizacion_offline.router)
    # «Sucursal sin internet» (libraedge ADR-011 y ADR-014): el admin da de alta el nodo de una sucursal y se lleva la
    # dirección y un código de vinculación, ve los nodos y los da de baja. Toda la lógica es de LibraEdge; acá sólo la
    # guarda (cambia la estructura de la instancia: sólo admin) y el aprovisionamiento de `app/offline.py`.
    app.include_router(
        create_nodos_router(offline.aprovisionamiento, lc_get_connection),
        dependencies=[Depends(require_admin)],
    )
    # El canje del código (libraedge ADR-014): `POST /sync/v1/vinculacion`. **Sin guarda a propósito**: lo llama el
    # instalador del nodo, que no tiene sesión; lo protegen el código (un solo uso, 15 minutos) y el límite de
    # intentos del motor. La IP real detrás del proxy es la de libraauth.
    app.include_router(create_canje_router(offline.aprovisionamiento, lc_get_connection, ip_del_request=ip_del_request))
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
        # Los clientes se dan de alta en el nodo (id provisorio, `cliente_club.alta`): su router lleva sus propias
        # guardas (editar y borrar son del central) y no la general de los maestros.
        propias = [] if router in maestros.CON_ALTA_EN_NODO else _DEL_CENTRAL
        app.include_router(router, dependencies=propias)
    # Los reincidentes de ausentismo. Vive bajo `/api/clientes` pero con dos
    # segmentos, así que no depende de ir antes o después del ABM de clientes.
    app.include_router(ausentismo_router.router, dependencies=_DEL_CENTRAL)
    # Qué tipos de aviso salen (ADR-029, ADR-030): `/api/avisos/tipos`. Los manda el cron del central: en el nodo no
    # hay qué mostrar.
    app.include_router(avisos_router.router, dependencies=_DEL_CENTRAL)
    # Cómo salen y qué salió: WhatsApp (apagado, registro o Evolution), «probar envío» y el registro, del motor
    # (libracore ADR-090) en el mismo prefijo `/api/avisos`. El gate es el del producto y cubre las cuatro rutas: la
    # configuración dice con qué cuenta de WhatsApp habla el club y el registro tiene los teléfonos y los textos de
    # sus clientes. El `smtp_config` es el MISMO resolver del envío de comprobantes y de la recuperación de contraseña
    # (`app/smtp.py`). En un nodo, el `PUT` y el «probar» contestan 409 `solo_en_el_central` por su cuenta (el nodo no
    # manda avisos).
    app.include_router(build_avisos_router(require_admin=require_admin, smtp_config=smtp_config))
    app.include_router(reservas.router)
    # Las reservas en conflicto (ADR-022). Prefijo propio y no `/api/reservas/conflictos`: `GET /api/reservas/{id}`
    # lo leería como un id.
    app.include_router(conflictos.router)
    # Los cambios de clientes en conflicto (ADR-022, tercer addendum): ver los dos valores y elegir cuál queda.
    app.include_router(clientes_en_conflicto.router)
    # Los torneos. Sin `dependencies`: definir y sortear son de admin —cambian
    # lo que el complejo se comprometió a jugar— e inscribir, programar y cargar
    # resultados son de mostrador. Cada endpoint declara el suyo.
    app.include_router(torneos.router, dependencies=_DEL_CENTRAL)
    # Los eventos (ADR-024): agrupan categorías —cada una un torneo— con las mismas fechas y canchas.
    app.include_router(eventos.router, dependencies=_DEL_CENTRAL)
    app.include_router(disponibilidad.router)
    app.include_router(usuarios_router.router, dependencies=_DEL_CENTRAL)
    app.include_router(admin.router, dependencies=_DEL_CENTRAL)
    # El panel del dueño de la pantalla (F5, ADR-027). Es una lectura: se puede abrir en un nodo.
    app.include_router(admin.router_api)

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
    # ARCA, del motor. Reemplaza al `routers/facturacion.py` propio, que sobre
    # el MISMO prefijo `/config/arca` sólo tenía `GET` y `PUT`, y pedía el
    # certificado como un PATH DEL FILESYSTEM del servidor en un campo de texto.
    #
    # 🔴 Con eso el alta no se podía hacer desde el navegador: alguien tenía que
    # dejar el `.crt` y el `.key` dentro del volumen del contenedor a mano. Con
    # el router del motor el par se sube y se VALIDA antes de escribirse, la
    # pantalla dice cuándo vence el certificado, y hay un botón que autentica
    # contra WSAA de verdad.
    #
    # `empresa_por_defecto` es el slug con el que `servicios/facturacion.py` lee
    # la configuración. Sin él, una instancia que todavía no facturó crearía la
    # fila como `default` — donde ese servicio no mira nunca.
    #
    # ⚠️ `exigir_base` NO es opcional y no viene del motor: sin ella, una
    # instancia sin `LIBRACLUB_LIBRACORE_DATABASE_URL` contestaría un 500
    # genérico en vez del 503 que dice **qué variable falta**. Es la misma
    # dependencia que ya usaba el router propio.
    app.include_router(
        build_arca_router(
            prefix="/config/arca", empresa_por_defecto=servicio_facturacion.EMPRESA,
        ),
        dependencies=[Depends(require_admin), Depends(exigir_base), *_DEL_CENTRAL],
    )

    # Consulta de CUIT en el padrón de ARCA (`GET /api/consultar-cuit/{cuit}`): el router del motor, el que usan
    # Contalibra, Restolibra y VentaLibra. Completa nombre, domicilio y condición de IVA del alta de un cliente a
    # partir del CUIT. Lee la fila activa de `arca_config` (la que escribe el router de arriba) y autentica contra
    # `ws_sr_padron_a13` con el par de la facturación: sin certificados contesta 503, y si ARCA no delegó ese
    # servicio al certificado, 403 con el paso a seguir.
    #
    # Va con `require_staff`, el mismo gate que el alta de `clientes` (`routers/maestros.py`): es trabajo de
    # mostrador, y si pidiera admin el encargado no podría completar al cliente que llama por primera vez. Y con
    # `exigir_base`, como el router de ARCA: lee `arca_config` de la base de LibraCore.
    app.include_router(
        build_consultar_cuit_router(usuario_actual=get_current_user),
        dependencies=[Depends(require_staff), Depends(exigir_base)],
    )

    # Los comprobantes: los doce endpoints del motor —listado, alta manual,
    # detalle, duplicar, autorizar, cobrar, mandar por mail, borrar, nota de
    # crédito y nota de débito— más el PDF, que es de este producto.
    #
    # Admin para todo, también para leer, y es distinto del resto de la
    # facturación: la factura de SU reserva la ve el mostrador desde el turno
    # (`GET /api/reservas/{id}/factura`, `require_staff`). Lo que es de admin es
    # ver TODO lo facturado por el complejo de una sentada, y emitir a mano —
    # mismo criterio que el historial de caja y el log de actividad.
    #
    # 🔑 **Van los DOS**, y el orden no importa: el del motor no tiene ninguna
    # ruta `/{id}/pdf`, así que no se pisan.
    # 🔴 `exigir_base` va en el montaje y no adentro del motor: el factory es de
    # LibraCore, y ahí la base SIEMPRE existe. Acá no —un complejo que todavía no
    # factura levanta igual—, y sin esta guarda sus doce endpoints contestarían
    # un error de conexión de psycopg en vez del 503 que nombra la variable que
    # falta. Lo agarró `test_sin_base_de_libracore_el_listado_lo_DICE`, que se
    # escribió para el listado hecho a mano y sobrevivió al reemplazo.
    #
    # 🔴 En un nodo se leen y no se escriben: emitir, autorizar o anular a mano numeraría con
    # `get_next_numero_with_arca`, y sin red eso cae a la numeración local (libracore ADR-074). La factura de una
    # reserva sale por la cola de ARCA (`POST /api/reservas/{id}/facturar`, ADR-023).
    app.include_router(
        facturas_router.comprobantes,
        dependencies=[Depends(require_admin), Depends(exigir_base), *_DEL_CENTRAL],
    )
    app.include_router(
        facturas_router.router,
        dependencies=[Depends(require_admin), Depends(exigir_base), *_DEL_CENTRAL],
    )

    # `GET`/`PUT /api/config/mercadopago`: con qué cuenta cobra el QR del
    # mostrador. Admin por el mismo motivo que ARCA — quien escriba acá cambia a
    # qué cuenta va la plata del complejo. El mostrador *usa* el QR sin poder
    # leer esto: `GET /api/reservas/mp/estado` le dice si está configurado, y
    # nada más.
    #
    # 🔴 **El prefijo NO se escribe acá: se deja el del motor.** Hasta el
    # 2026-08-31 esto montaba en `/config/mercadopago` —la ruta del endpoint
    # propio que existía antes de la unificación— mientras la tarjeta compartida
    # de `libra-ui` pide `/api/config/mercadopago`. La pantalla recibía un 404,
    # caía al `catch` y se dibujaba **vacía**: sin campos y sin el cartel de
    # ambiente, con la configuración perfectamente cargada del otro lado. Nadie
    # lo vio hasta que el humano fue a mirar la pantalla.
    #
    # Los dos tests que debían agarrarlo estaban en verde porque **ninguno
    # cruzaba la frontera**: el de backend pedía la ruta vieja y el mock del de
    # frontend devolvía datos para la nueva. Cada mitad confirmaba su propia
    # suposición.
    #
    # 🔴 `campo_auto_facturar` sí es de acá: es la clave de `config.json` que lee
    # `servicios/cobro_qr`, porque lo que se cobra con este QR es un TURNO de
    # cancha, no una venta. Con la clave por defecto del motor —`..._ventas`— el
    # interruptor escribiría donde nadie lee: la pantalla diría que está
    # prendido y no se emitiría ninguna factura, sin un solo error. Ver LibraCore
    # v1.62.0.
    app.include_router(
        build_mp_config_router(campo_auto_facturar="mp_auto_facturar_reservas"),
        dependencies=[Depends(require_admin), *_DEL_CENTRAL],
    )

    # La bandeja de MercadoPago: conciliar lo que entró y facturarlo. Es la
    # del motor, con el reparto por `external_reference` de este producto —
    # ver `routers/mp_bandeja.py`.
    #
    # 🔑 Admin, y con `exigir_base`: la bandeja vive en la base de LibraCore,
    # así que un complejo sin facturación configurada tiene que recibir el
    # 503 que nombra la variable y no un error de conexión de psycopg.
    app.include_router(
        mp_bandeja_router.router,
        dependencies=[Depends(require_admin), Depends(exigir_base), *_DEL_CENTRAL],
    )

    # La cola de comprobantes de ARCA del nodo (libracore ADR-079): lo que quedó esperando sin conexión, para avisarlo
    # y para que alguien resuelva lo que quedó a revisar. Staff mira y pide emitir; reintentar, descartar y marcar
    # emitido deciden sobre un documento fiscal: sólo admin. Fuera de un nodo contesta `es_nodo: false` y no hace nada.
    app.include_router(
        build_cola_del_nodo_router(cola=offline.cola(), usuario_actual=require_staff, resolver_con=require_admin),
        dependencies=[Depends(exigir_base)],
    )
    # Lo que el cartel «sin conexión» de libra-ui necesita saber (`GET /api/nodo/conexion`, libracore ADR-084): si esta
    # instancia es un nodo y si tiene conexión. Antes la pantalla se lo preguntaba a la cola, que trae una lista de
    # pedidos que no usa. Cualquier usuario de la instancia (la pantalla lo lee en cuanto carga la sesión); no lee
    # `arca_config`, así que no pide `exigir_base`.
    app.include_router(
        build_conexion_del_nodo_router(conexion=offline.CONEXION, usuario_actual=get_current_user),
        dependencies=[Depends(require_staff)],
    )

    # La caja por turno. Sin `dependencies` acá: cada endpoint declara su rol —
    # el mostrador abre y cobra en su propia caja, el historial es de admin, y
    # cerrar depende del turno, no sólo de quién pide.

    app.include_router(caja_router.router)

    # Las cajas: los mostradores de cada sucursal. Cada endpoint declara su
    # rol — el listado lo lee el mostrador para elegir dónde abrir el turno;
    # el alta, la edición y la baja son de admin.
    app.include_router(cajas_router.router, dependencies=_DEL_CENTRAL)

    # El cierre diario por sucursal (F1 del motor, ADR-011): vista previa,
    # cerrar, listar y los dos tickets de 80 mm. `require_staff` en las dos
    # puntas: en `usuario_actual` porque cualquiera de las dos únicas
    # credenciales de este producto (admin, staff) puede consultar el cierre —
    # es la misma población que ya lee la caja—, y en `autorizar_cierre` porque
    # el pedido del humano (2026-09-13) es que "lo puede hacer el admin o un
    # cajero", y en LibraClub el cajero es el rol `staff`.
    #
    # `resolver_sucursal_nombre` es lo que le permite al motor mostrar el
    # nombre de la sede sin conocer la tabla `Sucursal`, que vive del lado del
    # dominio. `exigir_base` porque el cierre diario vive en la base de
    # LibraCore: sin `LIBRACLUB_LIBRACORE_DATABASE_URL` esta instancia todavía
    # no tiene dónde guardarlo. El listado trae `cerrado_por_nombre` desde
    # libracore v1.98.1: no hace falta ningún endpoint propio encima.
    app.include_router(
        build_cierre_diario_router(
            usuario_actual=require_staff,
            resolver_sucursal_nombre=servicio_cierre_diario.resolver_sucursal_nombre,
            autorizar_cierre=Depends(require_staff),
            # En un nodo el cierre del día sube al central (libracore ADR-076); fuera de un nodo no hace nada.
            ganchos_de_caja=offline.GANCHOS_DE_CAJA,
        ),
        dependencies=[Depends(exigir_base)],
    )

    # Las devoluciones de seña que quedaron pendientes. El listado es de staff
    # —el encargado tiene que poder contestarle al jugador que llama— y el
    # reintento, de admin: mover plata hacia afuera es del dueño. Cada endpoint
    # declara su rol adentro.
    app.include_router(devoluciones_router.router, dependencies=_DEL_CENTRAL)

    # La cuenta corriente. Mismo criterio que la caja: el mostrador fía y cobra
    # —es quien está frente al cliente—, y la lista de deudores es de admin.
    app.include_router(cuenta_corriente_router.router, dependencies=_DEL_CENTRAL)

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

    # Y el del cobro por QR del mostrador, por lo mismo: acredita un cobro sin
    # que haya entrado un peso. El `if` va acá y no adentro del handler.
    simulador_qr = reservas.construir_router_de_simulacion_qr(config.entorno)
    if simulador_qr is not None:
        app.include_router(simulador_qr)

    # Y el de la venta de buffet, que confirma una venta y anota el ingreso sin
    # que haya entrado un peso: en la instancia de un complejo, cualquiera con la
    # URL vacía el buffet. Es un builder propio y no el de arriba a propósito —
    # ver el docstring de `buffet.construir_router_de_simulacion_qr`.
    simulador_qr_buffet = buffet_router.construir_router_de_simulacion_qr(config.entorno)
    if simulador_qr_buffet is not None:
        app.include_router(simulador_qr_buffet)

    resumen = resumen_router.construir_router()
    if resumen is not None:
        app.include_router(resumen)

    app.include_router(build_empresa_router(), dependencies=[Depends(require_admin)])
    app.include_router(build_empresa_admin_router(), dependencies=[Depends(require_admin)])

    # El tema de la suite (libracore ADR-012, libra-ui ADR-007/008): los colores que el backoffice de la
    # suite empuja a esta instancia. La lectura es PÚBLICA a propósito (el login también va con los
    # colores de la suite y no expone nada sensible). La escritura es del admin O del token de servicio
    # del backoffice: 🔴 con `require_admin` a secas el backoffice NO entraría (esa guarda no conoce el
    # token).
    app.include_router(build_tema_router())
    app.include_router(build_tema_admin_router(), dependencies=[Depends(require_admin_o_servicio)])
    # La marca de la instancia (nombre, logo, color, iconos y manifest), para venderla a marca blanca. La lectura es
    # publica (el login tambien lleva la marca) y va **antes** del catch-all de la SPA (`asgi.py`): si no,
    # `/manifest.webmanifest` devolveria el `index.html`. Escribir es del admin o del backoffice (token de servicio).
    app.include_router(build_marca_router(dist=frontend_dist()))
    app.include_router(build_marca_admin_router(), dependencies=[Depends(require_admin_o_servicio)])

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
    #
    # Marca blanca (ADR-092/093 del motor): una instancia con marca propia **exige** los Terminos de su revendedor
    # y, sin ellos, queda frenada; nunca cae a los de la familia.
    app.state.terminos = TerminosRepository(
        db.fabrica_de_sesiones(), contrato_propio=leer_terminos_propios, exigir_propio=es_marca_propia
    )
    app.state.password_reset = PasswordResetService(
        db.fabrica_de_sesiones(),
        # CALLABLE: con marca propia el mail de recuperacion sale con el nombre del revendedor.
        product_name=lambda: nombre_de_marca("LibraClub"),
        reset_url_base=os.environ.get(
            "LIBRACLUB_RESET_URL_BASE", "https://dev.libraclub.com.ar/reset-password"
        ),
        # CALLABLE, no un valor: se resuelve en cada envío. Con un valor fijo,
        # guardar el SMTP desde la pantalla de Configuración no tendría efecto
        # hasta recrear el contenedor.
        # El MISMO resolver que usa el envío de comprobantes — ver `app/smtp.py`.
        # Que cada envío lo resolviera por su cuenta es exactamente como la
        # familia terminó con dos configuraciones de SMTP distintas.
        smtp_config=smtp_config,
    )
    app.include_router(build_smtp_settings_router())
    # `POST /admin/smtp/probar`, del motor: abre la conexion, negocia TLS y
    # hace login.
    #
    # 🔑 Resuelve por el MISMO camino que los envios, y por eso el boton
    # significa algo: un endpoint que probara otra config diria "Conectado"
    # contra un servidor mientras los mails salen por otro. El gate va afuera
    # porque el router del motor no trae ninguno propio, y esto abre una
    # sesion SMTP con las credenciales del cliente.
    app.include_router(
        build_smtp_probe_router(smtp_config),
        dependencies=[Depends(require_admin)],
    )
    # `GET /terminos`, `POST /terminos/aceptar`, `GET /terminos/historial`.
    # NO se gatea desde afuera: es el unico camino para salir del gate.
    app.include_router(build_terminos_router())

    # Una sola variable para los dos routers de abajo: el enlace deja el
    # `rclone.conf` adentro de ESTE directorio (`.resguardo/`), y el subidor del
    # host lo busca ahí. Si cada uno armara su ruta, divergir sería un typo.
    backups_dir = os.path.join(config.directorio_de_datos, "backups")
    app.include_router(
        build_backup_router(
            _instancia_a_respaldar(config),
            backups_dir,
            cerrar_conexiones=motor.dispose,
            reabrir_conexiones=motor.dispose,
        ),
        dependencies=[Depends(require_admin)],
    )
    # La barra de estado del pie (libracore ADR-075, libra-ui ADR-083): usuario, versión, el certificado de ARCA y el
    # último respaldo, en una consulta. La abre cualquier rol de la instancia; lo que ve cada uno lo decide el motor
    # (ARCA y respaldo, sólo admin).
    app.include_router(
        build_estado_del_sistema_router(
            usuario_actual=get_current_user, backups_dir=backups_dir, conexion=offline.CONEXION,
            # La barra del pie: el nodo con las facturas que esperan su conexión, o los nodos del central.
            a_facturar=lambda: pedidos_a_emitir(offline.cola()), nodos_del_central=offline.nodos_del_central,
        ),
        dependencies=[Depends(require_staff)],
    )

    # La copia externa: el cliente conecta su Google Drive o Dropbox desde
    # Configuración → Datos / Backup (`/api/config/resguardo-externo/enlace`).
    # El router es del motor; subir sigue siendo del host, por cron.
    #
    # 🔴 **Es un ADD-ON**, no parte de ningún plan: viene apagado y se prende por
    # instancia desde el backoffice. Por eso el segundo gate es `require_addon`
    # y no el `require_module` del motor — ver `app/addons.py`. Apagado contesta
    # 403, que la pantalla lee como "sin plan" y esconde la tarjeta.
    #
    # El callback de OAuth queda detrás de los MISMOS dos gates a propósito: ver
    # el docstring de `build_resguardo_enlace_router`.
    app.include_router(
        build_resguardo_enlace_router(backups_dir, carpeta="Resguardo LibraClub"),
        dependencies=[Depends(require_admin), Depends(require_addon("resguardo_externo"))],
    )

    # En un nodo, un hilo emite lo que quedó en la cola de ARCA cuando vuelve la conexión (libracore ADR-079). Fuera de
    # un nodo no arranca nada. Con varios workers cada uno arranca el suyo: el candado por pedido evita la doble
    # emisión.
    def _arrancar_la_cola() -> None:
        app.state.parar_la_cola = offline.arrancar_cola()

    def _parar_la_cola() -> None:
        parar = getattr(app.state, "parar_la_cola", None)
        if parar is not None:
            parar.set()

    app.router.add_event_handler("startup", _arrancar_la_cola)
    app.router.add_event_handler("shutdown", _parar_la_cola)
    return app
