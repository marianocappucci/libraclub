"""La grilla: qué hay y qué queda libre en una cancha, día por día."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ESTADOS_QUE_OCUPAN, EstadoReserva
from app.models.maestros import Cancha, Feriado
from app.models.reservas import Reserva
from app.servicios import tarifario
from app.tiempo import TZ, a_local

#: Horario por defecto del complejo, mientras no exista una tabla de
#: disponibilidad semanal por cancha. **Es un supuesto, no un relevamiento** —
#: ver TASKS.md. Cuando entre el horario configurable, esto se borra; hasta
#: entonces está acá arriba y con nombre, y no metido en medio de una función.
APERTURA = time(8, 0)
CIERRE = time(0, 0)  # medianoche: se trata como "fin del día"


@dataclass(frozen=True, slots=True)
class Turno:
    """Un casillero de la grilla."""

    comienza_at: datetime
    termina_at: datetime
    libre: bool
    precio: Decimal | None = None
    reserva_id: int | None = None
    estado: EstadoReserva | None = None
    cliente: str | None = None
    motivo: str | None = None


def _fin_del_dia(dia: date) -> datetime:
    """Medianoche del día siguiente, en hora local.

    Se calcula así y no como `time(23, 59)` porque un turno de 23:00 a 00:30 es
    normal en un complejo de pádel, y con el corte a las 23:59 desaparecería de
    la grilla justo la franja más cara.
    """
    return datetime.combine(dia + timedelta(days=1), time(0, 0), tzinfo=TZ)


def grilla_del_dia(
    sesion: Session, cancha: Cancha, dia: date, *, con_precio: bool = True
) -> list[Turno]:
    """Los turnos de una cancha en un día, ocupados y libres.

    El paso de la grilla es `cancha.duracion_turno_min`. Una reserva que no cae
    en la grilla —un torneo de tres horas que arranca a las 17:20— **igual
    aparece**: se dibuja sobre los casilleros que toca. Alinear la vista a la
    grilla escondería reservas reales, que es peor que una fila despareja.
    """
    comienzo = datetime.combine(dia, APERTURA, tzinfo=TZ)
    fin = _fin_del_dia(dia)
    paso = timedelta(minutes=cancha.duracion_turno_min)

    cerrado = sesion.scalars(
        select(Feriado).where(
            Feriado.sucursal_id == cancha.sucursal_id,
            Feriado.dia == dia,
            Feriado.cerrado.is_(True),
        )
    ).first()
    if cerrado is not None:
        return []

    reservas = list(
        sesion.scalars(
            select(Reserva)
            .where(
                Reserva.cancha_id == cancha.id,
                Reserva.estado.in_(ESTADOS_QUE_OCUPAN),
                Reserva.comienza_at < fin,
                Reserva.termina_at > comienzo,
            )
            .order_by(Reserva.comienza_at)
        ).all()
    )

    turnos: list[Turno] = []
    momento = comienzo
    while momento + paso <= fin:
        termina = momento + paso
        ocupa = next(
            (
                r
                for r in reservas
                if r.comienza_at < termina and r.termina_at > momento
            ),
            None,
        )
        if ocupa is not None:
            turnos.append(
                Turno(
                    comienza_at=momento,
                    termina_at=termina,
                    libre=False,
                    reserva_id=ocupa.id,
                    estado=ocupa.estado,
                    cliente=ocupa.cliente.nombre if ocupa.cliente else None,
                    motivo=ocupa.motivo,
                )
            )
        else:
            precio = None
            if con_precio:
                try:
                    precio, _ = tarifario.precio_y_sena(sesion, cancha, momento)
                except tarifario.SinTarifa:
                    # Un turno sin tarifa **se muestra igual, sin precio**. Si se
                    # escondiera, la franja sin precio cargado sería invisible y
                    # nadie se enteraría de que falta cargarla.
                    precio = None
            turnos.append(
                Turno(comienza_at=momento, termina_at=termina, libre=True, precio=precio)
            )
        momento = termina
    return turnos


def grilla_de_la_semana(
    sesion: Session, sucursal_id: int, desde: date
) -> dict[int, dict[str, list[Turno]]]:
    """Siete días de todas las canchas activas de una sucursal.

    Devuelve `{cancha_id: {"2026-08-20": [turnos...]}}`. La clave del día es la
    fecha **local en ISO**, no un índice: un cliente que renderiza la semana
    tiene que poder mostrar la fecha sin recalcularla, y un índice 0-6 obliga a
    saber en qué día arranca la semana.
    """
    canchas = list(
        sesion.scalars(
            select(Cancha)
            .where(Cancha.sucursal_id == sucursal_id, Cancha.activa.is_(True))
            .order_by(Cancha.orden, Cancha.nombre)
        ).all()
    )
    resultado: dict[int, dict[str, list[Turno]]] = {}
    for cancha in canchas:
        por_dia: dict[str, list[Turno]] = {}
        for offset in range(7):
            dia = desde + timedelta(days=offset)
            por_dia[dia.isoformat()] = grilla_del_dia(sesion, cancha, dia)
        resultado[cancha.id] = por_dia
    return resultado


def proximas(sesion: Session, sucursal_id: int, momento: datetime, limite: int = 20):
    """Las próximas reservas de la sucursal. Para la pantalla de inicio."""
    return list(
        sesion.scalars(
            select(Reserva)
            .join(Cancha, Reserva.cancha_id == Cancha.id)
            .where(
                Cancha.sucursal_id == sucursal_id,
                Reserva.estado.in_(ESTADOS_QUE_OCUPAN),
                Reserva.comienza_at >= momento,
            )
            .order_by(Reserva.comienza_at)
            .limit(limite)
        ).all()
    )


def dia_local(momento: datetime) -> date:
    """Atajo con nombre, para no repetir `a_local(x).date()` por todos lados."""
    return a_local(momento).date()
