"""Lo que el motor de cierre diario (`libracore.caja_router.build_cierre_diario_router`)
no puede resolver solo, porque cruza las dos bases de este producto.

`cierres_diarios` vive en la base de LibraCore, y de ahí sólo se puede leer
`sucursal_id`, un entero: el **nombre de la sucursal** está en
`app.models.maestros.Sucursal`, del lado del DOMINIO, y lo pide
`build_cierre_diario_router(resolver_sucursal_nombre=...)`.

El **nombre de quién cerró** lo resuelve el motor, en el detalle y en el
listado (`listar_cierres` desde libracore v1.98.1), contra el espejo de
`usuarios` de LibraCore. Hasta esa versión el listado venía sin nombre y este
módulo lo agregaba con un endpoint propio que tapaba al del motor.
"""

from __future__ import annotations

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
