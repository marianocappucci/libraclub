"""Los cambios de clientes por revisar: verlos y elegir cuál queda, aplicarlos o descartarlos (ADR-022, tercer y cuarto
addendum). La lista trae las que chocan y las que ya no chocan (`ya_no_choca`).

Molde: `routers/conflictos.py` (las reservas en conflicto). La pantalla es de LibraClub (`ClientesEnConflicto` y
`ResolverConflictoDeCliente`); acá está la API. Es sólo del central: en la PC del club la lista viene vacía y resolver
da 409 `solo_en_el_central`, porque la revisión manual de LibraEdge vive en el central.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from libracore.nodo_offline import SoloEnElCentral
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_staff
from app.db import obtener_sesion
from app.servicios import clientes_nodo, ediciones_en_conflicto
from app.servicios.ediciones_en_conflicto import (
    CambioEnLaWeb,
    EdicionEnRevision,
    EdicionNoAplicable,
    EdicionNoEncontrada,
    EdicionYaResuelta,
    EleccionInvalida,
)

router = APIRouter(prefix="/api/clientes-en-conflicto", tags=["clientes"])


class CampoSalida(BaseModel):
    campo: str
    etiqueta: str
    #: `conflicto` (hay que elegir), `se_aplica` (la web no cambió: se pone el valor de la PC) o `igual` (ya está).
    estado: Literal["conflicto", "se_aplica", "igual"]
    #: Lo que había cuando se corrigió en la PC, para referencia.
    antes: Any
    #: Lo que hay hoy en la web.
    web: Any
    #: Lo que se cargó en la PC.
    pc: Any


class EdicionSalida(BaseModel):
    operacion_id: str
    cliente_id: int
    cliente_nombre: str
    recibida_at: str | None
    campos: list[CampoSalida]
    #: Cuántos campos piden elegir. Si es 0, ya no choca nada y guardar aplica lo que falta.
    en_conflicto: int
    #: Sigue en revisión pero hoy no hay nada para elegir: se puede aplicar (o descartar) sin riesgo.
    ya_no_choca: bool
    #: Si esta instancia puede resolverla (la web sí, la PC del club no).
    se_puede_resolver: bool


class Resolucion(BaseModel):
    #: Por cada campo en conflicto, de quién es el valor que queda.
    elecciones: dict[str, Literal["web", "pc"]] = Field(default_factory=dict)
    #: Lo que la pantalla mostró de la web en cada campo de la edición. Si cambió, no se pisa nada.
    vistos: dict[str, Any]


class Descarte(BaseModel):
    #: Lo que la pantalla mostró de la web en cada campo de la edición. Si cambió, no se descarta nada.
    vistos: dict[str, Any]


class ResultadoSalida(BaseModel):
    #: Los campos que se cambiaron en el cliente.
    aplicados: list[str]


class DescarteSalida(BaseModel):
    descartada: bool = True


def _a_salida(edicion: EdicionEnRevision) -> EdicionSalida:
    return EdicionSalida(
        operacion_id=edicion.operacion_id,
        cliente_id=edicion.cliente_id,
        cliente_nombre=edicion.cliente_nombre,
        recibida_at=edicion.recibida_at,
        campos=[CampoSalida(**vars(c)) for c in edicion.campos],
        en_conflicto=len(edicion.en_conflicto),
        ya_no_choca=edicion.ya_no_choca,
        se_puede_resolver=True,
    )


def _exigir_la_web() -> None:
    if clientes_nodo.en_un_nodo():
        raise SoloEnElCentral(ediciones_en_conflicto.MENSAJE_SOLO_EN_LA_WEB)


def _traducir(exc: Exception) -> HTTPException:
    if isinstance(exc, EdicionNoEncontrada):
        return HTTPException(404, str(exc))
    if isinstance(exc, EdicionYaResuelta):
        return HTTPException(409, {"codigo": "ya_resuelta", "mensaje": str(exc)})
    if isinstance(exc, CambioEnLaWeb):
        return HTTPException(409, {"codigo": "cambio_en_la_web", "mensaje": str(exc)})
    if isinstance(exc, EdicionNoAplicable):
        return HTTPException(409, {"codigo": "no_se_pudo_aplicar", "mensaje": str(exc)})
    return HTTPException(422, str(exc))


@router.get("", response_model=list[EdicionSalida])
def listar(sesion: Session = Depends(obtener_sesion), _: object = Depends(require_staff)):
    """Las ediciones de clientes que esperan a alguien, de la más vieja a la más nueva: las que chocan (hay que
    elegir) y las que ya no chocan (`ya_no_choca`: se aplican o se descartan). En la PC del club, vacía (la revisión
    es de la web)."""
    if clientes_nodo.en_un_nodo():
        return []
    return [_a_salida(e) for e in ediciones_en_conflicto.listar(sesion)]


@router.get("/{operacion_id}", response_model=EdicionSalida)
def ver(operacion_id: str, sesion: Session = Depends(obtener_sesion), _: object = Depends(require_staff)):
    """Una edición con los dos valores de cada campo, para elegir (o para aplicar, si ya no choca). 409
    `solo_en_el_central` en la PC del club."""
    _exigir_la_web()
    try:
        return _a_salida(ediciones_en_conflicto.detalle(sesion, operacion_id))
    except EdicionNoEncontrada as exc:
        raise _traducir(exc) from exc
    except EdicionYaResuelta as exc:
        raise _traducir(exc) from exc


@router.post("/{operacion_id}/resolver", response_model=ResultadoSalida)
def resolver(
    operacion_id: str,
    datos: Resolucion,
    sesion: Session = Depends(obtener_sesion),
    usuario: dict = Depends(require_staff),
):
    """Aplica lo elegido en una sola transacción y da la edición por resuelta (si ya no choca, `elecciones` va vacío y
    se aplica lo que falta). Resolverla dos veces da 409 `ya_resuelta` y no aplica nada otra vez; si el cliente cambió
    de nuevo en la web, 409 `cambio_en_la_web`. Sólo en la web (409 `solo_en_el_central` en la PC del club)."""
    _exigir_la_web()
    try:
        crudo = usuario.get("id")
        aplicados = ediciones_en_conflicto.resolver(
            sesion,
            operacion_id,
            dict(datos.elecciones),
            datos.vistos,
            usuario=str(usuario.get("username") or usuario.get("name") or "desconocido"),
            usuario_id=int(crudo) if crudo is not None and str(crudo).isdigit() else None,
        )
    except (EdicionNoEncontrada, EdicionYaResuelta, EleccionInvalida, CambioEnLaWeb, EdicionNoAplicable) as exc:
        sesion.rollback()
        raise _traducir(exc) from exc
    sesion.commit()
    return ResultadoSalida(aplicados=aplicados)


@router.post("/{operacion_id}/descartar", response_model=DescarteSalida)
def descartar(
    operacion_id: str,
    datos: Descarte,
    sesion: Session = Depends(obtener_sesion),
    usuario: dict = Depends(require_staff),
):
    """Cierra la edición sin aplicarla: el cliente queda como está en la web. **No tiene vuelta atrás.** Mismas
    garantías que `resolver`: 409 `ya_resuelta` si otra persona llegó antes, 409 `cambio_en_la_web` si el cliente
    cambió desde que se mostró la pantalla (puede haber vuelto a chocar). Sólo en la web (409 `solo_en_el_central` en
    la PC del club)."""
    _exigir_la_web()
    try:
        ediciones_en_conflicto.descartar(
            sesion,
            operacion_id,
            datos.vistos,
            usuario=str(usuario.get("username") or usuario.get("name") or "desconocido"),
        )
    except (EdicionNoEncontrada, EdicionYaResuelta, EleccionInvalida, CambioEnLaWeb) as exc:
        sesion.rollback()
        raise _traducir(exc) from exc
    return DescarteSalida()
