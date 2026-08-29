"""El pago que hace efectiva una reserva del portal. **Sin pago no hay reserva.**

Ésa es la regla del producto y define todo lo de acá abajo: el jugador elige un
turno, se le retiene **provisorio** con vencimiento, y sólo se confirma cuando
MercadoPago avisa que el pago está aprobado. Si no paga, el turno se libera solo.

## Por qué el estado lo decide el webhook y no el navegador

🔴 **La vuelta del jugador desde MercadoPago NO confirma nada.** MercadoPago
redirige al navegador a una URL de éxito, y esa URL la puede abrir cualquiera
—escribirla a mano, compartirla, volver atrás— sin haber pagado un peso.
Confirmar ahí es regalar turnos.

Lo que confirma es el **webhook**, y con dos recaudos que tampoco son opcionales:

1. **La firma se verifica** (HMAC del `x-signature`), o cualquiera puede hacer un
   POST diciendo que un pago se aprobó.
2. **El pago se consulta a MercadoPago**, no se cree lo que dice el cuerpo de la
   notificación. El webhook avisa *"pasó algo con el pago 123"*; el estado real
   se pregunta.

Es el mismo patrón que Contalibra tiene desde hace meses en
`app/web/routers/webhooks.py`, y de ahí sale la verificación de firma.

## El simulador de dev

Sin credenciales de MercadoPago no se puede probar nada de esto, así que hay un
`simular_pago()` que ejecuta **exactamente la misma función** que el webhook
—`aplicar_pago_aprobado`— en vez de tener su propio camino. Un simulador con
lógica propia probaría un circuito que en producción no existe.

🔴 **Está gateado por entorno y eso es lo único que separa dev de regalar
turnos.** En una instancia de producción el endpoint no se monta.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from decimal import Decimal

from libracore.mp_webhook import verificar_firma
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import EstadoReserva
from app.models.reservas import CanalDePago, EstadoPago, PagoDeReserva, Reserva
from app.tiempo import ahora


class PagoNoConfigurado(RuntimeError):
    """La instancia no tiene credenciales de MercadoPago cargadas."""


class PagoInvalido(ValueError):
    pass


#: Con qué arranca toda referencia de MercadoPago de este producto.
#:
#: 🔑 Está acá y no repetido en cada lugar que lo necesita porque la bandeja del
#: motor filtra por él: dos copias que divergen dejarían un filtro que no
#: matchea, y los pagos de reservas —ya resueltos por el webhook— empezarían a
#: aparecer en la bandeja como si nadie los hubiera conciliado.
PREFIJO_DE_REFERENCIA = "lc-"


def nueva_referencia(reserva_id: int) -> str:
    """La referencia externa que viaja a MercadoPago y vuelve en el webhook.

    Lleva el id de la reserva **y** un sufijo aleatorio: el id solo no alcanza
    porque un pago rechazado se reintenta, y la referencia tiene que ser distinta
    para que el `UNIQUE` no bloquee el segundo intento.
    """
    return f"{PREFIJO_DE_REFERENCIA}{reserva_id}-{secrets.token_hex(6)}"


def crear_pago(sesion: Session, reserva: Reserva, monto: Decimal) -> PagoDeReserva:
    """Registra el intento de pago de una reserva provisoria."""
    if reserva.estado is not EstadoReserva.PROVISORIA:
        raise PagoInvalido(
            f"Sólo se paga una reserva provisoria (ésta está {reserva.estado.value})."
        )
    pago = PagoDeReserva(
        reserva_id=reserva.id,
        monto=monto,
        estado=EstadoPago.PENDIENTE,
        referencia=nueva_referencia(reserva.id),
        canal=CanalDePago.PORTAL,
    )
    sesion.add(pago)
    sesion.flush()
    return pago


#: Los estados en los que tiene sentido cobrar un turno en el mostrador.
#:
#: `JUGADA` entra a propósito: en un complejo el grupo suele pagar **al
#: terminar**, y para entonces el turno ya se marcó jugado. Dejarla afuera haría
#: que el cobro más habitual sea el que el sistema rechaza.
ESTADOS_COBRABLES = (EstadoReserva.CONFIRMADA, EstadoReserva.JUGADA)


def crear_pago_de_mostrador(
    sesion: Session, reserva: Reserva, monto: Decimal
) -> PagoDeReserva:
    """El intento de cobro con QR de un turno ya tomado.

    Es la contracara de `crear_pago`: allá el pago **crea** la reserva —sin pago
    no hay reserva— y acá la reserva ya existe y lo que falta es la plata. Por
    eso los estados válidos son los opuestos.

    🔑 **Un turno con un pago aprobado no se vuelve a cobrar.** El índice parcial
    `uq_pagos_reserva_aprobado` lo impide en la base, pero fallar ahí sería un
    500; acá sale como un error del dominio que el router traduce a 409. Cubre
    los dos casos que importan: el que ya pagó por el portal y el que ya pagó
    por el QR hace un minuto.
    """
    if reserva.estado not in ESTADOS_COBRABLES:
        raise PagoInvalido(
            f"Sólo se cobra un turno confirmado o jugado (éste está "
            f"{reserva.estado.value})."
        )
    if aprobado_de(sesion, reserva.id) is not None:
        raise PagoInvalido(f"La reserva {reserva.id} ya tiene un pago aprobado.")
    pago = PagoDeReserva(
        reserva_id=reserva.id,
        monto=monto,
        estado=EstadoPago.PENDIENTE,
        referencia=nueva_referencia(reserva.id),
        canal=CanalDePago.MOSTRADOR,
    )
    sesion.add(pago)
    sesion.flush()
    return pago


def por_referencia(sesion: Session, referencia: str) -> PagoDeReserva | None:
    return sesion.scalars(
        select(PagoDeReserva).where(PagoDeReserva.referencia == referencia)
    ).first()


def aprobado_de(sesion: Session, reserva_id: int) -> PagoDeReserva | None:
    """El pago aprobado de una reserva, si lo hay. Hay a lo sumo uno."""
    return sesion.scalars(
        select(PagoDeReserva).where(
            PagoDeReserva.reserva_id == reserva_id,
            PagoDeReserva.estado == EstadoPago.APROBADO,
        )
    ).first()


def ultimo_de_mostrador(sesion: Session, reserva_id: int) -> PagoDeReserva | None:
    """El último intento de cobro con QR de una reserva.

    El último y no "el pendiente": si el cajero volvió a poner el monto en el
    QR, el intento vivo es el nuevo y el anterior ya no se consulta.
    """
    return sesion.scalars(
        select(PagoDeReserva)
        .where(
            PagoDeReserva.reserva_id == reserva_id,
            PagoDeReserva.canal == CanalDePago.MOSTRADOR,
        )
        .order_by(PagoDeReserva.id.desc())
    ).first()


def aplicar_pago_aprobado(
    sesion: Session, pago: PagoDeReserva, *, payment_id: str, estado_mp: str
) -> bool:
    """Confirma la reserva de un pago aprobado. Devuelve si cambió algo.

    🔑 **Es idempotente, y no por prolijidad.** MercadoPago reintenta las
    notificaciones —y manda varias por el mismo pago— así que esta función se
    llama más de una vez con los mismos datos. Sin el corte, la reserva se
    volvería a confirmar y el ingreso entraría dos veces a la caja.

    ⚠️ **Una reserva vencida NO se confirma.** Si el jugador pagó después de que
    la provisoria venciera, el turno pudo haberse vendido a otro: confirmarla
    ahora pondría dos reservas encima. El pago queda registrado como aprobado —la
    plata entró y hay que devolverla— y el turno no. Es un caso raro y ruidoso, y
    ruidoso es lo correcto: alguien tiene que mirarlo.

    🔑 **En un cobro de mostrador no hay nada que confirmar, y por eso alcanza
    con la misma función.** El turno ya está confirmado (o jugado), así que cae
    en la rama de arriba y lo único que hace es sellar el pago. Lo que le falta
    a ese caso —el movimiento de caja y la factura— lo agrega
    `servicios/cobro_qr.py`, que llama a ésta primero: acá no entra porque
    necesita saber quién cobra, y el webhook no lo sabe.
    """
    if pago.estado is EstadoPago.APROBADO:
        return False

    pago.estado = EstadoPago.APROBADO
    pago.payment_id = payment_id
    pago.estado_mp = estado_mp
    pago.pagado_at = ahora()

    reserva = sesion.get(Reserva, pago.reserva_id)
    if reserva is None:
        raise PagoInvalido(f"El pago {pago.id} apunta a una reserva que no existe.")
    if reserva.estado is not EstadoReserva.PROVISORIA:
        # Vencida, cancelada, o ya confirmada por otro camino. No se toca.
        return True

    reserva.estado = EstadoReserva.CONFIRMADA
    # 🔑 Se limpia el vencimiento: una confirmada con `vence_at` la levantaría
    # `vencer_provisorias` en la próxima corrida y el jugador perdería el turno
    # que pagó. El CHECK de la base sólo exige `vence_at` para las provisorias,
    # así que dejarlo puesto no falla — se descubriría con el turno perdido.
    reserva.vence_at = None
    return True


def aplicar_pago_rechazado(
    sesion: Session, pago: PagoDeReserva, *, payment_id: str, estado_mp: str
) -> None:
    """Deja constancia del rechazo. **La reserva no se cancela acá.**

    Sigue provisoria y con su vencimiento corriendo: el jugador puede reintentar
    con otra tarjeta dentro de la ventana, y si no lo hace el turno se libera
    solo. Cancelarla al primer rechazo le sacaría el turno a alguien que estaba
    por pagar.
    """
    if pago.estado is EstadoPago.APROBADO:
        return
    pago.estado = EstadoPago.RECHAZADO
    pago.payment_id = payment_id
    pago.estado_mp = estado_mp


def marcar_vencidos(sesion: Session, momento: datetime | None = None) -> int:
    """Los pagos pendientes de reservas que ya vencieron. Devuelve cuántos.

    Corre junto con `vencer_provisorias`: sin esto, un pago pendiente de una
    reserva que se liberó hace un mes sigue figurando como "esperando pago".
    """
    momento = momento or ahora()
    pendientes = sesion.scalars(
        select(PagoDeReserva)
        .join(Reserva, Reserva.id == PagoDeReserva.reserva_id)
        .where(
            PagoDeReserva.estado == EstadoPago.PENDIENTE,
            Reserva.estado != EstadoReserva.PROVISORIA,
        )
    ).all()
    for pago in pendientes:
        pago.estado = EstadoPago.VENCIDO
    return len(pendientes)


# ── El webhook ───────────────────────────────────────────────────────────


def firma_valida(
    *, x_signature: str, x_request_id: str, payment_id: str, secreto: str
) -> bool:
    """Si la notificación viene de verdad de MercadoPago.

    🔴 **Sin esto, un POST cualquiera confirma reservas.** El endpoint del
    webhook es público —tiene que serlo, lo llama MercadoPago— así que la firma
    es lo único que separa una notificación real de una inventada.

    🔑 **El HMAC lo hace el motor** desde el 2026-08-27. Estaba escrito dos
    veces y el docstring de esta función ya lo admitía —*"misma implementación
    que Contalibra"*—: el mismo algoritmo, la misma plantilla y la misma
    comparación en tiempo constante, en dos lugares que había que acordarse de
    actualizar juntos si MercadoPago cambiaba el esquema.

    🔴 **Lo que NO se delega es el guard del secreto vacío**, y es a propósito.
    `verificar_firma` del motor no lo chequea: con `secret=""` calcula el HMAC
    con clave vacía y compara. Peor todavía, el webhook del motor **saltea la
    verificación entera** si no hay secreto configurado. Acá eso no puede pasar:
    sin secreto no se verifica nada, y procesar sin verificar es peor que no
    procesar — cualquiera confirmaría reservas. Hay un test que lo fija.

    > El parámetro `cuerpo` se retiró: no se usaba. La plantilla de MercadoPago
    > es `id:<payment>;request-id:<req>;ts:<ts>` y **el cuerpo no entra en la
    > firma**; tenerlo ahí sugería lo contrario.
    """
    if not secreto:
        return False
    return verificar_firma(x_signature, x_request_id, payment_id, secreto)
