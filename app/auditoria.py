"""Quién hizo cada cambio: `created_by` / `updated_by`, llenados solos.

`Auditable` declara las cuatro columnas desde el primer día y **nadie las
llenaba**: cuatro columnas que se ven como trazabilidad y no lo son. Esto las
completa.

🔑 **Se llena en un solo lugar, no en cada servicio.** [[libradesk]] lo hace al
revés —`created_by=usuario_id` escrito a mano en cada `INSERT`— y es
exactamente así como se llega a columnas vacías: alcanza con que un camino nuevo
se olvide. Acá lo pone un listener de `before_flush`, así que **cualquier** fila
que se escriba queda auditada, incluidas las de los caminos que todavía no
existen.

Cómo llega el usuario hasta el flush:

1. Los gates de `app/auth.py` —que son por donde pasa toda ruta autenticada—
   guardan el id en `request.state`.
2. `db.obtener_sesion` deja la `Request` en `sesion.info`.
3. Este listener la lee **en el momento del flush**.

> 🔴 Se guarda la `Request` y no el id porque **el orden en que FastAPI resuelve
> las dependencias no está garantizado que ponga el gate antes que la sesión**:
> en estos endpoints `sesion` está declarada primero, así que cuando se crea
> todavía no hay usuario. Leyendo en el flush —que ocurre dentro del cuerpo del
> endpoint, con todas las dependencias ya resueltas— el orden deja de importar.
>
> Tampoco sirve un `ContextVar`: las dependencias sincrónicas de FastAPI corren
> en un hilo del threadpool, que recibe una **copia** del contexto. Un `.set()`
> ahí adentro no se ve desde el endpoint.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.base import Auditable

#: Dónde deja el gate el id, y dónde lo busca el listener.
CLAVE_EN_STATE = "usuario_id"
#: Dónde deja `obtener_sesion` la Request.
CLAVE_EN_INFO = "request"


def recordar_usuario(request: Any, usuario: dict | None) -> None:
    """Lo llaman los gates de `app/auth.py` con el usuario que dejaron pasar.

    🔑 **El token de servicio queda en `None`, y es a propósito.** `SERVICE_USER`
    de `libraauth` no tiene `id` —no es un usuario de esta instancia, es el
    backoffice de la suite—, y su propio comentario dice que una auditoría tiene
    que poder distinguir "lo hizo el proveedor" de "lo hizo un admin del
    cliente". Un `created_by` nulo con el resto de la fila cargada es justamente
    esa distinción; inventarle un id lo borraría.
    """
    if request is None:
        return
    crudo = (usuario or {}).get("id")
    # `libraauth` serializa el id como str en su API y la columna es Integer.
    try:
        request.state.usuario_id = int(crudo) if crudo is not None else None
    except (TypeError, ValueError):
        request.state.usuario_id = None


def _usuario_de(sesion: Session) -> int | None:
    request = sesion.info.get(CLAVE_EN_INFO)
    return getattr(getattr(request, "state", None), CLAVE_EN_STATE, None)


@event.listens_for(Session, "before_flush")
def _completar_auditoria(sesion: Session, _contexto, _instancias) -> None:
    """Sella quién crea y quién modifica, justo antes de que salga el SQL.

    Se engancha a la clase `Session` y no a una instancia: así vale para las
    sesiones de los endpoints y para cualquier otra que el producto abra.

    Sin usuario —una semilla, un script, el token de servicio— no se escribe
    nada y las columnas quedan en `NULL`. **Eso es un dato, no un agujero**: dice
    que el cambio no lo hizo una persona de esta instancia.
    """
    usuario_id = _usuario_de(sesion)
    if usuario_id is None:
        return

    for objeto in sesion.new:
        if isinstance(objeto, Auditable):
            # Sólo si viene vacío: un import o una migración pueden traer el
            # autor de verdad, y pisarlo con "quien corrió el import" sería
            # perder el dato que se quiere guardar.
            #
            # ⚠️ **Ningún test cubre este `if`, y no se puede cubrir hoy.** En un
            # alta por la API `created_by` siempre llega en `None`, así que
            # sacarlo no cambia nada — se midió mutándolo y la suite siguió en
            # verde. Es una defensa para el día que exista un importador que
            # traiga el autor original; cuando exista, ahí sí hay test posible.
            if objeto.created_by is None:
                objeto.created_by = usuario_id
            objeto.updated_by = usuario_id

    for objeto in sesion.dirty:
        if isinstance(objeto, Auditable) and sesion.is_modified(objeto):
            objeto.updated_by = usuario_id
