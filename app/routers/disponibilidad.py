"""La grilla de la agenda: qué está libre y a cuánto."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_staff
from app.db import obtener_sesion
from app.models.maestros import Cancha
from app.schemas.reservas import TurnoSalida
from app.servicios import disponibilidad
from app.tiempo import hoy

router = APIRouter(prefix="/api/disponibilidad", tags=["disponibilidad"])


@router.get("/cancha/{cancha_id}", response_model=list[TurnoSalida])
def del_dia(
    cancha_id: int,
    dia: date | None = Query(default=None),
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    cancha = sesion.get(Cancha, cancha_id)
    if cancha is None:
        raise HTTPException(404, "No existe esa cancha.")
    return disponibilidad.marcar_cobrados(
        sesion, disponibilidad.grilla_del_dia(sesion, cancha, dia or hoy())
    )


@router.get("/semana")
def de_la_semana(
    sucursal_id: int,
    desde: date | None = Query(default=None),
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
) -> dict[str, object]:
    """Siete días de todas las canchas activas de una sucursal.

    `desde` arranca por defecto en el **lunes de la semana en curso**, y no en
    hoy: una agenda semanal que empieza un miércoles es ilegible, y el operador
    que abre la pantalla el miércoles quiere ver la semana, no los próximos
    siete días.
    """
    inicio = desde or (hoy() - timedelta(days=hoy().weekday()))
    grilla = disponibilidad.grilla_de_la_semana(sesion, sucursal_id, inicio)
    # 🔑 **Un solo lote para la semana entera.** Se pregunta acá y no adentro de
    # `grilla_de_la_semana` porque esa función llama a `grilla_del_dia` 7 veces
    # por cancha: marcar ahí serían decenas de conexiones a la base del motor
    # por cada refresco de la pantalla.
    saldadas = disponibilidad.reservas_saldadas(
        sesion,
        (
            turno.reserva_id
            for por_dia in grilla.values()
            for turnos in por_dia.values()
            for turno in turnos
            if turno.reserva_id is not None
        ),
    )
    return {
        "desde": inicio.isoformat(),
        "hasta": (inicio + timedelta(days=6)).isoformat(),
        "canchas": {
            # Las claves van como string: `Turno` es un dataclass con `slots`, o
            # sea **sin `__dict__`** — se convierte con `from_attributes`, no
            # desempaquetando el objeto.
            str(cancha_id): {
                dia: [
                    TurnoSalida.model_validate(
                        replace(turno, cobrado=True)
                        if turno.reserva_id in saldadas
                        else turno,
                        from_attributes=True,
                    )
                    for turno in turnos
                ]
                for dia, turnos in por_dia.items()
            }
            for cancha_id, por_dia in grilla.items()
        },
    }
