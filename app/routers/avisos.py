"""Qué tipos de aviso se mandan (ADR-015, ADR-029, ADR-030).

Lo único que este router sigue sirviendo es **qué tipos de aviso salen** (`/api/avisos/tipos`): confirmación,
recordatorio, cancelación y seña por vencer. Es del producto porque son sus avisos. **No es el interruptor general**:
ese sigue siendo el cron.

Todo lo demás de la pantalla «Avisos» lo sirve el motor, montado en el mismo prefijo (`libracore.avisos_router`,
ADR-090):

| Ruta | Qué es | Quién |
|---|---|---|
| `GET /api/avisos/config`, `PUT /api/avisos/config` | el modo de WhatsApp, Evolution, si hay SMTP | admin |
| `POST /api/avisos/probar` | manda un mensaje fijo de prueba | admin |
| `GET /api/avisos/envios` | el registro de lo que salió | admin |

🔴 Por eso `/config` ya **no** es la configuración de los tipos (lo era hasta el ADR-030): el motor ocupa ese nombre, y
el `modo` de WhatsApp que guardaba `config_avisos` es ahora el suyo. Tampoco existe `/registro`: lo reemplaza
`/envios`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from libracore import config_manager
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_admin, require_staff
from app.db import obtener_sesion
from app.servicios import avisos as servicio

router = APIRouter(prefix="/api/avisos", tags=["avisos"])


class TiposDeAviso(BaseModel):
    confirmacion: bool
    recordatorio: bool
    cancelacion: bool
    sena_por_vencer: bool


class TiposDeAvisoSalida(TiposDeAviso):
    #: Si la instancia es una demo: lo necesita `ConfiguracionDeAvisos` del kit para decir de entrada que ahí WhatsApp
    #: nunca manda. Sale del mismo `config_manager` que usa el motor para decidirlo, no de una opción propia.
    demo: bool = False


def _salida(config: servicio.ConfiguracionDeAvisos) -> TiposDeAvisoSalida:
    return TiposDeAvisoSalida(
        confirmacion=config.confirmacion,
        recordatorio=config.recordatorio,
        cancelacion=config.cancelacion,
        sena_por_vencer=config.sena_por_vencer,
        demo=config_manager.es_demo(),
    )


@router.get("/tipos", response_model=TiposDeAvisoSalida)
def leer_tipos(
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    return _salida(servicio.configuracion(sesion))


@router.put("/tipos", response_model=TiposDeAvisoSalida)
def guardar_tipos(
    datos: TiposDeAviso,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
):
    """Sólo un admin: apagar la confirmación cambia lo que reciben los clientes."""
    nueva = servicio.ConfiguracionDeAvisos(
        confirmacion=datos.confirmacion,
        recordatorio=datos.recordatorio,
        cancelacion=datos.cancelacion,
        sena_por_vencer=datos.sena_por_vencer,
    )
    servicio.guardar_configuracion(sesion, nueva)
    sesion.commit()
    return _salida(nueva)
