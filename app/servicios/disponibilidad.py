"""La grilla: qué hay y qué queda libre en una cancha, día por día."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ESTADOS_QUE_OCUPAN, EstadoReserva
from app.models.maestros import Cancha
from app.models.reservas import Reserva
from app.servicios import buffet as servicio_buffet
from app.servicios import caja as servicio_caja
from app.servicios import facturacion as servicio_facturacion
from app.servicios import horarios, tarifario
from app.tiempo import TZ, a_local


@dataclass(frozen=True, slots=True)
class Turno:
    """Un casillero de la grilla."""

    comienza_at: datetime
    termina_at: datetime
    libre: bool
    precio: Decimal | None = None
    #: El precio sin promoción, **sólo cuando hay una** (ADR-029); `None` si el turno cuesta lo de la
    #: tarifa. Es lo que el portal tacha. Va con `promocion`, que es la que la nombra.
    precio_lista: Decimal | None = None
    promocion: str | None = None
    reserva_id: int | None = None
    estado: EstadoReserva | None = None
    cliente: str | None = None
    motivo: str | None = None
    #: Hasta cuándo se retiene el turno esperando el pago: la provisoria del portal o la seña de la
    #: `pendiente_pago` del mostrador (24 h). `None` si no vence (o la `pendiente_pago` es anterior
    #: al plazo). Es lo que la agenda y el detalle le muestran al mostrador.
    vence_at: datetime | None = None
    #: Si este turno ya no debe nada. Lo estampa `marcar_cobrados`, no la
    #: grilla: el dato vive en la base de LibraCore y averiguarlo por casillero
    #: sería una conexión por celda.
    cobrado: bool = False
    #: En qué punto de pago está: `cobrado` (no debe nada), `senado` (entró algo
    #: y falta) o `pendiente` (no entró nada). `None` si el turno no tiene total
    #: —un bloqueo, o una franja sin tarifa— o no se averiguó. Lo estampa
    #: `marcar_cobrados`, con el mismo lote que `cobrado`.
    cobro: str | None = None
    #: Lo que falta cobrar del turno. `None` cuando `cobro` es `None`.
    saldo: Decimal | None = None


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
                cotizacion = _cotizar(sesion, cancha, momento) if con_precio else None
                promo = cotizacion.promocion if cotizacion else None
                turnos.append(
                    Turno(
                        comienza_at=momento,
                        termina_at=termina,
                        libre=True,
                        precio=cotizacion.precio if cotizacion else None,
                        precio_lista=cotizacion.precio_lista if promo else None,
                        promocion=promo.nombre if promo else None,
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
        vence_at=reserva.vence_at,
    )


def _cotizar(
    sesion: Session, cancha: Cancha, momento: datetime
) -> tarifario.Cotizacion | None:
    try:
        return tarifario.cotizar(sesion, cancha, momento)
    except tarifario.SinTarifa:
        # Un turno sin tarifa **se muestra igual, sin precio**. Si se escondiera,
        # la franja sin precio cargado sería invisible y nadie se enteraría de
        # que falta cargarla.
        return None


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


COBRADO = "cobrado"
SENADO = "senado"
PENDIENTE = "pendiente"


@dataclass(frozen=True, slots=True)
class CobroDeReserva:
    """Cuánto falta cobrar de una reserva y en qué punto de pago está."""

    estado: str
    saldo: Decimal


def cobros_de_reservas(sesion: Session, reserva_ids: Iterable[int]) -> dict[int, CobroDeReserva]:
    """De esas reservas, en qué punto de pago está cada una — alquiler más buffet.

    🔑 **Se pregunta por todas juntas y por eso recibe una colección.** Los dos
    totales salen de la base de LibraCore, que abre y cierra una conexión por
    consulta: la semana de un complejo de seis canchas son cientos de
    casilleros, y preguntar por cada uno sería el mismo error que ya tenían el
    listado del mostrador y el buffet antes de sus versiones por lote.

    Tres estados, que son los que el operador distingue de un vistazo:
    `cobrado` (entró todo), `senado` (entró algo y falta) y `pendiente` (no
    entró nada). La cuenta es la de siempre —`cobrado >= total`—; lo nuevo es no
    tirar a la basura el «entró algo».

    🔴 **Un turno sin tarifa NO está saldado, está sin precio**, y por eso no
    figura en el resultado. Con total cero, `cobrado >= total` da verdadero sin
    que haya entrado un peso: la grilla marcaría como cobrada toda franja a la
    que le falta cargar el precio, que es justo la que hay que ir a mirar. Un
    bloqueo, que tampoco tiene total, queda afuera por lo mismo.

    ⚠️ **Sin base de LibraCore devuelve vacío, y la agenda anda igual.** La caja
    vive del lado del motor; una instancia que todavía no la configuró tiene que
    poder ver su agenda. Acá no corresponde el 503 del mostrador: allá la caja
    *es* la pantalla, y acá es una marca sobre el casillero.
    """
    ids = sorted({int(x) for x in reserva_ids})
    if not ids or not servicio_facturacion.hay_base():
        return {}

    precios = dict(
        sesion.execute(select(Reserva.id, Reserva.precio).where(Reserva.id.in_(ids))).all()
    )
    consumido = servicio_buffet.consumido_de_reservas(ids)
    cobrado = servicio_caja.cobrado_de_reservas(ids)

    resultado: dict[int, CobroDeReserva] = {}
    for reserva_id in ids:
        # Mismo total que `/agenda/por-cobrar` y que el comprobante: alquiler más
        # buffet. Con `reserva.precio` a secas, un turno con tres gaseosas sin
        # cobrar se dibujaría como saldado.
        total = Decimal(str(precios.get(reserva_id) or 0))
        total += consumido.get(reserva_id, Decimal("0"))
        if total <= 0:
            continue
        entro = cobrado.get(reserva_id, Decimal("0"))
        if entro >= total:
            resultado[reserva_id] = CobroDeReserva(COBRADO, Decimal("0"))
        elif entro > 0:
            resultado[reserva_id] = CobroDeReserva(SENADO, total - entro)
        else:
            resultado[reserva_id] = CobroDeReserva(PENDIENTE, total)
    return resultado


def reservas_saldadas(sesion: Session, reserva_ids: Iterable[int]) -> set[int]:
    """De esas reservas, las que ya no deben nada. Ver `cobros_de_reservas`."""
    return {
        reserva_id
        for reserva_id, cobro in cobros_de_reservas(sesion, reserva_ids).items()
        if cobro.estado == COBRADO
    }


def con_cobro(turno: Turno, cobros: dict[int, CobroDeReserva]) -> Turno:
    """El casillero con su punto de pago estampado (`cobrado`, `cobro` y `saldo`)."""
    cobro = cobros.get(turno.reserva_id) if turno.reserva_id is not None else None
    if cobro is None:
        return turno
    return replace(turno, cobrado=cobro.estado == COBRADO, cobro=cobro.estado, saldo=cobro.saldo)


def marcar_cobrados(sesion: Session, turnos: Sequence[Turno]) -> list[Turno]:
    """`cobros_de_reservas` aplicado a una lista de casilleros, en un solo lote.

    Una reserva larga ocupa varios casilleros y **todos** reciben la misma
    marca: es lo que se quiere ver en la grilla.
    """
    cobros = cobros_de_reservas(
        sesion, (t.reserva_id for t in turnos if t.reserva_id is not None)
    )
    return [con_cobro(turno, cobros) for turno in turnos]


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
