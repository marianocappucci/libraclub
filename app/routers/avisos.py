"""Avisos: qué salió y a quién, y qué avisos se mandan (ADR-015, ADR-029).

Dos cosas, y las dos son del mostrador y del dueño, no del jugador:

- **El registro** (`GET /api/avisos/registro`): lo que `avisos` guardó de cada intento. Existe
  desde ADR-015 pero no tenía por dónde mirarse, y su docstring lo dice —«es para lo único que
  se mira»: la discusión con el cliente que jura que no le llegó nada—.
- **La configuración** (`/api/avisos/config`): qué tipos de aviso salen y el modo del canal de
  WhatsApp. **No es el interruptor general**: ese sigue siendo el cron.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin, require_staff
from app.db import obtener_sesion
from app.models.avisos import Aviso
from app.models.enums import CanalAviso, EstadoAviso, ModoWhatsapp, TipoAviso
from app.models.maestros import Cancha
from app.models.reservas import Reserva
from app.servicios import avisos as servicio

router = APIRouter(prefix="/api/avisos", tags=["avisos"])

#: Cuántos intentos trae el registro como máximo. Es una pantalla para mirar lo último, no un
#: reporte: lo que se busca es «¿le llegó el de ayer?», no el historial del año.
MAXIMO_DEL_REGISTRO = 500


class ConfigAvisos(BaseModel):
    whatsapp: ModoWhatsapp
    confirmacion: bool
    recordatorio: bool
    cancelacion: bool
    sena_por_vencer: bool


class AvisoRegistrado(BaseModel):
    id: int
    creado_at: datetime
    tipo: TipoAviso
    canal: CanalAviso
    estado: EstadoAviso
    #: A dónde salió, **congelado** al momento del envío (ver `models/avisos.Aviso.destino`).
    destino: str
    detalle: str | None
    #: Lo que efectivamente se armó para mandar (`asunto` es `null` por WhatsApp).
    asunto: str | None
    cuerpo: str | None
    intentos: int
    reserva_id: int
    cancha: str | None
    comienza_at: datetime


def _salida(config: servicio.ConfiguracionDeAvisos) -> ConfigAvisos:
    return ConfigAvisos(
        whatsapp=config.whatsapp,
        confirmacion=config.confirmacion,
        recordatorio=config.recordatorio,
        cancelacion=config.cancelacion,
        sena_por_vencer=config.sena_por_vencer,
    )


@router.get("/config", response_model=ConfigAvisos)
def leer_config(
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    return _salida(servicio.configuracion(sesion))


@router.put("/config", response_model=ConfigAvisos)
def guardar_config(
    datos: ConfigAvisos,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
):
    """Sólo un admin: apagar la confirmación o prender WhatsApp cambia lo que reciben los clientes."""
    nueva = servicio.ConfiguracionDeAvisos(
        whatsapp=datos.whatsapp,
        confirmacion=datos.confirmacion,
        recordatorio=datos.recordatorio,
        cancelacion=datos.cancelacion,
        sena_por_vencer=datos.sena_por_vencer,
    )
    servicio.guardar_configuracion(sesion, nueva)
    sesion.commit()
    return _salida(nueva)


@router.get("/registro", response_model=list[AvisoRegistrado])
def registro(
    limite: int = Query(default=100, ge=1, le=MAXIMO_DEL_REGISTRO),
    canal: CanalAviso | None = None,
    estado: EstadoAviso | None = None,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Los últimos intentos, del más nuevo al más viejo."""
    consulta = (
        select(Aviso, Reserva.comienza_at, Cancha.nombre)
        .join(Reserva, Reserva.id == Aviso.reserva_id)
        .join(Cancha, Cancha.id == Reserva.cancha_id, isouter=True)
        .order_by(Aviso.created_at.desc(), Aviso.id.desc())
        .limit(limite)
    )
    if canal is not None:
        consulta = consulta.where(Aviso.canal == canal)
    if estado is not None:
        consulta = consulta.where(Aviso.estado == estado)
    return [
        AvisoRegistrado(
            id=a.id,
            creado_at=a.created_at,
            tipo=a.tipo,
            canal=a.canal,
            estado=a.estado,
            destino=a.destino,
            detalle=a.detalle,
            asunto=a.asunto,
            cuerpo=a.cuerpo,
            intentos=a.intentos,
            reserva_id=a.reserva_id,
            cancha=cancha,
            comienza_at=comienza_at,
        )
        for a, comienza_at, cancha in sesion.execute(consulta).all()
    ]
