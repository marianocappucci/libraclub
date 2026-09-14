"""Lo que el motor de cierre diario (`libracore.caja_router.build_cierre_diario_router`)
no puede resolver solo, porque cruza las dos bases de este producto.

🔴 **Dos cruces, y los dos por el mismo motivo.** `cierres_diarios` vive en la
base de LibraCore, y de ahí sólo se puede leer `sucursal_id` (un entero) y
`usuario_id` (otro entero, el espejo de `espejar_usuario` — ver
`servicios/caja.py`). Ni la `Sucursal` ni el usuario real viven ahí:

- El **nombre de la sucursal** está en `app.models.maestros.Sucursal`, del
  lado del DOMINIO — lo pide `build_cierre_diario_router(resolver_sucursal_nombre=...)`.
- El **nombre de quién cerró** el motor lo resuelve él mismo en `get_cierre()`
  (join contra `usuarios` de LibraCore, que espejea al del dominio), pero NO
  en `listar_cierres()` — esa consulta trae la cabecera pelada, sin joins. Sin
  esto el listado de cierres de una sucursal mostraría `usuario_id` en vez del
  nombre de quien cerró.
"""

from __future__ import annotations

from libracore.db import core as libracore_core

from app import db
from app.models.maestros import Sucursal


def resolver_sucursal_nombre(sucursal_id: int | None) -> str:
    """El nombre de una `Sucursal`, para el ticket y el listado del cierre diario.

    Abre su propia sesión porque el motor la llama fuera de un request de
    FastAPI (no hay `Depends` de por medio) — mismo cruce que ya resuelve la
    Caja, acá sin la `Request` en curso.
    """
    if sucursal_id is None:
        return ""
    with db.fabrica_de_sesiones()() as sesion:
        sucursal = sesion.get(Sucursal, sucursal_id)
        return sucursal.nombre if sucursal else ""


def _nombres_de_usuarios(ids: set[int]) -> dict[int, str]:
    """`{usuario_id: nombre}` para el espejo de LibraCore. Una sola consulta
    por lote — el listado no abre una conexión por fila."""
    if not ids:
        return {}
    conexion = libracore_core.get_connection()
    try:
        marcadores = ",".join("?" for _ in ids)
        filas = conexion.execute(
            f"SELECT id, nombre FROM usuarios WHERE id IN ({marcadores})",
            tuple(ids),
        ).fetchall()
    finally:
        conexion.close()
    return {int(f["id"]): f["nombre"] for f in filas}


def listar_con_nombre(sucursal_id: int | None, *, todas: bool = False,
                      limit: int = 50) -> list[dict]:
    """`listar_cierres()` del motor, con `cerrado_por_nombre` agregado.

    Reemplaza al `GET ""` que monta `build_cierre_diario_router` — ver
    `app/routers/cierre_diario.py`, que se registra ANTES que el del motor
    para que este endpoint sea el que responda.
    """
    from libracore.db import cierre_diario as db_cierre_diario

    filas = db_cierre_diario.listar_cierres(sucursal_id, todas=todas, limit=limit)
    nombres = _nombres_de_usuarios({f["usuario_id"] for f in filas})
    for f in filas:
        f["cerrado_por_nombre"] = nombres.get(
            f["usuario_id"], f"usuario #{f['usuario_id']}",
        )
    return filas
