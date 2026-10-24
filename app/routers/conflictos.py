"""Las reservas en conflicto: listarlas y resolverlas (ADR-022).

La pantalla es del kit (libra-ui); acá está la API. Listar sirve en el central y en un nodo (al nodo le llega por
el espejo); resolver sólo en el central.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_staff
from app.db import obtener_sesion
from app.models.maestros import Cancha, Cliente
from app.models.reservas import Reserva
from app.routers.reservas import _con_zona, _traducir
from app.schemas.reservas import ReservaSalida
from app.servicios import conflictos, devoluciones, reservas_nodo

router = APIRouter(prefix="/api/reservas-en-conflicto", tags=["reservas"])


class GanadoraSalida(BaseModel):
    """La reserva que se quedó con la cancha."""

    id: int
    estado: str
    origen: str
    comienza_at: datetime
    termina_at: datetime
    cliente_nombre: str | None


class ConflictoSalida(BaseModel):
    reserva: ReservaSalida
    cancha_nombre: str | None
    cliente_nombre: str | None
    #: `null` si la que ganó ya no se encuentra.
    ganadora: GanadoraSalida | None
    #: Si esta instancia puede resolverlo (el central sí, un nodo no): la pantalla esconde los botones.
    se_puede_resolver: bool


class Resolucion(BaseModel):
    accion: Literal["mover", "cancelar"]
    #: Sólo con `mover`. Sin ninguno de los dos, se intenta el horario original (sirve si la ganadora se canceló).
    comienza_at: datetime | None = None
    cancha_id: int | None = None
    #: Sólo con `cancelar`.
    motivo: str | None = Field(default=None, max_length=200)


def _nombre_cliente(sesion: Session, cliente_id: int | None) -> str | None:
    cliente = sesion.get(Cliente, cliente_id) if cliente_id is not None else None
    return cliente.nombre if cliente else None


@router.get("", response_model=list[ConflictoSalida])
def listar(
    sucursal_id: int | None = None,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Las reservas `en_conflicto`, por horario, cada una con la que le ganó."""
    se_puede = not reservas_nodo.en_un_nodo()
    salida = []
    for conflicto in conflictos.listar(sesion, sucursal_id):
        reserva, ganadora = conflicto.reserva, conflicto.ganadora
        cancha = sesion.get(Cancha, reserva.cancha_id)
        salida.append(
            ConflictoSalida(
                reserva=ReservaSalida.model_validate(reserva),
                cancha_nombre=cancha.nombre if cancha else None,
                cliente_nombre=_nombre_cliente(sesion, reserva.cliente_id),
                ganadora=(
                    GanadoraSalida(
                        id=ganadora.id,
                        estado=ganadora.estado.value,
                        origen=ganadora.origen.value,
                        comienza_at=ganadora.comienza_at,
                        termina_at=ganadora.termina_at,
                        cliente_nombre=_nombre_cliente(sesion, ganadora.cliente_id),
                    )
                    if ganadora is not None
                    else None
                ),
                se_puede_resolver=se_puede,
            )
        )
    return salida


@router.post("/{reserva_id}/resolver", response_model=ReservaSalida)
def resolver(
    reserva_id: int,
    datos: Resolucion,
    sesion: Session = Depends(obtener_sesion),
    usuario: dict = Depends(require_staff),
):
    """Mueve la reserva a un horario libre o la cancela. Sólo en el central (409 `solo_en_el_central` en un nodo)."""
    if datos.accion == "mover":
        reserva: Reserva = _traducir(conflictos.mover)(
            sesion,
            reserva_id,
            comienza_at=_con_zona(datos.comienza_at) if datos.comienza_at is not None else None,
            cancha_id=datos.cancha_id,
        )
    elif datos.accion == "cancelar":
        reserva = _traducir(conflictos.cancelar)(
            sesion,
            reserva_id,
            motivo=datos.motivo,
            pasarela=devoluciones.pasarela_de_la_instancia(),
            usuario=usuario,
        ).reserva
    else:  # pragma: no cover - lo cierra el Literal
        raise HTTPException(422, "Acción desconocida.")
    sesion.commit()
    sesion.refresh(reserva)
    return reserva
