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

import json
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from libracore import config_manager, mp_api
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.models.maestros import Cancha, CuentaDeJugador
from app.models.reservas import PagoDeReserva, Reserva
from app.portal_sesion import borrar_cookie, crear_cookie, cuenta_actual, exigir_jugador
from app.servicios import pagos as servicio_pagos
from app.servicios import portal as servicio
from app.tiempo import TZ, hoy

router = APIRouter(prefix="/api/portal", tags=["portal público"])


def _jugador(request: Request, sesion: Session = Depends(obtener_sesion)) -> CuentaDeJugador:
    return exigir_jugador(request, sesion)


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

    @field_validator("email")
    @classmethod
    def _mail(cls, v: str) -> str:
        return _parece_mail(v)


class LoginEntrada(BaseModel):
    email: str = Field(max_length=120)
    password: str


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
    sesion: Session = Depends(obtener_sesion),
):
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
    return _salida(cuenta)


@router.post("/login", response_model=JugadorSalida)
def login(
    datos: LoginEntrada,
    respuesta: Response,
    sesion: Session = Depends(obtener_sesion),
):
    try:
        cuenta = servicio.autenticar(sesion, email=datos.email, password=datos.password)
    except servicio.CredencialesInvalidas as e:
        # 🔑 Un solo mensaje para los dos casos. Distinguir "no existe" de
        # "contraseña equivocada" convierte el login en un verificador de quién
        # es cliente del complejo.
        raise HTTPException(401, str(e)) from e
    crear_cookie(respuesta, cuenta.id)
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
        reserva = servicio.cancelar(sesion, cuenta, reserva_id)
    except servicio.TurnoNoDisponible as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:  # transición inválida
        raise HTTPException(409, str(e)) from e
    sesion.commit()
    return {"id": reserva.id, "estado": reserva.estado.value}


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
    """
    cuerpo = await request.body()
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
        cuerpo=cuerpo,
        x_signature=request.headers.get("x-signature", ""),
        x_request_id=request.headers.get("x-request-id", ""),
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
    detalle = await mp_api.obtener_pago(payment_id, token)
    referencia = str(detalle.get("external_reference") or "")
    estado_mp = str(detalle.get("status") or "")

    pago = servicio_pagos.por_referencia(sesion, referencia)
    if pago is None:
        # Un pago de otra instancia, o una prueba. No es nuestro.
        return {"ok": True, "motivo": "referencia desconocida"}

    if estado_mp == "approved":
        cambio = servicio_pagos.aplicar_pago_aprobado(
            sesion, pago, payment_id=payment_id, estado_mp=estado_mp
        )
        sesion.commit()
        return {"ok": True, "confirmada": cambio}

    if estado_mp in ("rejected", "cancelled"):
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
    if entorno.lower() in ("prod", "produccion", "producción", "production"):
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
