"""«Falta uno»: completar el equipo de un partido ya reservado.

El organizador reservó y pagó la cancha, y le faltan jugadores. Publica cuántos,
y otros con cuenta se suman. **El sistema junta la gente y nada más**: lo que
cada uno le devuelve al que pagó lo arreglan entre ellos (decisión del humano,
2026-08-21).

## 🔴 La privacidad es la mitad del diseño

El listado de partidos abiertos lo ve **cualquiera con cuenta**. Si trajera
teléfonos, alcanzaría con registrarse para levantar la agenda de todos los que
juegan en el complejo — y quien la levanta no es un desconocido cualquiera, es
alguien que sabe además a qué hora juega cada uno y en qué cancha.

Por eso hay **dos vistas y no una con un campo opcional**:

- `listar()` devuelve nombre y cupos. Nunca contacto.
- `detalle()` devuelve el contacto **sólo si quien pregunta está anotado o es el
  organizador**, que es cuando lo necesita para coordinar.

Que sean dos funciones y no un `if` adentro de una es a propósito: un filtro
olvidado en una rama de un `if` no se ve, y un campo de más en un dict tampoco.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import EstadoReserva
from app.models.maestros import Cancha, Cliente, CuentaDeJugador
from app.models.reservas import AnotadoEnPartido, BusquedaDeJugadores, Reserva
from app.tiempo import ahora


class NoSePuedePublicar(ValueError):
    pass


class PartidoCerrado(RuntimeError):
    pass


class NoEsTuPartido(RuntimeError):
    pass


def publicar(
    sesion: Session, *, cuenta: CuentaDeJugador, reserva_id: int, faltan: int, nota: str = ""
) -> BusquedaDeJugadores:
    """Publica que faltan jugadores para una reserva propia.

    🔴 **Sólo sobre una reserva confirmada, futura y del que publica.** Las tres
    condiciones tapan cosas distintas: publicar sobre una provisoria ofrecería
    lugares en un turno que todavía se puede caer por falta de pago; sobre una
    pasada, un partido que ya se jugó; y sobre la de otro, un partido ajeno al
    que después nadie podría entrar.
    """
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None or reserva.cliente_id != cuenta.cliente_id:
        # Mismo error para "no existe" y "no es tuya": distinguirlos diría
        # cuáles ids existen.
        raise NoSePuedePublicar("No encontramos esa reserva.")
    if reserva.estado is not EstadoReserva.CONFIRMADA:
        raise NoSePuedePublicar(
            "Sólo se puede buscar jugadores para un turno confirmado y pagado."
        )
    if reserva.comienza_at <= ahora():
        raise NoSePuedePublicar("Ese partido ya pasó.")
    if not 1 <= faltan <= 20:
        raise NoSePuedePublicar("Decí cuántos jugadores faltan, entre 1 y 20.")

    busqueda = BusquedaDeJugadores(
        reserva_id=reserva.id, faltan=faltan, nota=(nota or "").strip() or None
    )
    sesion.add(busqueda)
    try:
        sesion.flush()
    except IntegrityError as exc:
        sesion.rollback()
        raise NoSePuedePublicar("Ese partido ya está publicado.") from exc
    return busqueda


def _cupos_libres(sesion: Session, busqueda: BusquedaDeJugadores) -> int:
    anotados = sesion.scalar(
        select(func.count(AnotadoEnPartido.id)).where(
            AnotadoEnPartido.busqueda_id == busqueda.id
        )
    ) or 0
    return max(0, busqueda.faltan - anotados)


def listar(sesion: Session) -> list[dict]:
    """Los partidos abiertos y futuros. **Sin datos de contacto de nadie.**

    Se ordena por cuándo se juega: el que busca quiere saber qué hay esta
    semana, no qué se publicó primero.
    """
    filas = sesion.execute(
        select(BusquedaDeJugadores, Reserva, Cancha.nombre, Cliente.nombre, Cancha.deporte)
        .join(Reserva, Reserva.id == BusquedaDeJugadores.reserva_id)
        .join(Cancha, Cancha.id == Reserva.cancha_id)
        .join(Cliente, Cliente.id == Reserva.cliente_id)
        .where(
            BusquedaDeJugadores.abierta.is_(True),
            Reserva.estado == EstadoReserva.CONFIRMADA,
            Reserva.comienza_at > ahora(),
        )
        .order_by(Reserva.comienza_at)
    ).all()

    salida = []
    for busqueda, reserva, cancha, organizador, deporte in filas:
        libres = _cupos_libres(sesion, busqueda)
        if libres == 0:
            # Completo: deja de ofrecerse. La búsqueda no se cierra sola en la
            # base —alguien puede bajarse y volver a abrir un lugar— pero no
            # tiene sentido listarla.
            continue
        salida.append(
            {
                "id": busqueda.id,
                "cancha": cancha,
                "comienza_at": reserva.comienza_at,
                "termina_at": reserva.termina_at,
                "deporte": deporte.value,
                "organizador": organizador,
                "faltan": libres,
                "nota": busqueda.nota,
            }
        )
    return salida


def detalle(sesion: Session, cuenta: CuentaDeJugador, busqueda_id: int) -> dict:
    """Un partido, **con el contacto sólo si quien pregunta juega ahí**.

    🔴 Ésta es la única función que devuelve teléfonos, y la condición está
    arriba de todo para que se vea. Un jugador que no está anotado recibe
    exactamente lo mismo que en el listado.
    """
    busqueda = sesion.get(BusquedaDeJugadores, busqueda_id)
    if busqueda is None:
        raise PartidoCerrado("No encontramos ese partido.")
    reserva = sesion.get(Reserva, busqueda.reserva_id)
    organizador = sesion.get(Cliente, reserva.cliente_id)
    cancha = sesion.get(Cancha, reserva.cancha_id)

    anotados = list(
        sesion.execute(
            select(AnotadoEnPartido, Cliente, CuentaDeJugador)
            .join(CuentaDeJugador, CuentaDeJugador.id == AnotadoEnPartido.cuenta_id)
            .join(Cliente, Cliente.id == CuentaDeJugador.cliente_id)
            .where(AnotadoEnPartido.busqueda_id == busqueda.id)
            .order_by(AnotadoEnPartido.id)
        ).all()
    )

    soy_organizador = reserva.cliente_id == cuenta.cliente_id
    estoy_anotado = any(c.id == cuenta.id for _, _, c in anotados)
    puedo_ver_contacto = soy_organizador or estoy_anotado

    return {
        "id": busqueda.id,
        "cancha": cancha.nombre if cancha else "",
        "comienza_at": reserva.comienza_at,
        "termina_at": reserva.termina_at,
        "organizador": organizador.nombre if organizador else "",
        # `None` y no la cadena vacía: el frontend distingue "no me corresponde
        # verlo" de "no lo cargó".
        "organizador_telefono": (
            (organizador.telefono if organizador else None) if puedo_ver_contacto else None
        ),
        "faltan": _cupos_libres(sesion, busqueda),
        "nota": busqueda.nota,
        "abierta": busqueda.abierta,
        "soy_organizador": soy_organizador,
        "estoy_anotado": estoy_anotado,
        "anotados": [
            {
                "nombre": cliente.nombre,
                "telefono": cliente.telefono if puedo_ver_contacto else None,
                "soy_yo": jugador.id == cuenta.id,
            }
            for _, cliente, jugador in anotados
        ],
    }


def sumarse(
    sesion: Session, cuenta: CuentaDeJugador, busqueda_id: int
) -> AnotadoEnPartido:
    """El jugador se suma a un partido. Devuelve su anotación."""
    busqueda = sesion.get(BusquedaDeJugadores, busqueda_id)
    if busqueda is None or not busqueda.abierta:
        raise PartidoCerrado("Ese partido ya no está abierto.")

    reserva = sesion.get(Reserva, busqueda.reserva_id)
    if reserva.estado is not EstadoReserva.CONFIRMADA or reserva.comienza_at <= ahora():
        # 🔑 Se chequea acá y no sólo al publicar: entre que se publicó y que
        # alguien se suma pueden pasar días, y en el medio la reserva se pudo
        # cancelar. Sumarse a un partido cancelado deja a alguien yendo a una
        # cancha que no está reservada.
        raise PartidoCerrado("Ese partido ya no está disponible.")
    if reserva.cliente_id == cuenta.cliente_id:
        raise PartidoCerrado("Ese partido es tuyo: ya estás adentro.")
    if _cupos_libres(sesion, busqueda) <= 0:
        raise PartidoCerrado("Ya se completaron los lugares.")

    anotado = AnotadoEnPartido(busqueda_id=busqueda.id, cuenta_id=cuenta.id)
    sesion.add(anotado)
    try:
        sesion.flush()
    except IntegrityError as exc:
        sesion.rollback()
        # El UNIQUE lo agarra: dos clicks seguidos no ocupan dos lugares.
        raise PartidoCerrado("Ya estás anotado en ese partido.") from exc
    return anotado


def bajarse(sesion: Session, cuenta: CuentaDeJugador, busqueda_id: int) -> None:
    """El jugador se baja y su lugar vuelve a quedar libre."""
    anotado = sesion.scalars(
        select(AnotadoEnPartido).where(
            AnotadoEnPartido.busqueda_id == busqueda_id,
            AnotadoEnPartido.cuenta_id == cuenta.id,
        )
    ).first()
    if anotado is None:
        raise PartidoCerrado("No estás anotado en ese partido.")
    sesion.delete(anotado)


def cerrar(sesion: Session, cuenta: CuentaDeJugador, busqueda_id: int) -> None:
    """El organizador deja de buscar. **Sólo el organizador.**"""
    busqueda = sesion.get(BusquedaDeJugadores, busqueda_id)
    if busqueda is None:
        raise PartidoCerrado("No encontramos ese partido.")
    reserva = sesion.get(Reserva, busqueda.reserva_id)
    if reserva.cliente_id != cuenta.cliente_id:
        raise NoEsTuPartido("Ese partido no es tuyo.")
    busqueda.abierta = False


def mis_partidos(sesion: Session, cuenta: CuentaDeJugador) -> list[dict]:
    """Los partidos donde el jugador está anotado. Con contacto: juega ahí."""
    ids = list(
        sesion.scalars(
            select(AnotadoEnPartido.busqueda_id).where(
                AnotadoEnPartido.cuenta_id == cuenta.id
            )
        )
    )
    return [detalle(sesion, cuenta, i) for i in ids]
