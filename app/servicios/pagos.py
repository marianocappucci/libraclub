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

import hashlib
import hmac
import secrets
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import EstadoReserva
from app.models.reservas import EstadoPago, PagoDeReserva, Reserva
from app.tiempo import ahora


class PagoNoConfigurado(RuntimeError):
    """La instancia no tiene credenciales de MercadoPago cargadas."""


class PagoInvalido(ValueError):
    pass


def nueva_referencia(reserva_id: int) -> str:
    """La referencia externa que viaja a MercadoPago y vuelve en el webhook.

    Lleva el id de la reserva **y** un sufijo aleatorio: el id solo no alcanza
    porque un pago rechazado se reintenta, y la referencia tiene que ser distinta
    para que el `UNIQUE` no bloquee el segundo intento.
    """
    return f"lc-{reserva_id}-{secrets.token_hex(6)}"


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
    )
    sesion.add(pago)
    sesion.flush()
    return pago


def por_referencia(sesion: Session, referencia: str) -> PagoDeReserva | None:
    return sesion.scalars(
        select(PagoDeReserva).where(PagoDeReserva.referencia == referencia)
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
    *, cuerpo: bytes, x_signature: str, x_request_id: str, payment_id: str, secreto: str
) -> bool:
    """Si la notificación viene de verdad de MercadoPago.

    🔴 **Sin esto, un POST cualquiera confirma reservas.** El endpoint del
    webhook es público —tiene que serlo, lo llama MercadoPago— así que la firma
    es lo único que separa una notificación real de una inventada.

    El template lo define MercadoPago: `id:<payment>;request-id:<req>;ts:<ts>`,
    firmado con HMAC-SHA256 y la clave secreta de la aplicación. Misma
    implementación que Contalibra, que ya la tiene en producción.
    """
    ts = v1 = ""
    for parte in x_signature.split(","):
        parte = parte.strip()
        if parte.startswith("ts="):
            ts = parte[3:]
        elif parte.startswith("v1="):
            v1 = parte[3:]
    if not ts or not v1 or not secreto:
        return False
    template = f"id:{payment_id};request-id:{x_request_id};ts:{ts}"
    esperado = hmac.new(secreto.encode(), template.encode(), hashlib.sha256).hexdigest()
    # `compare_digest` y no `==`: comparar hashes con `==` corta en el primer
    # byte distinto y filtra información por el tiempo de respuesta.
    return hmac.compare_digest(esperado, v1)
