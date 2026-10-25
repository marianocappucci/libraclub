"""Eventos: un campeonato con varias categorías (ADR-024).

Un evento agrupa torneos —cada categoría es uno, con sus zonas y su grilla— que
comparten **las fechas y las canchas**. El router valida, delega y traduce
errores a códigos; la regla de las canchas vive en `servicios/torneos.programar`
y la de las fechas acá, al editar el evento.

**Quién puede qué**: crear y editar un evento es de **admin**, como definir un
torneo —cambia lo que el complejo se comprometió a jugar—; verlo es de staff.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.auth import require_admin, require_staff
from app.db import obtener_sesion
from app.models.maestros import Cancha, Sucursal
from app.models.torneos import Evento, Torneo, canchas_de_evento
from app.routers.torneos import torneos_en_lista
from app.schemas.torneos import (
    EventoDetalle,
    EventoEdicion,
    EventoEnLista,
    EventoEntrada,
    EventoSalida,
)

router = APIRouter(prefix="/api/eventos", tags=["eventos"])


def _evento(sesion: Session, evento_id: int) -> Evento:
    evento = sesion.get(Evento, evento_id)
    if evento is None:
        raise HTTPException(404, "No existe ese evento.")
    return evento


def _canchas_de(sesion: Session, evento_ids: list[int]) -> dict[int, list[int]]:
    """Las canchas de varios eventos en una consulta."""
    por_evento: dict[int, list[int]] = {i: [] for i in evento_ids}
    if not evento_ids:
        return por_evento
    filas = sesion.execute(
        select(canchas_de_evento.c.evento_id, canchas_de_evento.c.cancha_id)
        .where(canchas_de_evento.c.evento_id.in_(evento_ids))
        .order_by(canchas_de_evento.c.cancha_id)
    )
    for evento_id, cancha_id in filas:
        por_evento[evento_id].append(cancha_id)
    return por_evento


def _salida(sesion: Session, evento: Evento) -> EventoSalida:
    return EventoSalida(
        id=evento.id,
        sucursal_id=evento.sucursal_id,
        nombre=evento.nombre,
        desde=evento.desde,
        hasta=evento.hasta,
        observaciones=evento.observaciones,
        cancha_ids=_canchas_de(sesion, [evento.id])[evento.id],
    )


def _validar_canchas(sesion: Session, sucursal_id: int, cancha_ids: list[int]) -> list[int]:
    """Las canchas tienen que existir y ser de la sucursal del evento."""
    unicas = sorted(set(cancha_ids))
    if not unicas:
        return []
    halladas = {
        c.id: c
        for c in sesion.scalars(select(Cancha).where(Cancha.id.in_(unicas)))
    }
    for cancha_id in unicas:
        cancha = halladas.get(cancha_id)
        if cancha is None:
            raise HTTPException(422, "Una de las canchas no existe.")
        if cancha.sucursal_id != sucursal_id:
            raise HTTPException(422, f"{cancha.nombre} es de otra sucursal.")
    return unicas


def _nombre_libre(
    sesion: Session, sucursal_id: int, nombre: str, salvo: int | None = None
) -> None:
    consulta = select(Evento.id).where(
        Evento.sucursal_id == sucursal_id, func.lower(Evento.nombre) == nombre.lower()
    )
    if salvo is not None:
        consulta = consulta.where(Evento.id != salvo)
    if sesion.scalar(consulta) is not None:
        raise HTTPException(409, "Ya hay un evento con ese nombre en la sucursal.")


@router.get("", response_model=list[EventoEnLista])
def listar(
    sucursal_id: int | None = Query(default=None),
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    consulta = select(Evento).order_by(Evento.desde.desc(), Evento.id.desc())
    if sucursal_id is not None:
        consulta = consulta.where(Evento.sucursal_id == sucursal_id)
    eventos = list(sesion.scalars(consulta).all())
    canchas = _canchas_de(sesion, [e.id for e in eventos])
    cuantas = dict(
        sesion.execute(
            select(Torneo.evento_id, func.count(Torneo.id))
            .where(Torneo.evento_id.in_([e.id for e in eventos]))
            .group_by(Torneo.evento_id)
        ).all()
    ) if eventos else {}
    return [
        EventoEnLista(
            **_base(e, canchas[e.id]),
            categorias=cuantas.get(e.id, 0),
        )
        for e in eventos
    ]


def _base(evento: Evento, cancha_ids: list[int]) -> dict:
    return dict(
        id=evento.id,
        sucursal_id=evento.sucursal_id,
        nombre=evento.nombre,
        desde=evento.desde,
        hasta=evento.hasta,
        observaciones=evento.observaciones,
        cancha_ids=cancha_ids,
    )


@router.post("", response_model=EventoSalida, status_code=201)
def crear(
    datos: EventoEntrada,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
):
    if sesion.get(Sucursal, datos.sucursal_id) is None:
        raise HTTPException(422, "No existe esa sucursal.")
    _nombre_libre(sesion, datos.sucursal_id, datos.nombre)
    cancha_ids = _validar_canchas(sesion, datos.sucursal_id, datos.cancha_ids)
    evento = Evento(
        sucursal_id=datos.sucursal_id,
        nombre=datos.nombre.strip(),
        desde=datos.desde,
        hasta=datos.hasta,
        observaciones=datos.observaciones,
    )
    sesion.add(evento)
    sesion.flush()
    if cancha_ids:
        sesion.execute(
            insert(canchas_de_evento),
            [{"evento_id": evento.id, "cancha_id": c} for c in cancha_ids],
        )
    sesion.commit()
    return _salida(sesion, evento)


@router.get("/{evento_id}", response_model=EventoDetalle)
def obtener(
    evento_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    evento = _evento(sesion, evento_id)
    categorias = list(
        sesion.scalars(
            select(Torneo)
            .where(Torneo.evento_id == evento.id)
            .order_by(Torneo.categoria, Torneo.id)
        ).all()
    )
    return EventoDetalle(
        **_base(evento, _canchas_de(sesion, [evento.id])[evento.id]),
        categorias=torneos_en_lista(sesion, categorias),
    )


@router.put("/{evento_id}", response_model=EventoSalida)
def editar(
    evento_id: int,
    datos: EventoEdicion,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
):
    """Cambia nombre, fechas y canchas. Las fechas se copian a todas las categorías.

    Las canchas que se sacan no tocan los partidos que ya tienen una: el evento
    deja de ofrecerlas, pero el bloqueo que ya está en la agenda sigue siendo de
    ese partido hasta que alguien lo mueva.
    """
    evento = _evento(sesion, evento_id)
    _nombre_libre(sesion, evento.sucursal_id, datos.nombre, salvo=evento.id)
    cancha_ids = _validar_canchas(sesion, evento.sucursal_id, datos.cancha_ids)

    evento.nombre = datos.nombre.strip()
    evento.desde = datos.desde
    evento.hasta = datos.hasta
    evento.observaciones = datos.observaciones
    # Las fechas del evento mandan: todas sus categorías juegan los mismos días.
    # Una por una y no con un `UPDATE` masivo: la auditoría de cada torneo
    # (quién le cambió las fechas) sale de la sesión.
    for categoria in sesion.scalars(select(Torneo).where(Torneo.evento_id == evento.id)):
        categoria.desde = datos.desde
        categoria.hasta = datos.hasta
    sesion.execute(
        delete(canchas_de_evento).where(canchas_de_evento.c.evento_id == evento.id)
    )
    if cancha_ids:
        sesion.execute(
            insert(canchas_de_evento),
            [{"evento_id": evento.id, "cancha_id": c} for c in cancha_ids],
        )
    sesion.commit()
    sesion.refresh(evento)
    return _salida(sesion, evento)
