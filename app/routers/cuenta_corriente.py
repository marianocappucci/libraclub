"""Cuenta corriente: fiar una reserva, cobrar a cuenta y ver el saldo."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_staff
from app.db import obtener_sesion
from app.models.maestros import Cliente
from app.models.reservas import Reserva
from app.servicios import caja as servicio_caja
from app.servicios import cuenta_corriente as servicio
from app.servicios import facturacion

router = APIRouter(prefix="/api/cuenta-corriente", tags=["cuenta corriente"])


class PagoEntrada(BaseModel):
    monto: Decimal = Field(gt=0)
    medio_pago: str


class SaldoSalida(BaseModel):
    cliente_id: int
    cliente: str
    #: Positivo = debe; negativo = tiene saldo a favor. Lo calcula el backend:
    #: es plata, y dos pantallas sumando por su cuenta terminan mostrando
    #: números distintos.
    saldo: float


def _exigir_base() -> None:
    if not facturacion.hay_base():
        raise HTTPException(
            503,
            "La cuenta corriente no está configurada en esta instancia: falta "
            "LIBRACLUB_LIBRACORE_DATABASE_URL.",
        )


@router.post("/reservas/{reserva_id}/cargar", response_model=SaldoSalida)
def cargar(
    reserva_id: int,
    sesion: Session = Depends(obtener_sesion),
    usuario: dict = Depends(require_staff),
):
    """Fía una reserva: queda como deuda del cliente.

    Lo puede hacer el **mostrador**: decidir que alguien paga a fin de mes es
    parte de atender, y es el encargado el que está frente al cliente.
    """
    _exigir_base()
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None:
        raise HTTPException(404, "no existe esa reserva")
    if reserva.cliente_id is None:
        # Un bloqueo, o una reserva sin cliente, no se puede fiar: no hay a
        # quién cobrarle después.
        raise HTTPException(422, "esa reserva no tiene cliente al que cargarle la deuda")
    if reserva.precio is None or reserva.precio <= 0:
        raise HTTPException(422, "esa reserva no tiene precio")

    cliente = sesion.get(Cliente, reserva.cliente_id)
    saldo = servicio.cargar_reserva(cliente, reserva, usuario)
    return SaldoSalida(cliente_id=cliente.id, cliente=cliente.nombre, saldo=saldo)


@router.post("/clientes/{cliente_id}/pagos", response_model=SaldoSalida)
def pagar(
    cliente_id: int,
    datos: PagoEntrada,
    sesion: Session = Depends(obtener_sesion),
    usuario: dict = Depends(require_staff),
):
    """Registra un pago a cuenta. Entra a la caja del turno abierto."""
    _exigir_base()
    cliente = sesion.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(404, "no existe ese cliente")
    try:
        saldo = servicio.registrar_pago(cliente, datos.monto, datos.medio_pago, usuario)
    except servicio_caja.SinTurnoAbierto as e:
        raise HTTPException(409, str(e)) from e
    except servicio_caja.MedioDePagoInvalido as e:
        raise HTTPException(422, str(e)) from e
    return SaldoSalida(cliente_id=cliente.id, cliente=cliente.nombre, saldo=saldo)


@router.get("/clientes/{cliente_id}")
def ver(
    cliente_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """El saldo y el extracto de un cliente.

    Los movimientos van tal como los devuelve el motor: cada uno con su `tipo`
    (`debito` o `credito`) y un `monto` **siempre positivo**. El signo lo pone el
    tipo, no el número.
    """
    _exigir_base()
    cliente = sesion.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(404, "no existe ese cliente")
    return {
        "cliente_id": cliente.id,
        "cliente": cliente.nombre,
        "saldo": servicio.saldo(cliente_id),
        "movimientos": servicio.movimientos(cliente_id),
    }


@router.get("/deudores", response_model=list[SaldoSalida])
def deudores(_: object = Depends(require_staff)):
    """Quién debe y cuánto: la pantalla de cobranza.

    De **mostrador**, igual que fiar y que cobrar. El cliente llega y dice "vengo
    a pagar lo que debo": si el encargado no puede ver el saldo, no puede
    atenderlo. Esconderlo detrás de admin haría que la pantalla exista para el
    rol que no la usa.
    """
    _exigir_base()
    return [
        SaldoSalida(
            cliente_id=int(d["id"]),
            cliente=d.get("name") or "",
            saldo=float(d["saldo"]),
        )
        for d in servicio.deudores()
    ]
