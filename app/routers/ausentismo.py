"""Los clientes que faltan sin avisar. Lo lee el mostrador al reservar.

La regla —cuántas ausencias, en cuántos días— está en `servicios/ausentismo.py`
y la respuesta la trae **resuelta**: la pantalla muestra lo que le llega y no
vuelve a decidir quién es reincidente.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_staff
from app.db import obtener_sesion
from app.servicios import ausentismo as servicio

router = APIRouter(prefix="/api/clientes", tags=["clientes"])


class Reincidente(BaseModel):
    cliente_id: int
    ausentes: int
    #: El comienzo del último turno al que faltó, en ISO. El `dd-mm-aaaa` lo
    #: pone la pantalla, como en el resto de la API.
    ultimo_ausente_at: datetime


class Reincidentes(BaseModel):
    #: La regla vigente, para que la pantalla la pueda **decir** («en los
    #: últimos 90 días») sin llevar su propia copia del número.
    umbral: int
    dias: int
    reincidentes: list[Reincidente]


@router.get("/ausentismo/reincidentes", response_model=Reincidentes)
def reincidentes(
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Los que pasaron el umbral de ausencias en la ventana.

    🔴 **Dos segmentos después de `/clientes`, a propósito.** El ABM de clientes
    declara `GET /api/clientes/{item_id}`, que matchea cualquier segmento único:
    un `GET /api/clientes/reincidentes` entraría por ahí con
    `item_id="reincidentes"` y contestaría un 422. Mismo criterio que
    `/api/reservas/series/listado`.

    Una lista y no un campo más en cada cliente del listado: los reincidentes
    son pocos, y sumar un conteo al ABM genérico obligaría a la fábrica de los
    cinco maestros a saber qué es una reserva.
    """
    return Reincidentes(
        umbral=servicio.UMBRAL,
        dias=servicio.VENTANA.days,
        reincidentes=[
            Reincidente(
                cliente_id=a.cliente_id, ausentes=a.ausentes, ultimo_ausente_at=a.ultimo
            )
            for a in servicio.reincidentes(sesion)
        ],
    )
