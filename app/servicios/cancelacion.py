"""Qué pasa con la plata cuando se cae un turno.

Hasta acá cancelar era gratis y sin consecuencias: el turno se liberaba y **la
seña se quedaba donde estaba**, ni devuelta ni anotada como no devuelta. Es la
segunda brecha de la Fase A, y la que Alquila Tu Cancha vende como funcionalidad
propia: *devolución automática si cancela con más de 24 horas*.

## Las tres decisiones

**Cancelar siempre se puede.** La ventana decide si se devuelve la plata, no si
el jugador puede soltar el turno. Impedirle cancelar fuera de plazo no le
devuelve la cancha al complejo: la deja ocupada por alguien que ya sabe que no
viene, y encima sin poder revenderla.

**La cancelación nunca se cae porque falle la devolución.** Soltar el turno es
una acción del cliente; devolverle la plata es una deuda del complejo. Si
MercadoPago no contesta, el turno igual queda libre y la deuda queda anotada —al
revés, un jugador que no puede cancelar porque la API de otro está caída llama
por teléfono, y el turno se pierde igual.

**Sólo se devuelve el pago del portal.** Un cobro de mostrador ya entró a la
caja del turno (`PagoDeReserva.caja_movimiento_id`): devolverlo por API dejaría
el arqueo descuadrado, con la plata saliendo por un lado que la caja no ve. Esa
devolución se hace **desde la caja**, y acá se dice explícitamente en vez de
hacerla a medias.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import EstadoReserva
from app.models.maestros import Cancha, Sucursal
from app.models.reservas import CanalDePago, EstadoPago, PagoDeReserva, Reserva
from app.servicios import devoluciones
from app.servicios import reservas as servicio_reservas
from app.tiempo import ahora


@dataclass(frozen=True, slots=True)
class Politica:
    """La ventana de la sucursal, y de qué lado del corte cae este turno."""

    #: `None` = la sucursal no configuró política, o sea que no devuelve nada.
    horas: int | None
    #: Cuánto falta para el turno, en el momento de cancelar.
    faltan: timedelta

    @property
    def hay_politica(self) -> bool:
        return self.horas is not None

    @property
    def a_tiempo(self) -> bool:
        """Si se avisó con la anticipación que pide la sucursal.

        Sin política, nunca está «a tiempo»: no es que llegó tarde, es que no
        hay devolución que ganarse. Los dos casos se distinguen con
        `hay_politica`, y la pantalla dice cosas distintas.
        """
        if self.horas is None:
            return False
        return self.faltan >= timedelta(hours=self.horas)


@dataclass(frozen=True, slots=True)
class Resultado:
    """Qué terminó pasando. Es lo que el portal le muestra al jugador."""

    reserva: Reserva
    politica: Politica
    #: El pago que se miró, si había alguno aprobado.
    pago: PagoDeReserva | None
    #: En qué quedó la devolución. `None` = no correspondía ninguna.
    devolucion: EstadoPago | None
    #: En castellano, **para el mostrador**. Siempre dice algo: «no correspondía»
    #: también es una respuesta, y es la que evita el llamado preguntando qué
    #: pasó.
    #:
    #: 🔴 **No se le muestra al jugador.** Nombra la configuración de la
    #: instancia —«no tiene MercadoPago configurado», «la sucursal no tiene
    #: política cargada»— y el portal está expuesto a internet sin sesión: eso es
    #: información del complejo, no de quien pregunta. Para el portal está
    #: `para_el_jugador`.
    detalle: str

    @property
    def para_el_jugador(self) -> str:
        """Lo mismo, contado para quien canceló y sin datos del complejo.

        Habla de **su** plata y de nada más. Un jugador que cancela no tiene por
        qué enterarse de si el complejo cargó sus credenciales de MercadoPago.
        """
        if self.devolucion is EstadoPago.DEVUELTO:
            return "Te devolvimos la seña. Puede tardar unos días en verse en tu cuenta."
        if self.devolucion is EstadoPago.DEVOLUCION_PENDIENTE:
            # No dice por qué, pero **sí** dice que le corresponde: es la
            # diferencia entre un jugador que espera y uno que se siente
            # estafado.
            return "Te corresponde la devolución de la seña y la estamos gestionando."
        if self.pago is None:
            return "Tu turno quedó cancelado."
        if self.politica.hay_politica and not self.politica.a_tiempo:
            return (
                f"Tu turno quedó cancelado. Se canceló con menos de "
                f"{self.politica.horas} horas de anticipación, así que la seña no "
                f"se devuelve."
            )
        return "Tu turno quedó cancelado. La seña no se devuelve."


def politica_de(sesion: Session, reserva: Reserva, momento: datetime | None = None) -> Politica:
    """La política que le aplica a este turno.

    Sale de la **sucursal de la cancha**, no de la reserva: la reserva no guarda
    a qué sucursal pertenece —la deduce por la cancha— y duplicar el dato acá
    sería un tercer lugar donde puede quedar viejo.
    """
    momento = momento or ahora()
    horas = sesion.scalar(
        select(Sucursal.horas_de_cancelacion)
        .join(Cancha, Cancha.sucursal_id == Sucursal.id)
        .where(Cancha.id == reserva.cancha_id)
    )
    return Politica(horas=horas, faltan=reserva.comienza_at - momento)


def _pago_devolvible(sesion: Session, reserva_id: int) -> PagoDeReserva | None:
    """El pago aprobado de esta reserva, si hay uno.

    Devuelve también el de mostrador —no lo filtra acá— porque el llamador tiene
    que poder **decir** que no lo devuelve y por qué. Filtrarlo en la consulta
    haría que ese caso se vea igual que «no había pago».
    """
    return sesion.scalars(
        select(PagoDeReserva).where(
            PagoDeReserva.reserva_id == reserva_id,
            PagoDeReserva.estado == EstadoPago.APROBADO,
        )
    ).first()


def _intentar(
    pago: PagoDeReserva, pasarela: devoluciones.Pasarela
) -> tuple[EstadoPago, str]:
    """Le pide la devolución a la pasarela. No commitea ni decide política.

    Devuelve en qué quedó el pago y el texto para mostrar. **No propaga la
    excepción**: la falla de la devolución no puede voltear la cancelación.
    """
    if not pasarela.disponible():
        return (
            EstadoPago.DEVOLUCION_PENDIENTE,
            "Falta devolver la seña: la instancia no tiene MercadoPago configurado.",
        )
    if not pago.payment_id:
        # Aprobado sin `payment_id` es el pago simulado de dev: no existe del
        # lado de MercadoPago, así que no hay nada que devolver allá.
        return (
            EstadoPago.DEVOLUCION_PENDIENTE,
            "Falta devolver la seña: el pago no tiene id de MercadoPago.",
        )
    try:
        refund_id = pasarela.devolver(
            payment_id=pago.payment_id,
            # La clave de idempotencia es de la **referencia del pago**, que es
            # nuestra y única: todos los reintentos mandan la misma y
            # MercadoPago devuelve una sola vez.
            referencia=f"devolucion-{pago.referencia}",
        )
    except devoluciones.DevolucionRechazada as exc:
        return EstadoPago.DEVOLUCION_PENDIENTE, str(exc)[:500]

    pago.refund_id = refund_id
    pago.devuelto_at = ahora()
    return EstadoPago.DEVUELTO, "Se devolvió la seña."


def cancelar(
    sesion: Session,
    reserva_id: int,
    *,
    motivo: str,
    pasarela: devoluciones.Pasarela,
    momento: datetime | None = None,
) -> Resultado:
    """Cancela el turno y resuelve la seña según la política. No commitea.

    El orden importa: **primero se cancela** y después se mira la plata. Al
    revés, un error de MercadoPago dejaría el turno sin cancelar y la cancha
    ocupada por alguien que ya avisó que no viene.
    """
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None:
        raise servicio_reservas.ReservaInvalida("No existe esa reserva.")

    politica = politica_de(sesion, reserva, momento)
    reserva = servicio_reservas.cambiar_estado(
        sesion, reserva_id, EstadoReserva.CANCELADA, motivo=motivo
    )

    pago = _pago_devolvible(sesion, reserva_id)
    if pago is None:
        return Resultado(reserva, politica, None, None, "No había seña pagada.")

    if pago.canal is CanalDePago.MOSTRADOR:
        return Resultado(
            reserva, politica, pago, None,
            "El cobro fue por caja: la devolución se hace desde la caja, no por API.",
        )

    if not politica.hay_politica:
        return Resultado(
            reserva, politica, pago, None,
            "La sucursal no tiene política de cancelación cargada: la seña no se devuelve.",
        )

    if not politica.a_tiempo:
        return Resultado(
            reserva, politica, pago, None,
            f"Se canceló con menos de {politica.horas} horas: la seña no se devuelve.",
        )

    estado, detalle = _intentar(pago, pasarela)
    pago.estado = estado
    pago.detalle_devolucion = None if estado is EstadoPago.DEVUELTO else detalle
    sesion.flush()
    return Resultado(reserva, politica, pago, estado, detalle)


def reintentar(
    sesion: Session, pago_id: int, *, pasarela: devoluciones.Pasarela
) -> Resultado:
    """Vuelve a pedir una devolución que quedó pendiente. No commitea.

    🔑 **Lo dispara una persona, no un cron.** Una devolución que falla suele
    fallar por algo que hay que arreglar —credenciales, un pago que MercadoPago
    no deja devolver— y un reintento automático cada cinco minutos lo único que
    agrega es ruido en el log. La clave de idempotencia hace que apretar el
    botón dos veces no devuelva dos veces.
    """
    pago = sesion.get(PagoDeReserva, pago_id)
    if pago is None:
        raise servicio_reservas.ReservaInvalida("No existe ese pago.")
    if pago.estado is not EstadoPago.DEVOLUCION_PENDIENTE:
        raise servicio_reservas.TransicionInvalida(
            f"Ese pago está {pago.estado.value}, no hay devolución pendiente."
        )

    reserva = sesion.get(Reserva, pago.reserva_id)
    estado, detalle = _intentar(pago, pasarela)
    pago.estado = estado
    pago.detalle_devolucion = None if estado is EstadoPago.DEVUELTO else detalle
    sesion.flush()
    return Resultado(reserva, politica_de(sesion, reserva), pago, estado, detalle)


def pendientes(sesion: Session) -> list[PagoDeReserva]:
    """Las devoluciones que el complejo debe.

    🔴 Sin esta lista, `DEVOLUCION_PENDIENTE` sería un estado que nadie mira: la
    plata quedaría debida y la única forma de enterarse sería que el jugador
    llame. Es lo que hace que el estado sirva para algo.
    """
    return list(
        sesion.scalars(
            select(PagoDeReserva)
            .where(PagoDeReserva.estado == EstadoPago.DEVOLUCION_PENDIENTE)
            .order_by(PagoDeReserva.id)
        ).all()
    )
