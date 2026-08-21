"""La grilla: qué hay y qué queda libre en una cancha, día por día."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ESTADOS_QUE_OCUPAN, EstadoReserva
from app.models.maestros import Cancha
from app.models.reservas import Reserva
from app.servicios import horarios, tarifario
from app.tiempo import TZ, a_local


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

    Los casilleros salen del **horario de atención** de esa cancha ese día (ver
    `servicios/horarios.py`), que puede ser más de una franja: un complejo que
    abre de 9 a 13 y de 16 a 24 no tiene casilleros entre las 13 y las 16. El
    paso es `cancha.duracion_turno_min`.

    Una reserva que no cae en la grilla —un torneo de tres horas que arranca a
    las 17:20— **igual aparece**: se dibuja sobre los casilleros que toca.
    Alinear la vista a la grilla escondería reservas reales, que es peor que una
    fila despareja.

    🔑 **Y una reserva que quedó FUERA de todo horario también aparece**, como
    casillero propio al final. Pasa apenas alguien achica el horario de un
    complejo que ya venía trabajando: las reservas viejas de las 7 de la mañana
    no dejan de existir porque ahora se abra a las 9. Esconderlas sería la peor
    versión del cambio — el turno sigue vendido y nadie lo ve.
    """
    intervalos = horarios.franjas_del_dia(sesion, cancha, dia)
    # Los del día anterior, para saber si una reserva de la madrugada ya quedó
    # dibujada en la grilla de ayer: un complejo que cierra a las 02:00 tiene su
    # jornada del viernes terminando el sábado, y el turno de las 00:30 pertenece
    # al viernes. Sin esto se dibujaría dos veces.
    de_ayer = horarios.franjas_del_dia(sesion, cancha, dia - timedelta(days=1))

    inicio_dia = datetime.combine(dia, time(0, 0), tzinfo=TZ)
    fin_dia = _fin_del_dia(dia)
    desde = min([inicio_dia, *(i for i, _ in intervalos)])
    hasta = max([fin_dia, *(f for _, f in intervalos)])

    reservas = list(
        sesion.scalars(
            select(Reserva)
            .where(
                Reserva.cancha_id == cancha.id,
                Reserva.estado.in_(ESTADOS_QUE_OCUPAN),
                Reserva.comienza_at < hasta,
                Reserva.termina_at > desde,
            )
            .order_by(Reserva.comienza_at)
        ).all()
    )

    turnos: list[Turno] = []
    dibujadas: set[int] = set()
    paso = timedelta(minutes=cancha.duracion_turno_min)

    for comienzo, fin in intervalos:
        momento = comienzo
        while momento + paso <= fin:
            termina = momento + paso
            ocupa = next(
                (r for r in reservas if r.comienza_at < termina and r.termina_at > momento),
                None,
            )
            if ocupa is not None:
                dibujadas.add(ocupa.id)
                turnos.append(_ocupado(ocupa, momento, termina))
            else:
                turnos.append(
                    Turno(
                        comienza_at=momento,
                        termina_at=termina,
                        libre=True,
                        precio=_precio(sesion, cancha, momento) if con_precio else None,
                    )
                )
            momento = termina

    for reserva in reservas:
        if reserva.id in dibujadas:
            continue
        if a_local(reserva.comienza_at).date() != dia:
            continue
        # Si alguna franja de ayer la contiene, ya se dibujó en la grilla de ayer.
        if any(i <= reserva.comienza_at and reserva.termina_at <= f for i, f in de_ayer):
            continue
        turnos.append(_ocupado(reserva, reserva.comienza_at, reserva.termina_at))

    turnos.sort(key=lambda t: t.comienza_at)
    return turnos


def _ocupado(reserva: Reserva, comienza_at: datetime, termina_at: datetime) -> Turno:
    return Turno(
        comienza_at=comienza_at,
        termina_at=termina_at,
        libre=False,
        reserva_id=reserva.id,
        estado=reserva.estado,
        cliente=reserva.cliente.nombre if reserva.cliente else None,
        motivo=reserva.motivo,
    )


def _precio(sesion: Session, cancha: Cancha, momento: datetime) -> Decimal | None:
    try:
        precio, _ = tarifario.precio_y_sena(sesion, cancha, momento)
    except tarifario.SinTarifa:
        # Un turno sin tarifa **se muestra igual, sin precio**. Si se escondiera,
        # la franja sin precio cargado sería invisible y nadie se enteraría de
        # que falta cargarla.
        return None
    return precio


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
