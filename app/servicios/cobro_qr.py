"""Cobro con QR de MercadoPago en el mostrador, y la factura que sale sola.

Es la misma función que Contalibra tiene en producción desde el 2026-08-19,
traída al mostrador de un complejo. El cliente REST no se reimplementa: sale de
`libracore.mp_api`, que ya lo comparten los productos de la familia.

## Qué se cobra: el turno entero, cancha más buffet

🔑 **Un solo cobro y un solo comprobante**, igual que `facturar_reserva`. El
grupo juega y toma tres gaseosas; el QR cobra las dos cosas juntas y sale una
factura con el alquiler y el consumo detallados. Cobrarlos por separado
obligaría a dos escaneos por un mismo grupo y a que el buffet queme numeración
fiscal por cada gaseosa.

## El QR es el cartel impreso de la caja, no una imagen

Nada de esto devuelve un QR para mostrar en pantalla. Es el modelo de **QR fijo
por punto de venta**: el cartel del mostrador no cambia nunca; lo que esta
llamada cambia es *cuánto cobra* cuando alguien lo escanea.

## Los dos caminos por los que se entera de que se pagó

1. **El webhook** (`POST /api/portal/webhook`), que es el mismo del portal: el
   pago del mostrador viaja por la misma tabla y con el mismo
   `external_reference`, así que lo encuentra por referencia sin cambios.
2. **El poll** (`GET /api/reservas/{id}/mp-status`), que es el que corre con el
   cajero mirando.

🔴 **Sólo el poll registra el cobro en la caja, y no es una omisión.** El
movimiento de caja va contra el **turno abierto de quien cobra**, y el webhook
no sabe quién es: llega de MercadoPago, sin sesión. Un ingreso sin `turno_id`
queda fuera de todo arqueo — plata que entró y que ningún cierre cuenta. Así
que el webhook sella el pago y el poll —el tick siguiente, con el cajero ahí—
completa la caja y la factura. Si el webhook llegó primero, el poll lo ve
aprobado y hace su parte igual.

## Dos bases, sin transacción única

La factura y el movimiento de caja viven en la base de LibraCore; el pago y la
reserva, en la del dominio. No hay una transacción que las abarque, así que cada
parte es idempotente por separado — el mismo criterio que VentaLibra documenta
en su ADR-022. La marca del cobro es `PagoDeReserva.caja_movimiento_id` y no la
idempotencia de `create_caja_movimiento`: ver la nota en el modelo.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from libracore import config_manager, mp_api
from sqlalchemy.orm import Session

from app.models.reservas import EstadoPago, PagoDeReserva, Reserva
from app.servicios import buffet, caja, facturacion
from app.servicios import pagos as servicio_pagos
from app.tiempo import a_local

logger = logging.getLogger(__name__)


class QrNoConfigurado(RuntimeError):
    """Faltan las credenciales del QR en Configuración → Mercado Pago."""


class QrError(RuntimeError):
    """MercadoPago rechazó la orden, o no se la pudo consultar."""


class NadaQueCobrar(RuntimeError):
    """No queda saldo: poner cero en el QR es cobrarle de nuevo a quien ya pagó."""


class SinPrecio(RuntimeError):
    """El turno no tiene precio cargado: no hay nada que cobrar."""


#: El toggle de la factura automática. No está en los DEFAULTS de
#: `libracore.config_manager` —son los genéricos de la familia— así que viaja
#: como `extra_defaults`, que es el mecanismo que el motor expone para esto.
EXTRA_DEFAULTS = {"mp_auto_facturar_reservas": False}

#: El medio con el que entra a la caja. Es la clave de `MEDIOS_PAGO` de
#: `servicios/caja.py`, que a su vez es un subconjunto de las de LibraCore.
MEDIO = "mercadopago"


def cargar_config() -> dict:
    return config_manager.load(EXTRA_DEFAULTS)


def guardar_config(cfg: dict) -> None:
    config_manager.save(cfg, EXTRA_DEFAULTS)


def credenciales(cfg: dict | None = None) -> tuple[str, str, str]:
    """Access token, user id y pos id. Levanta si falta alguno.

    🔑 Los tres, no sólo el token: `crear_orden_qr` mete el `user_id` (el
    collector id de la cuenta) y el `pos_id` (el **external_id** de la caja, no
    su nombre ni su id numérico) en la URL. Con uno vacío la URL se arma igual y
    MercadoPago contesta 404 — un error que no dice qué falta.
    """
    cfg = cfg if cfg is not None else cargar_config()
    token = (cfg.get("mp_access_token") or "").strip()
    user_id = (cfg.get("mp_user_id") or "").strip()
    pos_id = (cfg.get("mp_pos_id") or "").strip()
    if not token or not user_id or not pos_id:
        raise QrNoConfigurado(
            "Falta configurar el Access Token, el User ID y el POS ID de "
            "MercadoPago en Configuración → Mercado Pago."
        )
    return token, user_id, pos_id


def esta_configurado() -> bool:
    """Si este mostrador puede cobrar por QR. Lo lee la pantalla para no ofrecer
    un botón que sólo puede fallar."""
    try:
        credenciales()
    except QrNoConfigurado:
        return False
    return True


def auto_facturar_prendida(cfg: dict | None = None) -> bool:
    cfg = cfg if cfg is not None else cargar_config()
    return bool(cfg.get("mp_auto_facturar_reservas"))


# ── Qué se cobra ─────────────────────────────────────────────────────────


def total_a_cobrar(reserva: Reserva) -> Decimal:
    """Lo que falta cobrar del turno: cancha más buffet, menos lo que ya entró.

    🔴 **La cancha más el buffet, y no `reserva.precio` a secas.** Si el QR
    cobrara sólo el alquiler, la factura saldría por más de lo que entró y el
    arqueo no cerraría — y el que lo descubre es el cierre de turno, horas
    después. Es el mismo total que factura `facturar_reserva`.

    🔴 **Y menos lo ya cobrado, desde el 2026-08-28.** Antes esta función
    devolvía el total pelado, así que un turno con **seña en efectivo** cobrado
    después por QR le cobraba al cliente el total **otra vez**: $14.000 de turno
    con $5.000 de seña terminaban en $19.000 en la caja. No era hipotético —
    tomar seña y cobrar el saldo es el flujo normal de un complejo, y la
    pantalla del detalle ofrecía el botón igual.

    Restar acá y no en el llamador es a propósito: son **tres** los caminos que
    ponen plata en el QR —el detalle del turno, la Caja y el portal— y el que
    sabe cuánto falta es este módulo.

    La factura, en cambio, sigue siendo del **turno entero**: seña y saldo son
    dos movimientos de caja contra el mismo comprobante, que es el modelo que
    `facturar_reserva` declara desde el día uno.
    """
    if reserva.precio is None or Decimal(str(reserva.precio)) <= 0:
        raise SinPrecio("El turno no tiene precio cargado.")
    total = Decimal(str(reserva.precio)) + buffet.total_consumido(reserva.id)
    pendiente = total - caja.total_cobrado(reserva.id)
    if pendiente <= 0:
        # 🔑 Sale como error de dominio y no como el `CheckConstraint monto > 0`
        # de la tabla: ese fallaría con un 500 que no le dice nada al operador.
        raise NadaQueCobrar(
            f"El turno ya está cobrado (total {total}, cobrado {total - pendiente})."
        )
    return pendiente


def items_para_mp(reserva: Reserva, cancha_nombre: str) -> list[dict]:
    """Las líneas que ve el cliente en la app de MercadoPago al escanear.

    Van con el precio **final**, no con el neto: el desglose de IVA es de la
    factura, no del cobro. Es la misma lista que arma
    `facturacion.lineas_de_la_reserva`, pero sin pasar por el neto — y por eso
    no se reusa: ahí el precio ya viene desagregado.
    """
    duracion = int((reserva.termina_at - reserva.comienza_at).total_seconds() // 60)
    precio = Decimal(str(reserva.precio))
    items = [{
        "producto_id": reserva.cancha_id,
        "nombre": (
            f"Alquiler de {cancha_nombre} — "
            f"{a_local(reserva.comienza_at):%d-%m-%Y %H:%M} ({duracion} min)"
        ),
        "qty": 1.0,
        "precio": float(precio),
        "subtotal": float(precio),
    }]
    for consumo in buffet.lineas_para_factura(reserva.id):
        cantidad = Decimal(consumo.quantity)
        unitario = Decimal(consumo.unit_price)
        items.append({
            "producto_id": consumo.item_id,
            "nombre": consumo.description_snapshot,
            "qty": float(cantidad),
            "precio": float(unitario),
            "subtotal": float(cantidad * unitario),
        })
    return items


# ── La orden en la caja ──────────────────────────────────────────────────


async def poner_en_el_qr(
    sesion: Session, reserva: Reserva, cancha_nombre: str
) -> PagoDeReserva:
    """Pone el total del turno a cobrar en el QR del mostrador.

    Deja el intento registrado como `PagoDeReserva` **del canal mostrador**: es
    lo que después encuentran el webhook (por referencia) y el poll.
    """
    total = total_a_cobrar(reserva)
    token, user_id, pos_id = credenciales()

    # El pago se crea ANTES de llamar a MercadoPago para que la referencia
    # exista: es lo que viaja en la orden. Si MercadoPago falla, el caller no
    # commitea y la fila no queda.
    pago = servicio_pagos.crear_pago_de_mostrador(sesion, reserva, total)

    try:
        await mp_api.crear_orden_qr(
            user_id=user_id,
            pos_id=pos_id,
            access_token=token,
            external_reference=pago.referencia,
            titulo=f"Turno {a_local(reserva.comienza_at):%d-%m-%Y %H:%M}",
            items=items_para_mp(reserva, cancha_nombre),
            total=float(total),
        )
    except RuntimeError as exc:
        # `crear_orden_qr` levanta con el status y el cuerpo de MercadoPago
        # adentro. Se propaga tal cual: el 404 de un POS ID que no existe es lo
        # único que le dice al operador que se equivocó de dato.
        raise QrError(str(exc)) from exc

    logger.info("Reserva %s puesta en el QR por %s (ref %s)",
                reserva.id, total, pago.referencia)
    return pago


async def bajar_del_qr(sesion: Session, reserva_id: int) -> bool:
    """Saca la orden del QR: el cartel queda sin nada que cobrar.

    🔴 **Es lo que evita que el próximo cliente pague el turno anterior.** Una
    orden que queda puesta sigue cobrando ese monto a quien escanee, aunque el
    encargado haya cancelado el cobro hace media hora. Contalibra no llama nunca
    a `eliminar_orden_qr` —no tiene un solo call site en todo el repo— y por eso
    depende de que nadie escanee entre un cobro y el siguiente.

    Devuelve si había algo que bajar. No levanta si falta configuración: se
    llama al cancelar, y hacer fallar una cancelación por eso sería peor.
    """
    pago = servicio_pagos.ultimo_de_mostrador(sesion, reserva_id)
    if pago is None or pago.estado is not EstadoPago.PENDIENTE:
        return False
    try:
        token, user_id, pos_id = credenciales()
    except QrNoConfigurado:
        return False
    await mp_api.eliminar_orden_qr(user_id, pos_id, token)
    pago.estado = EstadoPago.VENCIDO
    return True


# ── El poll, que es donde se completa el cobro ───────────────────────────


async def estado_del_cobro(
    sesion: Session, reserva: Reserva, cliente, cancha_nombre: str, usuario: dict
) -> dict:
    """Si el QR de este turno ya se pagó, y si sí, termina de cobrarlo.

    Es un GET con efectos, igual que el de Contalibra: acá es donde entran el
    movimiento de caja y la factura. Sellar dos veces no hace nada — el pago ya
    figura aprobado y `caja_movimiento_id` corta el segundo ingreso.

    El caller commitea.
    """
    pago = servicio_pagos.ultimo_de_mostrador(sesion, reserva.id)
    if pago is None:
        return {"estado": "sin_orden", "payment_id": None, "factura_id": None}

    if pago.estado is EstadoPago.APROBADO:
        # Puede haberlo sellado el webhook. Se completa igual: es idempotente y
        # es el único camino que sabe quién cobra.
        return await _completar(sesion, pago, reserva, cliente, cancha_nombre, usuario)

    if pago.estado is not EstadoPago.PENDIENTE:
        return {"estado": pago.estado.value, "payment_id": pago.payment_id,
                "factura_id": reserva.factura_id}

    token, _user_id, _pos_id = credenciales()
    try:
        detalle = await mp_api.buscar_pago_por_referencia(pago.referencia, token)
    except Exception as exc:
        raise QrError(f"No se pudo consultar el pago en MercadoPago: {exc}") from exc

    if not detalle:
        return {"estado": "pendiente", "payment_id": None, "factura_id": None}

    estado_mp = str(detalle.get("status") or "pendiente")
    payment_id = str(detalle["id"])

    if estado_mp in ("rejected", "cancelled"):
        servicio_pagos.aplicar_pago_rechazado(
            sesion, pago, payment_id=payment_id, estado_mp=estado_mp
        )
        return {"estado": "rechazado", "payment_id": payment_id, "factura_id": None}

    if estado_mp != "approved":
        pago.estado_mp = estado_mp
        return {"estado": "pendiente", "payment_id": None, "factura_id": None}

    servicio_pagos.aplicar_pago_aprobado(
        sesion, pago, payment_id=payment_id, estado_mp=estado_mp
    )
    return await _completar(sesion, pago, reserva, cliente, cancha_nombre, usuario)


async def _completar(
    sesion: Session, pago: PagoDeReserva, reserva: Reserva, cliente,
    cancha_nombre: str, usuario: dict,
) -> dict:
    """La factura y el movimiento de caja de un pago ya aprobado. Idempotente.

    El orden importa: **primero la factura, después la caja**, para que el
    movimiento quede atado al comprobante. Si ARCA falla, el cobro se registra
    igual con `factura_id` en `None` —la plata entró y perderla del arqueo sería
    peor que quedarse sin la factura, que se puede emitir con el botón de
    siempre— y el movimiento queda sin atar. Es una consecuencia asumida: volver
    a registrarlo con el `factura_id` del reintento contaría el ingreso dos
    veces.
    """
    if pago.caja_movimiento_id is not None:
        return {"estado": "aprobado", "payment_id": pago.payment_id,
                "factura_id": reserva.factura_id}

    await _facturar_si_corresponde(reserva, cliente, cancha_nombre)

    movimiento_id = caja.registrar_ingreso(
        usuario,
        pago.monto,
        f"Turno {a_local(reserva.comienza_at):%d-%m-%Y %H:%M} — {cancha_nombre}",
        MEDIO,
        referencia=pago.referencia,
        factura_id=reserva.factura_id,
    )
    pago.caja_movimiento_id = movimiento_id
    logger.info("Reserva %s cobrada por QR: payment_id=%s, movimiento=%s, factura=%s",
                reserva.id, pago.payment_id, movimiento_id, reserva.factura_id)
    return {"estado": "aprobado", "payment_id": pago.payment_id,
            "factura_id": reserva.factura_id}


async def _facturar_si_corresponde(reserva: Reserva, cliente, cancha_nombre: str) -> None:
    """Emite la factura del turno si la instancia tiene la automática prendida.

    🔴 **No propaga el error.** El cobro ya está acreditado: perderlo del arqueo
    sería peor que quedarse sin la factura, que se puede emitir después con el
    botón del detalle. Falla ruidosa en el log y sigue.

    Tampoco reemite: si la reserva ya tiene comprobante —lo pidieron a mano
    antes de cobrar— el cobro se ata a ése.
    """
    if not auto_facturar_prendida() or reserva.factura_id is not None:
        return
    try:
        factura = await facturacion.facturar_reserva(reserva, cliente, cancha_nombre)
    except Exception as exc:
        logger.error("Error auto-facturando la reserva %s: %s", reserva.id, exc)
        return
    logger.info("Auto-factura de la reserva %s: id=%s CAE=%s",
                reserva.id, factura["id"], factura.get("cae") or "sin CAE")
