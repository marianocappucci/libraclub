"""Las reservas `en_conflicto`: cuáles son y cómo se resuelven (ADR-022).

Una reserva queda `en_conflicto` cuando se dio en el club sin conexión y, al llegar al central, la cancha ya
estaba tomada por otra que llegó antes (`servicios/reservas_nodo.aplicar_reserva_creada`). No ocupa la cancha: no
está en `ESTADOS_QUE_OCUPAN`, ni la grilla la pinta ni la exclusión la mira. Sigue siendo una reserva de un
cliente que fue al club a jugar: **alguien tiene que llamarlo**. Por eso no se descarta sola, ni vence, ni se
pasa a `cancelada` sin que una persona lo decida.

## Cómo se resuelve: dos caminos, los dos desde el central

- **mover**: la pasa a otro horario y/o otra cancha libres (`comienza_at`, `cancha_id`; la duración se conserva) y
  vuelve al estado que tenía (`estado_previo`: `confirmada` o `pendiente_pago`). Sin ningún dato lo intenta en el
  horario original: sirve cuando la que ganó se canceló y la cancha se liberó.
- **cancelar**: la cancela por `servicios/cancelacion.py`, que **devuelve siempre la seña entera** sin mirar la
  política de la sucursal (decisión del humano, 2026-10-24: el conflicto no es culpa del jugador). Sale por donde
  entró: MercadoPago si la seña se pagó por ahí, la caja si fue en efectivo. Queda auditado en el motivo de la
  reserva (`Conflicto de reserva del nodo: ...`) y en el concepto del egreso de caja.

Ninguna se hace en un nodo (409 `solo_en_el_central`): el nodo ve el conflicto, que le llega por el espejo, pero
sus filas del central son de sólo lectura y no tiene cómo subir el cambio.

Mover **conserva el precio y la seña** que se le dijo al cliente, aunque el nuevo horario tenga otra tarifa: el
conflicto no es culpa suya.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import EstadoReserva
from app.models.maestros import Cancha
from app.models.reservas import Reserva
from app.servicios import cancelacion, devoluciones, reservas_nodo
from app.servicios import reservas as servicio
from app.tiempo import ahora


@dataclass(frozen=True, slots=True)
class Conflicto:
    """Una reserva en conflicto y la que le ganó (`None` si ya no se sabe cuál fue)."""

    reserva: Reserva
    ganadora: Reserva | None


def listar(sesion: Session, sucursal_id: int | None = None) -> list[Conflicto]:
    """Las reservas `en_conflicto`, por orden de horario, cada una con la que le ganó."""
    consulta = (
        select(Reserva)
        .join(Cancha, Reserva.cancha_id == Cancha.id)
        .where(Reserva.estado == EstadoReserva.EN_CONFLICTO)
    )
    if sucursal_id is not None:
        consulta = consulta.where(Cancha.sucursal_id == sucursal_id)
    reservas = list(sesion.scalars(consulta.order_by(Reserva.comienza_at, Reserva.id)).all())

    ids = {r.conflicto_con_id for r in reservas if r.conflicto_con_id is not None}
    ganadoras = {}
    if ids:
        ganadoras = {r.id: r for r in sesion.scalars(select(Reserva).where(Reserva.id.in_(ids))).all()}
    return [Conflicto(r, ganadoras.get(r.conflicto_con_id)) for r in reservas]


def _en_conflicto(sesion: Session, reserva_id: int) -> Reserva:
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None:
        raise servicio.ReservaInvalida("No existe esa reserva.")
    if reserva.estado is not EstadoReserva.EN_CONFLICTO:
        raise servicio.TransicionInvalida(
            f"Una reserva {reserva.estado.value} no está en conflicto: no hay nada que resolver."
        )
    return reserva


def mover(
    sesion: Session,
    reserva_id: int,
    *,
    comienza_at: datetime | None = None,
    cancha_id: int | None = None,
) -> Reserva:
    """Resuelve el conflicto llevando la reserva a un horario libre. No commitea.

    Valida lo que valida una reserva nueva: la cancha existe y está activa, el horario de atención y que no haya
    nada encima (`Superpuesta`, con el horario que la ocupa). Si en el medio alguien tomó ese horario, la exclusión
    de la base lo frena igual."""
    reservas_nodo.exigir_central(reservas_nodo.MENSAJE_CONFLICTO_SOLO_EN_EL_CENTRAL)
    reserva = _en_conflicto(sesion, reserva_id)

    duracion = reserva.termina_at - reserva.comienza_at
    nueva_cancha_id = cancha_id if cancha_id is not None else reserva.cancha_id
    nuevo_comienzo = comienza_at if comienza_at is not None else reserva.comienza_at
    nuevo_fin = nuevo_comienzo + duracion

    cancha = sesion.get(Cancha, nueva_cancha_id)
    if cancha is None:
        raise servicio.ReservaInvalida("No existe esa cancha.")
    if not cancha.activa:
        raise servicio.ReservaInvalida(f"La cancha {cancha.nombre} está dada de baja.")
    servicio._verificar_dentro_del_horario(sesion, cancha, nuevo_comienzo, nuevo_fin)
    servicio._verificar_libre(sesion, nueva_cancha_id, nuevo_comienzo, nuevo_fin, excluir_id=reserva.id)

    reserva.cancha_id = nueva_cancha_id
    reserva.comienza_at = nuevo_comienzo
    reserva.termina_at = nuevo_fin
    reserva.estado = reserva.estado_previo or EstadoReserva.CONFIRMADA
    # Si vuelve a `pendiente_pago`, el plazo de la seña empieza ahora y sobre el horario nuevo: el conflicto lo
    # causó el club (se vendió dos veces la cancha), y no es justo que le cuente al jugador.
    reserva.vence_at = (
        servicio.vencimiento_de_sena(ahora(), nuevo_comienzo)
        if reserva.estado is EstadoReserva.PENDIENTE_PAGO
        else None
    )
    reserva.conflicto_con_id = None
    reserva.estado_previo = None
    reserva.motivo = None
    # El `UPDATE` pasa por el mismo savepoint que un alta: si la exclusión lo rechaza, es `Superpuesta`.
    servicio._guardar(sesion, reserva)
    return reserva


def cancelar(
    sesion: Session,
    reserva_id: int,
    *,
    motivo: str | None,
    pasarela: devoluciones.Pasarela,
    usuario: dict | None = None,
) -> cancelacion.Resultado:
    """Resuelve el conflicto cancelando la reserva y devolviendo la seña entera, sea cual sea la política de la
    sucursal (`cancelacion.cancelar` lo decide por el estado `en_conflicto`). No commitea."""
    reservas_nodo.exigir_central(reservas_nodo.MENSAJE_CONFLICTO_SOLO_EN_EL_CENTRAL)
    _en_conflicto(sesion, reserva_id)
    return cancelacion.cancelar(
        sesion,
        reserva_id,
        motivo=motivo or "Cancelada al resolver el conflicto",
        pasarela=pasarela,
        usuario=usuario,
    )
