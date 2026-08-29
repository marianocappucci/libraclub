"""Las devoluciones de seña que quedaron a medias.

🔴 **Esto es lo que hace que `DEVOLUCION_PENDIENTE` sirva para algo.** Un estado
que dice «el complejo le debe plata a alguien» y que nadie puede ver ni
reintentar es peor que no tenerlo: la deuda existe, no se paga, y la única forma
de enterarse es que el jugador llame.

El reintento **lo aprieta una persona**. Una devolución que falla suele fallar
por algo que hay que arreglar —el token vencido, un pago que MercadoPago no deja
devolver— y un reintento automático cada cinco minutos sólo agrega ruido al log.
Apretar dos veces no devuelve dos veces: la clave de idempotencia es del pago.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import require_admin, require_staff
from app.db import obtener_sesion
from app.servicios import cancelacion as servicio
from app.servicios import devoluciones as pasarelas
from app.servicios import reservas as servicio_reservas

router = APIRouter(prefix="/api/devoluciones", tags=["devoluciones"])


class DevolucionPendiente(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reserva_id: int
    monto: Decimal
    referencia: str
    payment_id: str | None
    detalle_devolucion: str | None
    created_at: datetime


class ResultadoSalida(BaseModel):
    pago_id: int
    estado: str
    detalle: str


@router.get("", response_model=list[DevolucionPendiente])
def pendientes(
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Lo que el complejo debe devolver y todavía no devolvió."""
    return servicio.pendientes(sesion)


@router.post("/{pago_id}/reintentar", response_model=ResultadoSalida)
def reintentar(
    pago_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
):
    """Vuelve a pedirle la devolución a MercadoPago.

    Es de **admin** y no de staff: mover plata hacia afuera es del dueño. Ver la
    lista sí es de staff — el encargado tiene que poder contestarle al jugador
    que llama, sin poder ejecutar la devolución.
    """
    try:
        resultado = servicio.reintentar(
            sesion, pago_id, pasarela=pasarelas.pasarela_de_la_instancia()
        )
    except servicio_reservas.ReservaInvalida as exc:
        raise HTTPException(404, str(exc)) from exc
    except servicio_reservas.TransicionInvalida as exc:
        raise HTTPException(409, str(exc)) from exc
    sesion.commit()
    # 🔑 Un reintento que falla devuelve **200 y el motivo**, no un 500: el
    # pedido se procesó y la respuesta es "sigue pendiente, por esto". Un error
    # HTTP haría que la pantalla muestre "algo salió mal" y esconda justamente
    # el texto que dice qué arreglar.
    return ResultadoSalida(
        pago_id=pago_id,
        estado=resultado.pago.estado.value if resultado.pago else "",
        detalle=resultado.detalle,
    )
