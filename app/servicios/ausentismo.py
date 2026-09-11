"""Ausentismo: cuántas veces faltó un cliente sin avisar, y si ya es reincidente.

Es el último punto de la Fase A. `AUSENTE` se marcaba desde el primer día —la
agenda tiene el botón— pero **nadie lo contaba**: el que faltó tres veces este
mes reservaba igual que el que viene todos los martes, y el encargado se enteraba
cuando la cancha quedaba vacía otra vez.

## Contar y avisar, sin bloquear

Decisión del humano: **no se bloquea a nadie**, ni en el mostrador ni en el
portal. El mostrador ve el aviso —cuántas veces faltó y cuándo fue la última— y
decide él: pedirle la seña entera, llamarlo el día antes, o tomarle el turno
igual porque sabe que se le murió el perro. Un bloqueo automático se equivoca en
todos esos casos, y el cliente que se lo come se va a otro complejo.

🔑 **La regla vive acá y en ningún otro lado.** El umbral y la ventana son dos
constantes de este módulo, y la API devuelve **ya resuelto** si el cliente es
reincidente. La pantalla no sabe que son «3 en 90 días»: si lo supiera, el día
que el número cambie habría dos lugares que actualizar y uno se quedaría viejo.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import EstadoReserva
from app.models.reservas import Reserva
from app.tiempo import ahora

#: Desde cuántas ausencias el mostrador ve el aviso.
UMBRAL = 3

#: Hacia atrás, desde hoy, cuánto se mira. Un cliente que faltó tres veces hace
#: un año y desde entonces viene siempre no es un problema de hoy.
VENTANA = timedelta(days=90)


@dataclass(frozen=True, slots=True)
class Ausentismo:
    """Las ausencias de un cliente dentro de la ventana."""

    cliente_id: int
    ausentes: int
    #: El comienzo del último turno al que faltó. `None` si no faltó a ninguno.
    ultimo: datetime | None

    @property
    def reincidente(self) -> bool:
        return self.ausentes >= UMBRAL


def de_clientes(
    sesion: Session,
    cliente_ids: Iterable[int] | None = None,
    momento: datetime | None = None,
) -> dict[int, Ausentismo]:
    """Las ausencias por cliente, **en una sola consulta**.

    `cliente_ids=None` trae a todos los que faltaron alguna vez en la ventana. Un
    cliente que no aparece en el resultado no faltó: no se completa con ceros
    para no devolver una fila por cada cliente de la base.

    🔑 **La ventana se mide sobre `comienza_at`, no sobre cuándo se marcó.** Lo
    que importa es a qué turno faltó; que el encargado lo haya marcado a la
    mañana siguiente no cambia cuándo pasó. Y tiene cota de arriba: un turno
    futuro marcado `ausente` por error no cuenta como algo que ya pasó.
    """
    momento = momento or ahora()
    consulta = (
        select(
            Reserva.cliente_id,
            func.count(Reserva.id),
            func.max(Reserva.comienza_at),
        )
        .where(
            Reserva.estado == EstadoReserva.AUSENTE,
            Reserva.comienza_at >= momento - VENTANA,
            Reserva.comienza_at <= momento,
        )
        .group_by(Reserva.cliente_id)
    )
    if cliente_ids is not None:
        ids = [int(x) for x in cliente_ids]
        if not ids:
            return {}
        consulta = consulta.where(Reserva.cliente_id.in_(ids))
    return {
        cliente_id: Ausentismo(cliente_id, int(cuantas), ultimo)
        for cliente_id, cuantas, ultimo in sesion.execute(consulta).all()
    }


def reincidentes(sesion: Session, momento: datetime | None = None) -> list[Ausentismo]:
    """Los clientes que pasaron el umbral, el que más faltó primero."""
    return sorted(
        (a for a in de_clientes(sesion, momento=momento).values() if a.reincidente),
        key=lambda a: (-a.ausentes, a.cliente_id),
    )
