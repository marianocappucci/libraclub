"""Alta, cancelación, bloqueo y series de reservas.

La regla que ordena este módulo: **la aplicación valida para dar un mensaje
útil; la base garantiza que no se pise nada**. Las dos cosas, no una.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from libragenda.recurrence import RecurrenceRule, generate_occurrences
from libragenda.scheduling import intervals_overlap
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import ESTADOS_QUE_OCUPAN, EstadoReserva, OrigenReserva
from app.models.maestros import Cancha
from app.models.reservas import Reserva, Serie
from app.servicios import horarios, tarifario
from app.tiempo import TZ, a_local, ahora

#: Cuánto vive una reserva provisoria sin confirmarse. Entra en juego de verdad
#: en F2, con el portal: es lo que impide que un carrito abandonado deje muerto
#: el turno de las 20:00 de un viernes.
VENCIMIENTO_PROVISORIA = timedelta(minutes=15)

#: Hasta dónde se materializan las ocurrencias de una serie sin fin. Se
#: materializa una ventana y se extiende, en vez de generar infinitas filas: una
#: cancha fija "hasta que avise" no puede ocupar la agenda del año 2100.
HORIZONTE_SERIE = timedelta(days=90)


class ReservaInvalida(ValueError):
    """El pedido está mal formado: termina antes de empezar, cancha inactiva."""


class FueraDelHorario(ValueError):
    """La reserva cae fuera del horario de atención de la cancha.

    Hereda de `ValueError` igual que `ReservaInvalida` —es un pedido que el
    modelo rechaza, no un choque con otra reserva—, pero es su propia clase
    porque el router la traduce a un 422 con un mensaje que nombra el horario.
    """


class Superpuesta(Exception):
    """Ya hay algo en esa cancha a esa hora.

    Llega por dos caminos distintos y **los dos importan**: el chequeo previo de
    la aplicación (el caso normal, con buen mensaje) y el `IntegrityError` del
    constraint de exclusión (el caso concurrente, el que la aplicación no puede
    ver). Que sea la misma excepción es a propósito: el que la atrapa no tiene
    por qué saber cuál de los dos fue.
    """


class TransicionInvalida(Exception):
    """Ese estado no se puede alcanzar desde donde está la reserva."""


#: El nombre de la constraint, tal cual está en el modelo y en la migración.
#: 🔴 Se compara contra esto y **no se hace `grep` sobre el texto del error**: el
#: mensaje de PostgreSQL cambia entre versiones y se traduce con el locale del
#: servidor. Un `if "overlap" in str(exc)` funciona en el runner en inglés y deja
#: de funcionar en un servidor en español, devolviendo un 500 donde iba un 409.
CONSTRAINT_SUPERPOSICION = "ex_reservas_sin_superposicion"


def _es_superposicion(exc: IntegrityError) -> bool:
    original = getattr(exc, "orig", None)
    diag = getattr(original, "diag", None)
    return getattr(diag, "constraint_name", None) == CONSTRAINT_SUPERPOSICION


def ocupadas(
    sesion: Session, cancha_id: int, desde: datetime, hasta: datetime
) -> list[Reserva]:
    """Las reservas que ocupan esa cancha y tocan ese rango."""
    return list(
        sesion.scalars(
            select(Reserva).where(
                Reserva.cancha_id == cancha_id,
                Reserva.estado.in_(ESTADOS_QUE_OCUPAN),
                Reserva.comienza_at < hasta,
                Reserva.termina_at > desde,
            )
        ).all()
    )


def _verificar_libre(
    sesion: Session, cancha_id: int, comienza_at: datetime, termina_at: datetime,
    excluir_id: int | None = None,
) -> None:
    """Chequeo previo, **para el mensaje**. La garantía es el constraint.

    Se usa `intervals_overlap` de LibraGenda en vez de reescribir la comparación:
    es la misma regla semiabierta que expresa el `tstzrange` `[)`, y tenerla en
    un solo lugar evita que la aplicación y la base opinen distinto sobre el
    turno que termina justo cuando empieza el otro.
    """
    for otra in ocupadas(sesion, cancha_id, comienza_at, termina_at):
        if otra.id == excluir_id:
            continue
        if intervals_overlap(comienza_at, termina_at, otra.comienza_at, otra.termina_at):
            inicio = a_local(otra.comienza_at).strftime("%H:%M")
            fin = a_local(otra.termina_at).strftime("%H:%M")
            que = "un bloqueo" if otra.estado is EstadoReserva.BLOQUEO else "una reserva"
            raise Superpuesta(
                f"La cancha ya tiene {que} de {inicio} a {fin} ese día."
            )


def _guardar(sesion: Session, reserva: Reserva) -> Reserva:
    """Persiste traduciendo el choque del constraint.

    El `flush` es lo que hace llegar el `INSERT` a la base **acá** y no en el
    commit de más arriba: sin él, la violación del constraint explota fuera de
    este módulo, ya sin contexto para traducirla, y sale un 500.

    🔴 Y va adentro de un **SAVEPOINT**, no de un `try` a secas. Después de un
    `IntegrityError` PostgreSQL deja la transacción abortada: todo lo que se
    intente después falla con `InFailedSqlTransaction` hasta que alguien
    deshaga. Un `sesion.rollback()` deshace **toda** la transacción — y eso, en
    una serie de trece martes donde el tercero choca, se lleva puestos los dos
    que ya se habían creado y devuelve "no se pudo crear la serie" cuando se
    podían crear doce.
    """
    punto = sesion.begin_nested()
    try:
        sesion.add(reserva)
        sesion.flush()
    except IntegrityError as exc:
        punto.rollback()
        if _es_superposicion(exc):
            raise Superpuesta(
                "Alguien tomó esa cancha a esa hora mientras cargabas la reserva."
            ) from exc
        raise
    punto.commit()
    return reserva


def _verificar_dentro_del_horario(
    sesion: Session, cancha: Cancha, comienza_at: datetime, termina_at: datetime
) -> None:
    """Una reserva fuera del horario de atención no entra.

    🔴 **Que la grilla no lo ofrezca no alcanza.** La pantalla dibuja sólo los
    casilleros de las franjas abiertas, pero la API sigue tomando cualquier
    `comienza_at`: sin esta guarda, una reserva de las 4 de la mañana entra por
    `POST /api/reservas` y después aparece en la grilla como turno huérfano.

    El mensaje dice **qué horario rige ese día**, no sólo que está mal: el
    encargado que se equivocó de día necesita saber a qué hora sí puede.

    Los **bloqueos no pasan por acá** a propósito: son del complejo, no de un
    cliente, y el mantenimiento de las 6 de la mañana es justamente lo que se
    hace con el lugar cerrado.
    """
    if horarios.esta_abierto(sesion, cancha, comienza_at, termina_at):
        return
    dia = a_local(comienza_at).date()
    raise FueraDelHorario(
        f"{cancha.nombre} no atiende en ese horario: el "
        f"{dia:%d-%m-%Y} abre {horarios.texto_del_horario(sesion, cancha, dia)}."
    )


def crear(
    sesion: Session,
    *,
    cancha_id: int,
    cliente_id: int,
    comienza_at: datetime,
    duracion_min: int | None = None,
    estado: EstadoReserva = EstadoReserva.CONFIRMADA,
    origen: OrigenReserva = OrigenReserva.MOSTRADOR,
    precio: Decimal | None = None,
    serie_id: int | None = None,
    observaciones: str | None = None,
) -> Reserva:
    """Una reserva nueva. El precio se congela ahora, no se resuelve al leer."""
    cancha = sesion.get(Cancha, cancha_id)
    if cancha is None:
        raise ReservaInvalida("No existe esa cancha.")
    if not cancha.activa:
        raise ReservaInvalida(f"La cancha {cancha.nombre} está dada de baja.")

    minutos = duracion_min or cancha.duracion_turno_min
    if minutos <= 0:
        raise ReservaInvalida("La duración tiene que ser positiva.")
    termina_at = comienza_at + timedelta(minutes=minutos)

    _verificar_dentro_del_horario(sesion, cancha, comienza_at, termina_at)
    _verificar_libre(sesion, cancha_id, comienza_at, termina_at)

    if precio is None:
        precio, sena = tarifario.precio_y_sena(sesion, cancha, comienza_at)
    else:
        # Precio a mano: no se inventa una seña sobre un número que el operador
        # eligió. Si hace falta seña sobre un precio manual, se pide explícita.
        sena = None

    return _guardar(
        sesion,
        Reserva(
            cancha_id=cancha_id,
            cliente_id=cliente_id,
            serie_id=serie_id,
            estado=estado,
            origen=origen,
            comienza_at=comienza_at,
            termina_at=termina_at,
            precio=precio,
            sena=sena,
            vence_at=(
                ahora() + VENCIMIENTO_PROVISORIA
                if estado is EstadoReserva.PROVISORIA
                else None
            ),
            observaciones=observaciones,
        ),
    )


def crear_bloqueo(
    sesion: Session,
    *,
    cancha_id: int,
    comienza_at: datetime,
    termina_at: datetime,
    motivo: str,
) -> Reserva:
    """Mantenimiento, torneo, lluvia. Sin cliente y sin precio.

    Va a la misma tabla que las reservas para que el constraint de exclusión lo
    cubra en las dos direcciones: un bloqueo no se puede poner encima de una
    reserva, y una reserva no se puede poner encima de un bloqueo.
    """
    if termina_at <= comienza_at:
        raise ReservaInvalida("El bloqueo tiene que terminar después de empezar.")
    if not motivo.strip():
        raise ReservaInvalida("Un bloqueo necesita motivo: alguien va a preguntar.")

    _verificar_libre(sesion, cancha_id, comienza_at, termina_at)
    return _guardar(
        sesion,
        Reserva(
            cancha_id=cancha_id,
            cliente_id=None,
            estado=EstadoReserva.BLOQUEO,
            origen=OrigenReserva.MOSTRADOR,
            comienza_at=comienza_at,
            termina_at=termina_at,
            motivo=motivo.strip(),
        ),
    )


#: Desde qué estado se puede ir a cuál. Explícito, para que "cancelar una reserva
#: ya jugada" sea un 409 y no una fila que descuadra el reporte del mes pasado.
TRANSICIONES: dict[EstadoReserva, frozenset[EstadoReserva]] = {
    EstadoReserva.PROVISORIA: frozenset(
        {EstadoReserva.PENDIENTE_PAGO, EstadoReserva.CONFIRMADA, EstadoReserva.CANCELADA}
    ),
    EstadoReserva.PENDIENTE_PAGO: frozenset(
        {EstadoReserva.CONFIRMADA, EstadoReserva.CANCELADA}
    ),
    EstadoReserva.CONFIRMADA: frozenset(
        {EstadoReserva.JUGADA, EstadoReserva.AUSENTE, EstadoReserva.CANCELADA}
    ),
    EstadoReserva.JUGADA: frozenset(),
    EstadoReserva.CANCELADA: frozenset(),
    EstadoReserva.AUSENTE: frozenset(),
    EstadoReserva.BLOQUEO: frozenset({EstadoReserva.CANCELADA}),
}


def cambiar_estado(
    sesion: Session, reserva_id: int, nuevo: EstadoReserva, motivo: str | None = None
) -> Reserva:
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None:
        raise ReservaInvalida("No existe esa reserva.")
    if nuevo not in TRANSICIONES[reserva.estado]:
        raise TransicionInvalida(
            f"Una reserva {reserva.estado.value} no puede pasar a {nuevo.value}."
        )
    reserva.estado = nuevo
    if motivo:
        reserva.motivo = motivo
    if nuevo is not EstadoReserva.PROVISORIA:
        reserva.vence_at = None
    sesion.flush()
    return reserva


def vencer_provisorias(sesion: Session, momento: datetime | None = None) -> int:
    """Cancela las provisorias que pasaron su `vence_at`. Devuelve cuántas.

    Es un `UPDATE` masivo y no un bucle: son filas que ya nadie mira, y traerlas
    a Python para cancelarlas de a una sólo agrega tiempo entre el vencimiento y
    la liberación del turno — que es exactamente lo que no se quiere.
    """
    corte = momento or ahora()
    resultado = sesion.execute(
        update(Reserva)
        .where(
            Reserva.estado == EstadoReserva.PROVISORIA,
            Reserva.vence_at.is_not(None),
            Reserva.vence_at <= corte,
        )
        .values(estado=EstadoReserva.CANCELADA, motivo="Vencida sin confirmar", vence_at=None)
    )
    return int(resultado.rowcount or 0)


def materializar_serie(
    sesion: Session, serie: Serie, hasta: date | None = None
) -> tuple[list[Reserva], list[datetime]]:
    """Genera las reservas de una cancha fija. Devuelve (creadas, salteadas).

    **Una ocurrencia que choca no aborta la serie**: se saltea y se informa. Una
    cancha fija de los martes con un torneo el tercer martes tiene que dejar las
    otras doce; abortar entera obligaría al operador a cargarlas a mano.

    Lo que hace eso posible es el `SAVEPOINT` de `_guardar`, no un `try` acá: sin
    savepoint, el `IntegrityError` de la que choca deja la transacción abortada y
    todas las siguientes fallan también.
    """
    tope = hasta or (a_local(ahora()).date() + HORIZONTE_SERIE)
    if serie.hasta is not None:
        tope = min(tope, serie.hasta)

    regla = RecurrenceRule(
        weekdays=frozenset({serie.dia_semana}),
        start_time=serie.hora,
        starts_on=serie.desde,
        until=tope,
    )

    creadas: list[Reserva] = []
    salteadas: list[datetime] = []
    for ocurrencia in generate_occurrences(regla):
        # 🔴 `generate_occurrences` devuelve datetimes **naive**: hace
        # `datetime.combine(fecha, hora)` y no le pone zona. Guardarlos así deja
        # que psycopg los interprete como UTC, y la cancha fija de las 20:00
        # aparece a las 17:00 en la grilla.
        comienza_at = ocurrencia.replace(tzinfo=TZ)
        try:
            creadas.append(
                crear(
                    sesion,
                    cancha_id=serie.cancha_id,
                    cliente_id=serie.cliente_id,
                    comienza_at=comienza_at,
                    duracion_min=serie.duracion_min,
                    origen=OrigenReserva.SERIE,
                    serie_id=serie.id,
                )
            )
        except (Superpuesta, tarifario.SinTarifa):
            # Las dos son "esta fecha no se puede, las demás sí". `SinTarifa`
            # además es frecuente y esperable: una serie que cruza el cambio de
            # temporada llega a semanas sin precio cargado.
            salteadas.append(comienza_at)
    return creadas, salteadas
