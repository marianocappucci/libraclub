"""`GET`/`PUT /config/arca` — la configuración de facturación de la instancia.

El prefijo es `/config/arca` y **no** `/api/config/arca` porque es el que
consume la pestaña de ARCA de `libra-ui`, que ya comparten los tres verticales
de instancia única. Renombrarlo obligaría a forkear esa pantalla.

> ⚠️ Es la excepción a la convención `/api/*` de este producto, y por eso está
> escrito acá. La otra ruta del kit que no lleva `/api` es
> `/auth/change-password`, por el mismo motivo.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.servicios import facturacion

router = APIRouter(prefix="/config/arca", tags=["facturacion"])


class ConfigArcaEntrada(BaseModel):
    cuit: str = Field(min_length=1, max_length=13)
    punto_venta: int = Field(ge=1, le=99999)
    certificado_path: str = ""
    clave_path: str = ""
    #: `homologacion` por default: emitir contra producción es deliberado.
    ambiente: str = "homologacion"


class ConfigArcaSalida(BaseModel):
    empresa: str
    cuit: str
    punto_venta: int
    ambiente: str
    certificado_path: str
    clave_path: str


def _salida(cfg: dict) -> ConfigArcaSalida:
    return ConfigArcaSalida(
        empresa=cfg["empresa"], cuit=cfg["cuit"], punto_venta=cfg["punto_venta"],
        ambiente=cfg["ambiente"], certificado_path=cfg["certificado_path"],
        clave_path=cfg["clave_path"],
    )


def _exigir_base() -> None:
    """503 y no 500 si la instancia no tiene base de LibraCore.

    🔑 El mensaje dice **qué falta**, porque el síntoma del lado de la pantalla
    es idéntico al de un error cualquiera: sin esto, un complejo sin configurar
    vería "algo falló" y nadie sabría que lo que hay que hacer es agregar una
    variable de entorno.
    """
    if not facturacion.hay_base():
        raise HTTPException(
            503,
            "La facturación no está configurada en esta instancia: falta "
            "LIBRACLUB_LIBRACORE_DATABASE_URL.",
        )


@router.get("", response_model=ConfigArcaSalida | None)
def obtener() -> ConfigArcaSalida | None:
    _exigir_base()
    cfg = facturacion.obtener_config_arca()
    return _salida(cfg) if cfg else None


@router.put("", response_model=ConfigArcaSalida)
def guardar(datos: ConfigArcaEntrada) -> ConfigArcaSalida:
    _exigir_base()
    return _salida(
        facturacion.guardar_config_arca(
            datos.cuit, datos.punto_venta, datos.clave_path,
            datos.certificado_path, datos.ambiente,
        )
    )
