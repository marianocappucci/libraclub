"""`/api/portal` — lo que el jugador puede hacer desde internet.

🔴 **Es el único router del producto sin sesión de staff detrás.** Todo lo que
devuelve sale a internet, así que las reglas están en `servicios/portal.py` y
acá sólo se cablean.

El circuito completo:

1. `POST /registro` o `/login` → cookie de jugador
2. `GET /canchas` y `/disponibilidad` → qué hay libre y a cuánto
3. `POST /reservas` → retiene el turno **provisorio** y devuelve a dónde pagar
4. MercadoPago cobra → llama a `/webhook` → la reserva pasa a confirmada
5. Si no paga, `vencer-provisorias` libera el turno

**Sin el paso 4 no hay reserva.** Es la regla del producto.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from libraauth import auth_events
from libraauth import session_auth as _session_auth
from libracore import config_manager, mp_api, mp_sync
from libracore import pagos as acreditacion
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import es_produccion
from app.db import obtener_sesion
from app.models.maestros import Cancha, CuentaDeJugador
from app.models.reservas import PagoDeReserva, Reserva
from app.portal_sesion import borrar_cookie, crear_cookie, cuenta_actual, exigir_jugador
from app.routers.mp_bandeja import REFERENCIAS_PROPIAS
from app.servicios import devoluciones
from app.servicios import pagos as servicio_pagos
from app.servicios import partidos as servicio_partidos
from app.servicios import portal as servicio
from app.tiempo import TZ, hoy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portal", tags=["portal público"])


#: 🔑 Mismo default que `max_intentos_fallidos` de
#: `build_json_api_auth_router` (`libraauth.session_auth`, v0.40.0). Allá NO
#: es una constante de módulo, es el valor por defecto de un parámetro — no
#: hay nada que importar, así que se repite el número acá. Que sea el mismo
#: es lo que hace que el portal y el login de staff bloqueen en el mismo
#: punto (comparten la tabla `auth_log` y cuentan por IP, no por producto).
MAXIMO_INTENTOS_FALLIDOS = 5

#: `detalle` de los eventos que anota este router en `auth_log`, para
#: distinguirlos de los logins de staff que viven en la misma tabla.
DETALLE_PORTAL = "portal"

#: Evento propio para un alta exitosa desde el portal. No es "login": nadie
#: probó una contraseña. `libraauth.auth_events` admite eventos que no son los
#: tres suyos — están pensados justamente para esto (ver su docstring).
EVENTO_REGISTRO_PORTAL = "registro_portal"


def _jugador(request: Request, sesion: Session = Depends(obtener_sesion)) -> CuentaDeJugador:
    return exigir_jugador(request, sesion)


def _cortar_si_bloqueado(request: Request, username: str) -> None:
    """El MISMO bloqueo por intentos fallidos que usa el login de staff
    (`libraauth.session_auth.build_json_api_auth_router`), sobre la MISMA
    tabla `auth_log` y contando por IP: una IP que agotó sus intentos contra
    `/auth/login` tampoco entra por acá, y viceversa — es una sola defensa,
    no dos que conviven por separado.

    🔴 Va ANTES que el captcha y la credencial, igual que allá: chequear la
    credencial primero y cortar después le contestaría distinto a quien
    acertó la clave que a quien no, y el rate limiting se volvería un oráculo.
    """
    if not MAXIMO_INTENTOS_FALLIDOS:
        return
    recientes = auth_events.contar_fallidos_seguro(request, auth_events.VENTANA_FALLIDOS_MINUTOS)
    if recientes >= MAXIMO_INTENTOS_FALLIDOS:
        auth_events.registrar_seguro(
            request, auth_events.LOGIN_BLOQUEADO, username, detalle=DETALLE_PORTAL
        )
        raise HTTPException(
            429,
            "Demasiados intentos fallidos. Esperá "
            f"{auth_events.VENTANA_FALLIDOS_MINUTOS} minutos e intentá de nuevo.",
        )


def _exigir_captcha(request: Request, captcha: str) -> None:
    """Verifica el captcha ALTCHA con el MISMO `Captcha` de proceso que usa el
    login de staff — necesario para que la lista de desafíos ya usados
    (anti-replay) no se parta en dos, y para que `GET /auth/captcha` —que ya
    existe— sirva de desafío también para el portal, sin un
    `/api/portal/captcha` propio.

    🔑 **`_captcha_de` es un nombre privado de `libraauth.session_auth`** —no
    hay uno público todavía— y se resuelve por ATRIBUTO DE MÓDULO
    (`_session_auth._captcha_de(request)`) y no con
    `from libraauth.session_auth import _captcha_de`: la suite parchea
    justamente `libraauth.session_auth._captcha_de` (fixture
    `_captcha_aprobado` en `tests/conftest.py`) para que el resto de los tests
    no tenga que resolver un desafío real en cada login. Un `from` capturaría
    la función real en el momento del import, ANTES del parche, y esta ruta
    dejaría de aprobar el captcha con el resto de la suite. El arreglo de
    fondo sería que libraauth exporte una versión pública de esto.
    """
    if not _session_auth._captcha_de(request).verificar(captcha):
        raise HTTPException(400, _session_auth.CAPTCHA_INVALIDO)


#: 🔑 **`str` y no `EmailStr`, a propósito.** `EmailStr` arrastra la dependencia
#: `email-validator` a todo el producto para chequear una forma que igual no
#: prueba nada: un correo sintácticamente perfecto puede no existir. Lo único que
#: verifica un buzón es mandarle algo, y eso ya lo hace el recupero de
#: contraseña. Acá alcanza con descartar lo que evidentemente no es un mail.
def _parece_mail(valor: str) -> str:
    valor = valor.strip().lower()
    usuario, arroba, dominio = valor.partition("@")
    if not arroba or not usuario or "." not in dominio or dominio.endswith("."):
        raise ValueError("Ese correo no parece válido.")
    return valor


class RegistroEntrada(BaseModel):
    email: str = Field(min_length=5, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    nombre: str = Field(min_length=1, max_length=120)
    telefono: str = Field(default="", max_length=40)
    #: La solución del desafío ALTCHA (`GET /auth/captcha`). Default `""` y no
    #: obligatorio: un captcha vacío es sencillamente uno que no verifica, y
    #: el 400 que eso produce es el mismo que el de uno mal resuelto.
    captcha: str = ""

    @field_validator("email")
    @classmethod
    def _mail(cls, v: str) -> str:
        return _parece_mail(v)


class LoginEntrada(BaseModel):
    email: str = Field(max_length=120)
    password: str
    #: Ídem `RegistroEntrada.captcha`.
    captcha: str = ""


class JugadorSalida(BaseModel):
    id: int
    nombre: str
    email: str


class ReservaEntrada(BaseModel):
    cancha_id: int
    #: ISO 8601 **con offset**, igual que el resto del producto.
    comienza_at: datetime


def _salida(cuenta: CuentaDeJugador) -> JugadorSalida:
    return JugadorSalida(id=cuenta.id, nombre=cuenta.cliente.nombre, email=cuenta.email)


# ── Cuenta ───────────────────────────────────────────────────────────────


@router.post("/registro", response_model=JugadorSalida, status_code=201)
def registro(
    datos: RegistroEntrada,
    respuesta: Response,
    request: Request,
    sesion: Session = Depends(obtener_sesion),
):
    email = servicio._normalizar(datos.email)
    # Antes que el captcha: una IP bloqueada no registra cuentas tampoco.
    _cortar_si_bloqueado(request, email)
    _exigir_captcha(request, datos.captcha)
    try:
        cuenta = servicio.registrar(
            sesion, email=datos.email, password=datos.password,
            nombre=datos.nombre, telefono=datos.telefono,
        )
    except servicio.RegistroInvalido as e:
        raise HTTPException(422, str(e)) from e
    sesion.commit()
    sesion.refresh(cuenta)
    crear_cookie(respuesta, cuenta.id)
    auth_events.registrar_seguro(request, EVENTO_REGISTRO_PORTAL, email, detalle=DETALLE_PORTAL)
    return _salida(cuenta)


@router.post("/login", response_model=JugadorSalida)
def login(
    datos: LoginEntrada,
    respuesta: Response,
    request: Request,
    sesion: Session = Depends(obtener_sesion),
):
    email = servicio._normalizar(datos.email)
    # 🔴 El orden es bloqueo → captcha → credencial, igual que el login de
    # staff (ver docstrings de `_cortar_si_bloqueado` y `_exigir_captcha`).
    _cortar_si_bloqueado(request, email)
    _exigir_captcha(request, datos.captcha)
    try:
        cuenta = servicio.autenticar(sesion, email=datos.email, password=datos.password)
    except servicio.CredencialesInvalidas as e:
        # 🔑 Un solo mensaje para los dos casos. Distinguir "no existe" de
        # "contraseña equivocada" convierte el login en un verificador de quién
        # es cliente del complejo.
        auth_events.registrar_seguro(
            request, auth_events.LOGIN_FALLIDO, email, detalle=DETALLE_PORTAL
        )
        raise HTTPException(401, str(e)) from e
    crear_cookie(respuesta, cuenta.id)
    auth_events.registrar_seguro(request, auth_events.LOGIN, email, detalle=DETALLE_PORTAL)
    return _salida(cuenta)


@router.post("/logout", status_code=204)
def logout(respuesta: Response):
    borrar_cookie(respuesta)


@router.get("/yo", response_model=JugadorSalida | None)
def yo(request: Request, sesion: Session = Depends(obtener_sesion)):
    """Quién está logueado, o `null`. Lo llama la SPA al arrancar."""
    cuenta = cuenta_actual(request, sesion)
    return _salida(cuenta) if cuenta else None


# ── Qué hay para reservar ────────────────────────────────────────────────


@router.get("/canchas")
def canchas(sucursal_id: int, sesion: Session = Depends(obtener_sesion)):
    """Público **sin sesión**: hay que poder mirar antes de registrarse.

    Devuelve lo mínimo para elegir —nombre, deporte, si es techada— y no el
    modelo entero: `punto_venta_arca` y las notas internas no salen a internet.
    """
    return [
        {
            "id": c.id, "nombre": c.nombre, "deporte": c.deporte.value,
            "techada": c.techada, "iluminacion": c.iluminacion,
            "duracion_turno_min": c.duracion_turno_min,
        }
        for c in servicio.canchas_publicas(sesion, sucursal_id)
    ]


@router.get("/disponibilidad")
def disponibilidad(
    cancha_id: int,
    dia: date | None = Query(default=None),
    sesion: Session = Depends(obtener_sesion),
):
    """Los turnos libres de una cancha. También sin sesión.

    🔴 **No devuelve los ocupados.** La grilla del mostrador trae quién ocupa
    cada turno; publicarla diría en internet quién juega, a qué hora y con qué
    frecuencia.
    """
    cancha = sesion.get(Cancha, cancha_id)
    if cancha is None or not cancha.activa:
        raise HTTPException(404, "no existe esa cancha")
    libres = servicio.turnos_libres(sesion, cancha, dia or hoy())
    return [
        {
            "comienza_at": t["comienza_at"], "termina_at": t["termina_at"],
            "precio": float(t["precio"]),
        }
        for t in libres
    ]


# ── Reservar y pagar ─────────────────────────────────────────────────────


@router.post("/reservas", status_code=201)
def reservar(
    datos: ReservaEntrada,
    sesion: Session = Depends(obtener_sesion),
    cuenta: CuentaDeJugador = Depends(_jugador),
):
    """Retiene el turno y devuelve a dónde ir a pagar.

    🔑 **La respuesta dice `vence_at`.** El jugador tiene que ver cuánto tiempo
    tiene: un turno que desaparece sin aviso mientras completa la tarjeta es la
    peor versión de esto.
    """
    if servicio.con_pago_pendiente(sesion, cuenta) >= servicio.MAXIMO_SIN_PAGAR:
        raise HTTPException(
            429,
            f"Tenés {servicio.MAXIMO_SIN_PAGAR} reservas esperando pago. "
            "Completalas o esperá a que venzan.",
        )

    comienza = datos.comienza_at
    if comienza.tzinfo is None:
        comienza = comienza.replace(tzinfo=TZ)
    try:
        reserva, precio = servicio.reservar(
            sesion, cuenta=cuenta, cancha_id=datos.cancha_id, comienza_at=comienza
        )
    except servicio.TurnoNoDisponible as e:
        raise HTTPException(409, str(e)) from e

    pago = servicio_pagos.crear_pago(sesion, reserva, Decimal(str(precio)))
    sesion.commit()
    return {
        "reserva_id": reserva.id,
        "pago_id": pago.id,
        "referencia": pago.referencia,
        "monto": float(pago.monto),
        "vence_at": reserva.vence_at,
        # `null` mientras no haya credenciales de MercadoPago cargadas: la SPA
        # muestra "el complejo todavía no tiene los pagos configurados" en vez
        # de un botón que no lleva a ningún lado.
        "url_de_pago": None,
    }


@router.get("/reservas")
def mis_reservas(
    sesion: Session = Depends(obtener_sesion),
    cuenta: CuentaDeJugador = Depends(_jugador),
):
    return servicio.mis_reservas(sesion, cuenta)


@router.post("/reservas/{reserva_id}/cancelar")
def cancelar(
    reserva_id: int,
    sesion: Session = Depends(obtener_sesion),
    cuenta: CuentaDeJugador = Depends(_jugador),
):
    try:
        resultado = servicio.cancelar(
            sesion, cuenta, reserva_id, pasarela=devoluciones.pasarela_de_la_instancia()
        )
    except servicio.TurnoNoDisponible as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:  # transición inválida
        raise HTTPException(409, str(e)) from e
    sesion.commit()
    # 🔑 **El mensaje es lo que hace útil a esta respuesta.** Sin él, el que
    # canceló con dos días de anticipación y el que canceló media hora antes ven
    # exactamente lo mismo, y el segundo llama por teléfono a preguntar por su
    # seña.
    #
    # 🔴 Va `para_el_jugador` y **no** `detalle`: el detalle nombra la
    # configuración del complejo —«no tiene MercadoPago configurado»— y esto está
    # expuesto a internet sin sesión. Es la misma regla que el resto del módulo.
    return {
        "id": resultado.reserva.id,
        "estado": resultado.reserva.estado.value,
        "detalle": resultado.para_el_jugador,
        "devolucion": resultado.devolucion.value if resultado.devolucion else None,
    }


# ── «Falta uno»: completar el equipo de un partido ya reservado ──────────


class PublicarEntrada(BaseModel):
    faltan: int = Field(ge=1, le=20)
    nota: str = Field(default="", max_length=200)


@router.post("/reservas/{reserva_id}/buscar-jugadores", status_code=201)
def publicar_partido(
    reserva_id: int,
    datos: PublicarEntrada,
    sesion: Session = Depends(obtener_sesion),
    cuenta: CuentaDeJugador = Depends(_jugador),
):
    """«Faltan 2 para el partido del jueves». Sobre una reserva propia y pagada."""
    try:
        busqueda = servicio_partidos.publicar(
            sesion, cuenta=cuenta, reserva_id=reserva_id,
            faltan=datos.faltan, nota=datos.nota,
        )
    except servicio_partidos.NoSePuedePublicar as e:
        raise HTTPException(422, str(e)) from e
    sesion.commit()
    return servicio_partidos.detalle(sesion, cuenta, busqueda.id)


@router.get("/partidos")
def partidos_abiertos(
    sesion: Session = Depends(obtener_sesion),
    _: CuentaDeJugador = Depends(_jugador),
):
    """Los partidos que buscan jugadores.

    🔴 **Pide sesión, y no trae contacto de nadie.** Lo primero porque publicar
    en internet abierto a qué hora juega cada uno y en qué cancha es más de lo
    que hace falta; lo segundo porque con teléfonos, alcanzaría con registrarse
    para levantar la agenda de todos los que juegan en el complejo.
    """
    return servicio_partidos.listar(sesion)


@router.get("/partidos/mios")
def mis_partidos(
    sesion: Session = Depends(obtener_sesion),
    cuenta: CuentaDeJugador = Depends(_jugador),
):
    """Los partidos donde el jugador está anotado. **Con** contacto: juega ahí.

    ⚠️ Va antes de `/partidos/{id}` a propósito: declarada después, la ruta con
    parámetro se la come y `mios` llegaría como id, dando un 422 confuso.
    """
    return servicio_partidos.mis_partidos(sesion, cuenta)


@router.get("/partidos/{busqueda_id}")
def ver_partido(
    busqueda_id: int,
    sesion: Session = Depends(obtener_sesion),
    cuenta: CuentaDeJugador = Depends(_jugador),
):
    """Un partido. El contacto sale **sólo si quien pregunta juega ahí**."""
    try:
        return servicio_partidos.detalle(sesion, cuenta, busqueda_id)
    except servicio_partidos.PartidoCerrado as e:
        raise HTTPException(404, str(e)) from e


@router.post("/partidos/{busqueda_id}/sumarme", status_code=201)
def sumarme(
    busqueda_id: int,
    sesion: Session = Depends(obtener_sesion),
    cuenta: CuentaDeJugador = Depends(_jugador),
):
    try:
        servicio_partidos.sumarse(sesion, cuenta, busqueda_id)
    except servicio_partidos.PartidoCerrado as e:
        raise HTTPException(409, str(e)) from e
    sesion.commit()
    return servicio_partidos.detalle(sesion, cuenta, busqueda_id)


@router.post("/partidos/{busqueda_id}/bajarme")
def bajarme(
    busqueda_id: int,
    sesion: Session = Depends(obtener_sesion),
    cuenta: CuentaDeJugador = Depends(_jugador),
):
    try:
        servicio_partidos.bajarse(sesion, cuenta, busqueda_id)
    except servicio_partidos.PartidoCerrado as e:
        raise HTTPException(404, str(e)) from e
    sesion.commit()
    return servicio_partidos.detalle(sesion, cuenta, busqueda_id)


@router.post("/partidos/{busqueda_id}/cerrar")
def cerrar_partido(
    busqueda_id: int,
    sesion: Session = Depends(obtener_sesion),
    cuenta: CuentaDeJugador = Depends(_jugador),
):
    """El organizador deja de buscar."""
    try:
        servicio_partidos.cerrar(sesion, cuenta, busqueda_id)
    except servicio_partidos.NoEsTuPartido as e:
        raise HTTPException(403, str(e)) from e
    except servicio_partidos.PartidoCerrado as e:
        raise HTTPException(404, str(e)) from e
    sesion.commit()
    return servicio_partidos.detalle(sesion, cuenta, busqueda_id)


# ── El webhook de MercadoPago, que es lo que confirma ────────────────────


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, sesion: Session = Depends(obtener_sesion)):
    """La notificación de MercadoPago. **Es lo único que confirma una reserva.**

    🔴 **Contesta 200 casi siempre, y no es descuido.** MercadoPago reintenta
    ante cualquier respuesta que no sea 2xx, con backoff, durante días. Un 500
    por una notificación que no nos sirve —de otro tipo, de un pago que no es
    nuestro— convierte un caso normal en una tormenta de reintentos. Se contesta
    200 y se registra qué se hizo.

    Los 401 sí se devuelven: una firma inválida no es un caso normal.

    🔴 **Sigue siendo `async` sólo por el `await request.body()`**: la firma
    se verifica sobre el cuerpo crudo. Todo lo demás —`config.json`, la base
    y las dos corrutinas del motor— va a `_procesar_webhook`, en el
    threadpool: uvicorn corre con **un solo proceso**, y hecho acá cada
    consulta frenaba la instancia entera.
    """
    cuerpo = await request.body()
    return await run_in_threadpool(
        _procesar_webhook, cuerpo, sesion,
        x_signature=request.headers.get("x-signature", ""),
        x_request_id=request.headers.get("x-request-id", ""),
    )


def _procesar_webhook(
    cuerpo: bytes, sesion: Session, *, x_signature: str, x_request_id: str
) -> dict:
    """Lo que hace el webhook con el cuerpo ya leído. Corre en el threadpool.

    Las dos llamadas a MercadoPago van con `asyncio.run`, en un loop propio de
    este hilo: `mp_sync.ingerir` escribe la bandeja entre medio de lo que le
    pide a la red, y con `await` desde el loop de uvicorn eso lo frenaba.
    """
    try:
        payload = json.loads(cuerpo)
    except ValueError:
        return {"ok": False, "motivo": "json invalido"}

    if payload.get("type") != "payment":
        # `merchant_order` y demás. No es un error.
        return {"ok": True, "motivo": "no es un pago"}

    payment_id = str((payload.get("data") or {}).get("id") or "")
    if not payment_id:
        return {"ok": False, "motivo": "sin id de pago"}

    # De `config_manager` de LibraCore, que es donde la pantalla de
    # Configuración ya guarda las credenciales de MercadoPago. No hay una
    # segunda copia de esto en el producto.
    config = config_manager.load()
    secreto = config.get("mp_webhook_secret", "")
    if not secreto:
        # Sin secreto no se puede verificar nada, y procesar sin verificar es
        # peor que no procesar: cualquiera confirmaría reservas.
        return {"ok": False, "motivo": "webhook sin secreto configurado"}

    if not servicio_pagos.firma_valida(
        x_signature=x_signature,
        x_request_id=x_request_id,
        payment_id=payment_id,
        secreto=secreto,
    ):
        raise HTTPException(401, "firma invalida")

    token = config.get("mp_access_token", "")
    if not token:
        return {"ok": False, "motivo": "sin access token"}

    # 🔴 **El estado se le pregunta a MercadoPago; el cuerpo de la notificación
    # no se cree.** El webhook avisa "pasó algo con el pago 123"; qué pasó se
    # consulta. Confiar en el payload haría que una notificación forjada —si
    # alguna vez se filtrara el secreto— pudiera decir "aprobado" sola.
    detalle = asyncio.run(mp_api.obtener_pago(payment_id, token))
    referencia = str(detalle.get("external_reference") or "")
    estado_mp = str(detalle.get("status") or "")

    pago = servicio_pagos.por_referencia(sesion, referencia)
    if pago is None:
        # 🔑 **Un cobro que no salió de un turno.** Hasta el 2026-08-27 esto
        # contestaba 200 y no dejaba rastro: una transferencia al complejo o un
        # pago suelto **se perdían**. Ahora entran a la bandeja de conciliación.
        #
        # El depósito no se replica a mano: se llama a la MISMA función pública
        # que usan el botón *Sincronizar* y el cron nocturno. Rearmar acá los
        # datos del pagador —que el motor ya resuelve— es cómo dos copias
        # empiezan a divergir. `ingerir` es idempotente: si el pago ya estaba, no
        # lo duplica.
        if not referencia.startswith(servicio_pagos.PREFIJO_DE_REFERENCIA):
            try:
                nuevos = asyncio.run(mp_sync.ingerir(
                    config, dias=1, referencias_a_omitir=REFERENCIAS_PROPIAS,
                ))
            except Exception:
                # 🔴 200 igual, y a propósito: el cobro **ya está hecho** del
                # lado de MercadoPago. Un error haría que MP reintente durante
                # días por algo que el cron nocturno va a traer solo.
                logger.exception(
                    "No se pudo llevar a la bandeja el pago %s (referencia %r)",
                    payment_id, referencia,
                )
                return {"ok": True, "motivo": "no se pudo conciliar, queda para el cron"}
            return {"ok": True, "motivo": f"a la bandeja ({len(nuevos)} nuevos)"}

        # Con nuestro prefijo pero sin pago registrado: otra instancia del
        # producto sobre la misma cuenta, o una prueba. No es nuestro, y a la
        # bandeja tampoco va — ahí lo resolvió alguien más.
        return {"ok": True, "motivo": "referencia desconocida"}

    # 🔑 La MISMA traducción que usa el poll del QR (`servicios/cobro_qr.py`).
    # Estaba escrita dos veces con los mismos literales, y dos copias del mismo
    # `if` es de donde salen las divergencias.
    traducido = acreditacion.estado_desde_mercadopago(estado_mp)

    if traducido is acreditacion.EstadoAcreditacion.APROBADO:
        cambio = servicio_pagos.aplicar_pago_aprobado(
            sesion, pago, payment_id=payment_id, estado_mp=estado_mp
        )
        sesion.commit()
        return {"ok": True, "confirmada": cambio}

    if traducido is acreditacion.EstadoAcreditacion.RECHAZADO:
        servicio_pagos.aplicar_pago_rechazado(
            sesion, pago, payment_id=payment_id, estado_mp=estado_mp
        )
        sesion.commit()
        return {"ok": True, "rechazado": True}

    # `pending`, `in_process`, `authorized`: todavía no hay nada que hacer, y la
    # reserva sigue provisoria con su vencimiento corriendo.
    pago.estado_mp = estado_mp
    sesion.commit()
    return {"ok": True, "estado": estado_mp}


# ── El simulador de pago, sólo fuera de producción ───────────────────────


def construir_router_de_simulacion(entorno: str) -> APIRouter | None:
    """`POST /api/portal/pagos/{id}/simular`, **si esta instancia no es producción**.

    🔴 **Es lo único que separa dev de regalar turnos.** Este endpoint confirma
    una reserva sin que nadie haya pagado: montado en la instancia de un
    complejo, cualquiera con la URL se lleva los viernes a la noche gratis. Por
    eso devuelve `None` en producción y el router **no se monta** — no alcanza
    con un `if` adentro del handler, porque un `if` mal escrito deja el endpoint
    existiendo.

    🔑 **Llama a `aplicar_pago_aprobado`, la MISMA función que el webhook.** Un
    simulador con lógica propia probaría un circuito que en producción no
    existe: el día que MercadoPago confirme de verdad, se ejecutaría un camino
    que nunca corrió. Lo único que se saltea es la parte que no se puede tener
    sin credenciales —la firma y la consulta a MercadoPago—, y eso queda
    explícito acá y no escondido.
    """
    if es_produccion(entorno):
        return None

    simulador = APIRouter(prefix="/api/portal", tags=["portal público"])

    @simulador.post("/pagos/{pago_id}/simular")
    def simular(
        pago_id: int,
        aprobado: bool = Query(default=True),
        sesion: Session = Depends(obtener_sesion),
    ):
        """Hace de cuenta que MercadoPago avisó. Sólo en dev y demo."""
        pago = sesion.get(PagoDeReserva, pago_id)
        if pago is None:
            raise HTTPException(404, "no existe ese pago")

        falso_id = f"simulado-{pago.id}"
        if aprobado:
            cambio = servicio_pagos.aplicar_pago_aprobado(
                sesion, pago, payment_id=falso_id, estado_mp="approved"
            )
        else:
            servicio_pagos.aplicar_pago_rechazado(
                sesion, pago, payment_id=falso_id, estado_mp="rejected"
            )
            cambio = True
        sesion.commit()
        reserva = sesion.get(Reserva, pago.reserva_id)
        return {
            "pago": pago.estado.value,
            "reserva": reserva.estado.value,
            "cambio": cambio,
            "simulado": True,
        }

    return simulador
