"""El listado del cierre diario, con el nombre de quién cerró.

Sólo esto: el resto de los endpoints (`preview`, `cerrar`, el detalle por id y
los dos tickets) los sirve `libracore.caja_router.build_cierre_diario_router`,
montado en `app/main.py`. Este router se registra ANTES que aquél y sobre el
MISMO prefijo — Starlette matchea rutas en orden de registro, así que este
`GET ""` es el que responde y el `GET ""` del motor (que devuelve la cabecera
pelada, sin `cerrado_por_nombre`) nunca llega a ejecutarse. Ver el docstring
de `app/servicios/cierre_diario.py` por qué hace falta.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import require_staff
from app.routers.facturacion import exigir_base
from app.servicios import cierre_diario as servicio

router = APIRouter(
    prefix="/api/cierre-diario", tags=["cierre-diario"],
    dependencies=[Depends(exigir_base)],
)


@router.get("", operation_id="listar_cierre_diario_con_nombre")
def listar(sucursal_id: int | None = None, todas: bool = False, limit: int = 50,
          usuario: dict = Depends(require_staff)):
    # `operation_id` explícito: sin él, FastAPI lo deriva del nombre de la
    # función y el path — los mismos que usa el `GET ""` del motor sobre el
    # mismo prefijo — y el schema de OpenAPI queda con un id duplicado.
    return servicio.listar_con_nombre(sucursal_id, todas=todas, limit=limit)
