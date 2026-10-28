"""Alta, cancelación, bloqueo y series de reservas.

La regla que ordena este módulo: **la aplicación valida para dar un mensaje
útil; la base garantiza que no se pise nada**. Las dos cosas, no una.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from libragenda.recurrence import RecurrenceRule, generate_occurrences
from libragenda.scheduling import intervals_overlap
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.enums import ESTADOS_QUE_OCUPAN, EstadoReserva, OrigenReserva
from app.models.maestros import Cancha
from app.models.reservas import EstadoPago, PagoDeReserva, Reserva, Serie
from app.servicios import caja as servicio_caja
from app.servicios import facturacion as servicio_facturacion
from app.servicios import horarios, reservas_nodo, tarifario
from app.tiempo import TZ, a_local, ahora

logger = logging.getLogger(__name__)

#: Cuánto vive una reserva provisoria sin confirmarse. Entra en juego de verdad
#: en F2, con el portal: es lo que impide que un carrito abandonado deje muerto
#: el turno de las 20:00 de un viernes.
VENCIMIENTO_PROVISORIA = timedelta(minutes=15)

#: Cuánto tiene quien reservó **por teléfono o en el mostrador** (`pendiente_pago`) para pagar la
#: seña, contado desde que se tomó el turno (decisión del humano, 2026-10-28, ADR-029).
#:
#: Es otra regla que la de arriba y no una versión larga de ella: la provisoria del portal es un
#: carrito con la tarjeta en la mano (15 minutos); ésta es una promesa que se cumple con una
#: transferencia o pasando por el local, y a eso se le da un día.
PLAZO_DE_SENA = timedelta(hours=24)

#: Con cuánta anticipación al turno tiene que estar paga la seña, como mínimo. Un turno de mañana
#: a las 09:00 no puede seguir retenido hasta las 09:00 de hoy+24 h: el complejo lo liberaría con el
#: partido por empezar y nadie lo podría revender. Dos horas es lo que el complejo necesita para
#: ofrecerlo de nuevo y es la misma anticipación del segundo recordatorio (`avisos.ANTICIPACIONES`).
MARGEN_DE_SENA_ANTES_DEL_TURNO = timedelta(hours=2)

#: Lo mínimo que se le da a quien reserva sobre la hora. Si el turno es dentro de 1 hora, «dos horas
#: antes» ya pasó: sin un piso la reserva nacería vencida y el cron la liberaría a los 5 minutos,
#: antes de que el mostrador termine de cortar el teléfono.
PLAZO_MINIMO_DE_SENA = timedelta(minutes=30)

MOTIVO_SENA_VENCIDA = "Vencida sin seña"

#: Hasta dónde se materializan las ocurrencias de una serie sin fin. Se
#: materializa una ventana y se extiende, en vez de generar infinitas filas: una
#: cancha fija "hasta que avise" no puede ocupar la agenda del año 2100.
HORIZONTE_SERIE = timedelta(days=90)


def vencimiento_de_sena(tomada_at: datetime, comienza_at: datetime) -> datetime | None:
    """Hasta cuándo tiene el jugador para pagar la seña de un turno tomado por teléfono o en el mostrador.

    🔑 **La regla, en una línea: 24 horas desde que se tomó, pero nunca más tarde que 2 horas antes
    del turno.** Con las dos salvedades que hacen que no se rompa en los bordes:

    - **Piso de 30 minutos.** Si el turno es sobre la hora, «2 horas antes» ya pasó; la reserva no
      nace vencida: se le da media hora (y como mucho hasta el inicio del turno, que es el techo
      absoluto: el vencimiento nunca queda después del turno).
    - **Un turno que ya empezó no tiene plazo (`None`).** Es el mostrador cargando algo que ya pasó
      —o que está pasando—; vencerlo sería cancelar un partido que se está jugando.

    Es una función pura de las dos horas. La usan `crear` (el mostrador y el nodo) y el central
    cuando aplica un `reserva.creada` de LibraEdge, que la calcula con la hora en que el nodo tomó
    la reserva: el vencimiento lo decide el central y es **el mismo** lo haya tomado la web o un nodo.
    """
    if comienza_at <= tomada_at:
        return None
    vence = min(tomada_at + PLAZO_DE_SENA, comienza_at - MARGEN_DE_SENA_ANTES_DEL_TURNO)
    vence = max(vence, tomada_at + PLAZO_MINIMO_DE_SENA)
    return min(vence, comienza_at)


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


#: Los nombres de las constraints, tal cual están en el modelo y en la migración.
#: 🔴 Se comparan contra esto y **no se hace `grep` sobre el texto del error**: el
#: mensaje de PostgreSQL cambia entre versiones y se traduce con el locale del
#: servidor. Un `if "overlap" in str(exc)` funciona en el runner en inglés y deja
#: de funcionar en un servidor en español, devolviendo un 500 donde iba un 409.
#:
#: Son dos desde la `0013` (ADR-022): la exclusión está partida por el signo del
#: id, la del central (`id > 0`) y la de lo que se da en un nodo (`id < 0`).
CONSTRAINT_SUPERPOSICION = "ex_reservas_sin_superposicion"
CONSTRAINT_SUPERPOSICION_DEL_NODO = "ex_reservas_del_nodo_sin_superposicion"
_CONSTRAINTS_DE_SUPERPOSICION = (CONSTRAINT_SUPERPOSICION, CONSTRAINT_SUPERPOSICION_DEL_NODO)


def _es_superposicion(exc: IntegrityError) -> bool:
    original = getattr(exc, "orig", None)
    diag = getattr(original, "diag", None)
    return getattr(diag, "constraint_name", None) in _CONSTRAINTS_DE_SUPERPOSICION


#: SQLSTATE `deadlock_detected`. Por código y no por el texto del mensaje, por la
#: misma razón que `CONSTRAINT_SUPERPOSICION`: el texto se traduce con el locale.
SQLSTATE_DEADLOCK = "40P01"


def _es_deadlock(exc: OperationalError) -> bool:
    return getattr(getattr(exc, "orig", None), "sqlstate", None) == SQLSTATE_DEADLOCK


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
    # 🔴 **Dos `INSERT` simultáneos del mismo turno pueden dar `DeadlockDetected`
    # y no el `IntegrityError` del constraint.** El de exclusión inserta primero
    # la fila y el índice y recién después busca conflictos: si las dos
    # transacciones llegaron a insertar antes de que cualquiera mirara, cada una
    # ve la fila sin commitear de la otra y se queda esperando que termine. Es
    # un ciclo, y a 1 s (`deadlock_timeout`) PostgreSQL mata a una con 40P01.
    # Medido: ~13 % de las veces con dos hilos pegados. La otra sigue y gana, así
    # que **no hay doble reserva**; lo que se rompía era el perdedor, que salía
    # como `OperationalError` (un 500) en vez de "alguien tomó esa cancha" (409).
    #
    # Se reintenta **una vez** y no se traduce directo a `Superpuesta`: el
    # deadlock no dice si la otra transacción va a commitear o a deshacer. Al
    # reintentar, el `INSERT` espera a que la ganadora termine y entonces o
    # choca contra el constraint (`Superpuesta`, el caso de siempre) o entra,
    # porque el turno de verdad quedó libre.
    for intento in (1, 2):
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
        except OperationalError as exc:
            punto.rollback()
            if _es_deadlock(exc) and intento == 1:
                continue
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
    con_promocion: bool = True,
) -> Reserva:
    """Una reserva nueva. El precio se congela ahora, no se resuelve al leer.

    `con_promocion=False` cotiza al precio de lista: es lo que piden las series (los turnos fijos no
    llevan promoción ni hora valle). El mostrador y el portal siguen con ella.

    Una `pendiente_pago` nace con su vencimiento (`vencimiento_de_sena`): la seña tiene plazo.

    🔑 **En un nodo de LibraEdge** (ADR-022) la reserva nace con un **id provisorio negativo** y la operación
    `reserva.creada` se encola en la misma transacción; el central le asigna el definitivo y, si chocó con otra
    que llegó antes, la deja `en_conflicto`. Fuera de un nodo no cambia nada."""
    en_el_nodo = reservas_nodo.en_un_nodo()
    if en_el_nodo and serie_id is not None:
        reservas_nodo.exigir_central()
    if en_el_nodo and estado not in reservas_nodo.ESTADOS_DEL_NODO:
        raise ReservaInvalida("Sin conexión sólo se dan reservas confirmadas o pendientes de pago.")
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
        precio, sena = tarifario.precio_y_sena(
            sesion, cancha, comienza_at, con_promocion=con_promocion
        )
    else:
        # Precio a mano: no se inventa una seña sobre un número que el operador
        # eligió. Si hace falta seña sobre un precio manual, se pide explícita.
        sena = None

    reserva = Reserva(
        cancha_id=cancha_id,
        cliente_id=cliente_id,
        serie_id=serie_id,
        estado=estado,
        origen=origen,
        comienza_at=comienza_at,
        termina_at=termina_at,
        precio=precio,
        sena=sena,
        vence_at=_vencimiento_al_crear(estado, comienza_at),
        observaciones=observaciones,
    )
    if not en_el_nodo:
        return _guardar(sesion, reserva)

    conn = reservas_nodo.conexion_de_la_sesion(sesion)
    reserva.id = reservas_nodo.siguiente_id(conn)
    _guardar(sesion, reserva)
    reservas_nodo.avisar_creada(conn, reserva)
    return reserva


def _vencimiento_al_crear(estado: EstadoReserva, comienza_at: datetime) -> datetime | None:
    """El `vence_at` con el que nace una reserva: el de la provisoria del portal, el de la seña del
    mostrador, o ninguno (una confirmada no vence)."""
    if estado is EstadoReserva.PROVISORIA:
        return ahora() + VENCIMIENTO_PROVISORIA
    if estado is EstadoReserva.PENDIENTE_PAGO:
        return vencimiento_de_sena(ahora(), comienza_at)
    return None


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
    # En un nodo el id saldría de la secuencia local y chocaría con los del central (ADR-022).
    reservas_nodo.exigir_central()
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
    # Desde un conflicto sólo se cancela por acá. Volver a confirmarla pide verificar que la cancha esté libre y es
    # `servicios/conflictos.resolver`; a `en_conflicto` no llega nadie por acá (lo pone el aplicador del central).
    EstadoReserva.EN_CONFLICTO: frozenset({EstadoReserva.CANCELADA}),
}


def cambiar_estado(
    sesion: Session, reserva_id: int, nuevo: EstadoReserva, motivo: str | None = None
) -> Reserva:
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None:
        raise ReservaInvalida("No existe esa reserva.")
    # Antes de todo, y antes de que cancelar toque la plata: en un nodo, lo que no se dio acá espera a la conexión.
    reservas_nodo.exigir_reserva_modificable(reserva.id)
    if nuevo not in TRANSICIONES[reserva.estado]:
        raise TransicionInvalida(
            f"Una reserva {reserva.estado.value} no puede pasar a {nuevo.value}."
        )
    reserva.estado = nuevo
    if motivo:
        reserva.motivo = motivo
    if nuevo is EstadoReserva.PENDIENTE_PAGO:
        # Una provisoria que el mostrador pasa a «pendiente de pago»: la seña tiene su plazo desde ahora.
        reserva.vence_at = vencimiento_de_sena(ahora(), reserva.comienza_at)
    elif nuevo is not EstadoReserva.PROVISORIA:
        reserva.vence_at = None
    # Sale de un conflicto: ya no hay contra qué chocó ni a qué volver.
    reserva.conflicto_con_id = None
    reserva.estado_previo = None
    sesion.flush()
    if reservas_nodo.en_un_nodo() and reservas_nodo.es_del_nodo(reserva.id):
        reservas_nodo.avisar_estado(
            reservas_nodo.conexion_de_la_sesion(sesion), reserva.id, nuevo, motivo
        )
    return reserva


def vencer_provisorias(sesion: Session, momento: datetime | None = None) -> int:
    """Libera los turnos retenidos que pasaron su `vence_at`. Devuelve cuántos.

    Son **dos** cosas con el mismo final (`cancelada`, el turno vuelve a la grilla):

    - las **provisorias** del portal, que nadie pagó en `VENCIMIENTO_PROVISORIA`;
    - las **`pendiente_pago` del mostrador** (teléfono, local) cuya seña no llegó en
      `PLAZO_DE_SENA` — `vencer_senas_del_mostrador`, que antes de soltar una mira si entró plata.

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
    return int(resultado.rowcount or 0) + vencer_senas_del_mostrador(sesion, corte)


def cobrado_en_caja(reserva_ids: Iterable[int]) -> dict[int, Decimal]:
    """Cuánto entró en la caja por cada reserva (las que no tienen cobros no figuran).

    Una instancia que no lleva caja contra LibraCore (`hay_base()` falso) no tiene dónde haber
    cobrado nada: devuelve vacío. Si la caja existe y falla, **levanta** (ver `con_plata_adentro`).
    """
    ids = sorted({int(i) for i in reserva_ids})
    if not ids or not servicio_facturacion.hay_base():
        return {}
    return servicio_caja.cobrado_de_reservas(ids)


def con_plata_adentro(sesion: Session, reserva_ids: Iterable[int]) -> set[int]:
    """De esas reservas, las que **ya tienen plata**: un pago aprobado o un cobro en la caja.

    Es lo que decide que una seña vencida no se libere sola. Se mira lo **cobrado** y no que la
    seña esté completa, a propósito: una seña a medias (entró la mitad) sigue siendo plata de
    alguien, y cancelar la reserva obligaría a devolverla (`servicios/cancelacion`). Eso lo decide
    una persona, no el cron.

    Si la caja no se puede consultar **no se sabe**, y lo que no se sabe cuenta como que tiene plata
    (por eso levanta): equivocarse para ese lado deja un turno retenido de más hasta la próxima
    corrida; para el otro, libera la cancha de alguien que ya pagó.
    """
    ids = sorted({int(i) for i in reserva_ids})
    if not ids:
        return set()
    cobrado = cobrado_en_caja(ids)
    con_pago = set(
        sesion.scalars(
            select(PagoDeReserva.reserva_id).where(
                PagoDeReserva.reserva_id.in_(ids), PagoDeReserva.estado == EstadoPago.APROBADO
            )
        )
    )
    return con_pago | {i for i, monto in cobrado.items() if monto > 0}


def vencer_senas_del_mostrador(sesion: Session, momento: datetime | None = None) -> int:
    """Libera las `pendiente_pago` cuya seña no llegó a tiempo. Devuelve cuántas.

    🔑 **Mismo final que una provisoria vencida**: `cancelada`, `vence_at` limpio y el turno de
    vuelta en la grilla. Lo que cambia es el motivo («Vencida sin seña») y una guarda más:

    - **Una reserva con plata adentro no se libera** (`con_plata_adentro`). Pasó su plazo, pero la
      seña entró: se le saca el vencimiento y queda `pendiente_pago` para que el mostrador la
      confirme. Cancelarla solo sería quedarse con la plata de alguien que ya pagó.
    - Una `pendiente_pago` **sin** `vence_at` (las anteriores al plazo de 24 h, o las que dio un
      camino que no lo pone) no se toca nunca: no tiene plazo.

    Corre sólo en el central (el cron de `scripts/vencer_provisorias.py`). Un nodo de LibraEdge no
    libera nada: la reserva que se dio ahí sube al central, que le pone el vencimiento y la vence.
    """
    corte = momento or ahora()
    vencidas = list(
        sesion.scalars(
            select(Reserva.id).where(
                Reserva.estado == EstadoReserva.PENDIENTE_PAGO,
                Reserva.vence_at.is_not(None),
                Reserva.vence_at <= corte,
            )
        )
    )
    if not vencidas:
        return 0
    try:
        pagadas = con_plata_adentro(sesion, vencidas)
    except Exception:  # noqa: BLE001 - sin saber si entró plata no se libera nada
        logger.exception("No se pudo consultar la caja: no se vencen las señas del mostrador")
        return 0

    if pagadas:
        sesion.execute(
            update(Reserva)
            .where(Reserva.id.in_(pagadas), Reserva.estado == EstadoReserva.PENDIENTE_PAGO)
            .values(vence_at=None)
        )
    liberar = [i for i in vencidas if i not in pagadas]
    if not liberar:
        return 0
    resultado = sesion.execute(
        update(Reserva)
        .where(
            Reserva.id.in_(liberar),
            Reserva.estado == EstadoReserva.PENDIENTE_PAGO,
            Reserva.vence_at.is_not(None),
            Reserva.vence_at <= corte,
        )
        .values(estado=EstadoReserva.CANCELADA, motivo=MOTIVO_SENA_VENCIDA, vence_at=None)
    )
    return int(resultado.rowcount or 0)


@dataclass(frozen=True, slots=True)
class Salteada:
    """Una ocurrencia de la serie que no se pudo crear, y por qué.

    `motivo` es un código estable para la pantalla —`sin_tarifa`, `ocupada`,
    `fuera_de_horario`— y `detalle` el mensaje que ya arma la excepción, que
    nombra la cancha y el horario del día.
    """

    comienza_at: datetime
    motivo: str
    detalle: str


#: Qué código le corresponde a cada excepción. Es un dict y no una cadena de
#: `isinstance` para que agregar una causa nueva sea una línea acá **y** falle
#: ruidosamente si alguien agrega la excepción al `except` y se olvida del
#: motivo, en vez de mandar un código vacío a la pantalla.
_MOTIVO: dict[type, str] = {
    tarifario.SinTarifa: "sin_tarifa",
    Superpuesta: "ocupada",
    FueraDelHorario: "fuera_de_horario",
}


def materializar_serie(
    sesion: Session, serie: Serie, hasta: date | None = None
) -> tuple[list[Reserva], list[Salteada]]:
    """Genera las reservas de una cancha fija. Devuelve (creadas, salteadas).

    **Una ocurrencia que choca no aborta la serie**: se saltea y se informa. Una
    cancha fija de los martes con un torneo el tercer martes tiene que dejar las
    otras doce; abortar entera obligaría al operador a cargarlas a mano.

    Lo que hace eso posible es el `SAVEPOINT` de `_guardar`, no un `try` acá: sin
    savepoint, el `IntegrityError` de la que choca deja la transacción abortada y
    todas las siguientes fallan también.

    🔑 **Cada salteada dice POR QUÉ.** "Se saltearon 3 de 13" no le sirve al
    encargado: si fue por falta de tarifa carga la tarifa, si fue por horario
    revisa el horario, y si fue por superposición le avisa al cliente. Sin el
    motivo tiene que ir a buscar cada fecha a la grilla.
    """
    # Las ocurrencias de una serie saldrían con ids de la secuencia del nodo (ADR-022).
    reservas_nodo.exigir_central()
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
    salteadas: list[Salteada] = []
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
                    # Los turnos fijos pagan la tarifa, sin hora valle ni promoción (2026-10-28).
                    con_promocion=False,
                )
            )
        except (Superpuesta, tarifario.SinTarifa, FueraDelHorario) as exc:
            # Las tres son "esta fecha no se puede, las demás sí".
            #
            # `SinTarifa` es frecuente y esperable: una serie que cruza el cambio
            # de temporada llega a semanas sin precio cargado.
            #
            # 🔴 **`FueraDelHorario` no estaba en esta lista y la serie abortaba
            # entera.** El `except` cubría las dos excepciones que existían
            # cuando se escribió; la validación de horario nació el 2026-08-21 y
            # esta línea no se enteró. Con el complejo abriendo 09:00 y una serie
            # de los martes a las 07:00, `POST /series` devolvía 422 y no creaba
            # **ninguna** de las trece ocurrencias — ni siquiera las que sí
            # entraban. Verificado contra PostgreSQL antes de tocarlo.
            salteadas.append(Salteada(comienza_at, _MOTIVO[type(exc)], str(exc)))
    return creadas, salteadas
