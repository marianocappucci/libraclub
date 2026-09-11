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

**El pago del portal vuelve por MercadoPago; el de mostrador, por la caja.** Un
cobro de mostrador ya entró a la caja del turno (`PagoDeReserva.caja_movimiento_id`):
devolverlo por API dejaría el arqueo descuadrado, con la plata saliendo por un
lado que la caja no ve. Esa devolución es un **egreso de la caja del turno
abierto** de quien cancela.

🔴 Hasta el 2026-09-11 esto último se **decía** y no se hacía: el resultado
anunciaba «la devolución se hace desde la caja» y no registraba nada. El pago
seguía `aprobado` y la plata que se le devolvía al jugador salía del cajón como
un faltante sin explicación en el arqueo. Ver ADR-016, decisión 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import EstadoReserva
from app.models.maestros import Cancha, Sucursal
from app.models.reservas import CanalDePago, EstadoPago, PagoDeReserva, Reserva
from app.servicios import caja as servicio_caja
from app.servicios import devoluciones, facturacion
from app.servicios import reservas as servicio_reservas
from app.tiempo import a_local, ahora


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


def que_paso_con_la_sena(pago: PagoDeReserva | None, politica: Politica) -> str | None:
    """Qué pasó con la seña, contado para el jugador. `None` si no hubo seña.

    🔑 **Es la única fuente de estos textos**, y la leen dos lugares: el portal,
    en la respuesta de la cancelación, y el aviso de cancelación que manda el
    cron (`servicios/avisos.py`). Hasta el 2026-09-11 vivían adentro de
    `Resultado` y el mail no los tenía: el que canceló por teléfono se enteraba
    de qué pasó con su plata llamando otra vez.

    Lee el **estado guardado del pago** y no lo que se intentó en el momento: el
    mail sale minutos después, en otro proceso, y lo único que tiene es la base.
    Por eso recibe el pago y no el `Resultado`.

    🔴 **Habla de su plata y de nada más.** Nada de «no tiene MercadoPago
    configurado» ni de «no hay caja abierta»: eso es información del complejo, y
    el portal está expuesto a internet sin sesión. El detalle interno está en
    `Resultado.detalle` y en `PagoDeReserva.detalle_devolucion`.
    """
    if pago is None:
        return None
    if pago.estado is EstadoPago.DEVUELTO:
        if pago.canal is CanalDePago.MOSTRADOR:
            # Salió del cajón, en efectivo. «Puede tardar en verse en tu
            # cuenta» sería mentira: no pasa por ninguna cuenta.
            return "La seña se te devuelve en efectivo, en el mostrador del complejo."
        return "Te devolvimos la seña. Puede tardar unos días en verse en tu cuenta."
    if pago.estado is EstadoPago.DEVOLUCION_PENDIENTE:
        # No dice por qué, pero **sí** dice que le corresponde: es la
        # diferencia entre un jugador que espera y uno que se siente estafado.
        return "Te corresponde la devolución de la seña y la estamos gestionando."
    if politica.hay_politica and not politica.a_tiempo:
        # Con el número: «con menos de 24 horas» se puede discutir; «no se
        # devuelve» a secas se lee como arbitrario.
        return (
            f"Se canceló con menos de {politica.horas} horas de anticipación, "
            f"así que la seña no se devuelve."
        )
    return "La seña no se devuelve."


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
        """Lo mismo, contado para quien canceló y sin datos del complejo."""
        sena = que_paso_con_la_sena(self.pago, self.politica)
        if sena is None:
            return "Tu turno quedó cancelado."
        return f"Tu turno quedó cancelado. {sena}"


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
    """El pago aprobado de esta reserva, si hay uno."""
    return sesion.scalars(
        select(PagoDeReserva).where(
            PagoDeReserva.reserva_id == reserva_id,
            PagoDeReserva.estado == EstadoPago.APROBADO,
        )
    ).first()


#: Los estados de un pago que dicen que **hubo seña**: la que se quedó el
#: complejo, la que se le debe al jugador y la que ya se le devolvió. Un pago
#: `pendiente`, `rechazado` o `vencido` es plata que nunca entró.
_ESTADOS_CON_SENA = (
    EstadoPago.APROBADO,
    EstadoPago.DEVOLUCION_PENDIENTE,
    EstadoPago.DEVUELTO,
)


def sena_para_el_aviso(sesion: Session, reserva: Reserva) -> str | None:
    """Qué pasó con la seña de una reserva ya cancelada, para el mail.

    Deriva todo del **estado guardado**: el pago de la reserva y la política de
    su sucursal. `None` si no hubo seña, y entonces el mail no dice nada de
    seña.

    🔑 **El momento de la cancelación es `reserva.updated_at`**, y alcanza aunque
    alguien toque la reserva después. El único texto que depende del momento es
    «se canceló con menos de N horas», y sólo sale para un pago que siguió
    `aprobado` — o sea que en su momento **no** estuvo a tiempo, porque a tiempo
    el pago habría pasado a `devuelto` o `devolucion_pendiente`. Un
    `updated_at` posterior sólo puede alejar más el momento del turno, así que
    no puede dar vuelta ese «tarde» en «a tiempo».
    """
    pago = sesion.scalars(
        select(PagoDeReserva)
        .where(
            PagoDeReserva.reserva_id == reserva.id,
            PagoDeReserva.estado.in_(_ESTADOS_CON_SENA),
        )
        .order_by(PagoDeReserva.id.desc())
    ).first()
    if pago is None:
        return None
    return que_paso_con_la_sena(pago, politica_de(sesion, reserva, reserva.updated_at))


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


#: Qué se anota cuando no hay caja de la que sacar la plata. Uno solo para los
#: dos caminos que llegan acá —el jugador que cancela desde el portal, que no
#: tiene caja, y el encargado que cancela con la caja cerrada—, porque para el
#: que lee la lista de pendientes son el mismo problema y tienen el mismo
#: arreglo: abrir la caja y reintentar.
SIN_CAJA_ABIERTA = "Falta devolver la seña desde la caja: se canceló sin un turno de caja abierto."


def _devolver_por_caja(
    pago: PagoDeReserva, reserva: Reserva, usuario: dict | None
) -> tuple[EstadoPago, str]:
    """La devolución de un cobro de mostrador: un egreso de la caja abierta.

    Mismo contrato que `_intentar`: no commitea, no decide política y **no
    propaga**. Sin caja de dónde sacarla, la deuda queda anotada con el motivo —
    el mismo criterio que MercadoPago sin credenciales— y **no se inventa
    nada**: ni un turno de caja, ni un movimiento suelto fuera del arqueo.

    🔑 **El egreso y el `DEVUELTO` viven en dos bases**, y el orden importa. El
    movimiento se escribe en la de LibraCore, que commitea sola; el estado del
    pago, en la del dominio, al final del request. Si ese segundo commit se
    pierde, el pago queda pendiente con la plata ya afuera — y el reintento **no
    la saca otra vez**: la referencia es del pago (`devolucion-<referencia>`) y
    `create_caja_movimiento` es idempotente por `(referencia, factura_id)`.
    """
    if pago.caja_movimiento_id is None:
        # Aprobado pero sin movimiento: el QR se acreditó con la caja cerrada y
        # el ingreso todavía no entró (ver `cobro_qr._completar`). Sacar un
        # egreso por una plata que la caja nunca vio dejaría el arqueo al revés.
        return (
            EstadoPago.DEVOLUCION_PENDIENTE,
            "Falta devolver la seña: el cobro por QR todavía no entró a la caja.",
        )
    if usuario is None:
        return EstadoPago.DEVOLUCION_PENDIENTE, SIN_CAJA_ABIERTA
    if not facturacion.hay_base():
        return (
            EstadoPago.DEVOLUCION_PENDIENTE,
            "Falta devolver la seña: la instancia no tiene la caja configurada.",
        )

    cancha = reserva.cancha
    cliente = reserva.cliente
    detalle = (
        f"Turno {a_local(reserva.comienza_at):%d-%m-%Y %H:%M}"
        f" — {cancha.nombre if cancha else 'cancha'}"
        f"{f' — {cliente.nombre}' if cliente else ''}"
    )
    try:
        servicio_caja.registrar_devolucion(
            usuario, pago.monto, detalle,
            referencia=f"{servicio_caja.PREFIJO_DEVOLUCION}{pago.referencia}",
        )
    except servicio_caja.SinTurnoAbierto:
        return EstadoPago.DEVOLUCION_PENDIENTE, SIN_CAJA_ABIERTA

    pago.devuelto_at = ahora()
    return (
        EstadoPago.DEVUELTO,
        "Se devolvió la seña desde la caja: quedó como egreso en efectivo del turno abierto.",
    )


def _devolver(
    pago: PagoDeReserva,
    reserva: Reserva,
    *,
    pasarela: devoluciones.Pasarela,
    usuario: dict | None,
) -> tuple[EstadoPago, str]:
    """Por dónde vuelve la plata: por donde entró.

    🔑 Lo decide el **canal del pago** y no quién cancela. Un pago del portal que
    el encargado cancela desde el mostrador vuelve por MercadoPago igual; un
    cobro de mostrador que el jugador cancela desde el portal no puede salir de
    ninguna caja, y queda pendiente.
    """
    if pago.canal is CanalDePago.MOSTRADOR:
        return _devolver_por_caja(pago, reserva, usuario)
    return _intentar(pago, pasarela)


def cancelar(
    sesion: Session,
    reserva_id: int,
    *,
    motivo: str,
    pasarela: devoluciones.Pasarela,
    usuario: dict | None = None,
    momento: datetime | None = None,
) -> Resultado:
    """Cancela el turno y resuelve la seña según la política. No commitea.

    `usuario` es quien cancela desde el mostrador: de **su** caja abierta sale
    la devolución de un cobro de mostrador. `None` desde el portal.

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

    # 🔑 La política va **antes** que el canal, para los dos. Hasta el
    # 2026-09-11 el cobro de mostrador se desviaba primero y la política ni se
    # miraba: daba igual, porque tampoco se devolvía. Ahora que se devuelve,
    # tiene que ganarse la devolución como cualquier otro.
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

    estado, detalle = _devolver(pago, reserva, pasarela=pasarela, usuario=usuario)
    pago.estado = estado
    pago.detalle_devolucion = None if estado is EstadoPago.DEVUELTO else detalle
    sesion.flush()
    return Resultado(reserva, politica, pago, estado, detalle)


def reintentar(
    sesion: Session,
    pago_id: int,
    *,
    pasarela: devoluciones.Pasarela,
    usuario: dict | None = None,
) -> Resultado:
    """Vuelve a pedir una devolución que quedó pendiente. No commitea.

    `usuario` es quien reintenta: si el pago es de mostrador, la devolución
    sale de **su** caja abierta.

    🔑 **Lo dispara una persona, no un cron.** Una devolución que falla suele
    fallar por algo que hay que arreglar —credenciales, un pago que MercadoPago
    no deja devolver, una caja cerrada— y un reintento automático cada cinco
    minutos lo único que agrega es ruido en el log. Apretar el botón dos veces
    no devuelve dos veces: por MercadoPago lo cuida la clave de idempotencia; por
    caja, la referencia del egreso.
    """
    pago = sesion.get(PagoDeReserva, pago_id)
    if pago is None:
        raise servicio_reservas.ReservaInvalida("No existe ese pago.")
    if pago.estado is not EstadoPago.DEVOLUCION_PENDIENTE:
        raise servicio_reservas.TransicionInvalida(
            f"Ese pago está {pago.estado.value}, no hay devolución pendiente."
        )

    reserva = sesion.get(Reserva, pago.reserva_id)
    estado, detalle = _devolver(pago, reserva, pasarela=pasarela, usuario=usuario)
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
