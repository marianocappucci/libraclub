"""ABM de sucursales, canchas, clientes, feriados y tarifas.

Cinco maestros con la misma forma, armados por una fábrica en vez de copiados
cinco veces: el ABM que se copia es donde aparece la validación que sólo está en
cuatro de los cinco.
"""

# 🔴 **Sin `from __future__ import annotations`, y es a propósito.**
#
# Con ese import, PEP 563 convierte todas las anotaciones en strings y FastAPI
# las resuelve contra los **globals del módulo**. Acá `entrada` es una variable
# local de la fábrica, así que no la encuentra, y en vez de fallar decide que
# `datos` es un **query param**: el endpoint contesta
# `422 {"loc": ["query", "datos"]}` a un POST con cuerpo perfectamente válido.
#
# Medido el 2026-08-20: cinco tests de API en rojo por esto, y el mensaje no
# habla de anotaciones. Sin el import, la anotación se evalúa en el `def` y es
# la clase de verdad.
from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_admin, require_staff
from app.db import obtener_sesion
from app.models.maestros import Cancha, Cliente, Feriado, Sucursal
from app.models.tarifas import Tarifa
from app.schemas.maestros import (
    CanchaEntrada,
    CanchaSalida,
    ClienteEntrada,
    ClienteSalida,
    FeriadoEntrada,
    FeriadoSalida,
    SucursalEntrada,
    SucursalSalida,
    TarifaEntrada,
    TarifaSalida,
)


def _traducir_integridad(exc: IntegrityError) -> HTTPException:
    """Un choque de constraint es un 409 con el nombre del constraint.

    Se mira `constraint_name` y no el texto: el mensaje de PostgreSQL cambia
    entre versiones y se traduce con el locale del servidor, así que un `if
    "duplicate" in str(exc)` anda en el runner en inglés y falla en producción.
    """
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    nombre = getattr(diag, "constraint_name", None) or ""
    mensajes = {
        "uq_sucursales_nombre": "Ya hay una sucursal con ese nombre.",
        "uq_sucursales_punto_venta": (
            "Ese punto de venta de ARCA ya lo usa otra sucursal. Dos sucursales "
            "con el mismo punto de venta se pisan la numeración de comprobantes."
        ),
        "uq_canchas_sucursal_nombre": "Esa sucursal ya tiene una cancha con ese nombre.",
        "uq_feriados_sucursal_dia": "Ese día ya está cargado como feriado.",
    }
    return HTTPException(409, mensajes.get(nombre, "El dato choca con uno existente."))


def construir_abm(
    *,
    prefijo: str,
    etiqueta: str,
    modelo: type,
    entrada: type[BaseModel],
    salida: type[BaseModel],
    orden: Sequence,
    rol_escritura=require_admin,
) -> APIRouter:
    """Un ABM completo: listar, obtener, crear, editar y borrar.

    `rol_escritura` es `require_admin` por defecto y se baja a `require_staff`
    sólo donde el alta es **trabajo de mostrador**. Hoy es el caso de
    `clientes`: si crear un cliente pidiera admin, el encargado no podría tomarle
    la reserva a alguien que llama por primera vez — y lo que haría en la
    práctica es cargarlo todo bajo un cliente genérico, que es peor que no
    tenerlo.

    Lo que **no** se baja: sucursales, canchas, tarifas y feriados. Ahí el alta
    define plata y configuración, no operación.
    """
    router = APIRouter(prefix=f"/api/{prefijo}", tags=[etiqueta])

    @router.get("", response_model=list[salida])
    def listar(
        sesion: Session = Depends(obtener_sesion),
        _: object = Depends(require_staff),
    ):
        return list(sesion.scalars(select(modelo).order_by(*orden)).all())

    @router.get("/{item_id}", response_model=salida)
    def obtener(
        item_id: int,
        sesion: Session = Depends(obtener_sesion),
        _: object = Depends(require_staff),
    ):
        item = sesion.get(modelo, item_id)
        if item is None:
            raise HTTPException(404, f"No existe {etiqueta} con id {item_id}.")
        return item

    @router.post("", response_model=salida, status_code=201)
    def crear(
        datos: entrada,
        sesion: Session = Depends(obtener_sesion),
        _: object = Depends(rol_escritura),
    ):
        item = modelo(**datos.model_dump())
        sesion.add(item)
        try:
            sesion.commit()
        except IntegrityError as exc:
            sesion.rollback()
            raise _traducir_integridad(exc) from exc
        sesion.refresh(item)
        return item

    @router.put("/{item_id}", response_model=salida)
    def editar(
        item_id: int,
        datos: entrada,
        sesion: Session = Depends(obtener_sesion),
        _: object = Depends(rol_escritura),
    ):
        item = sesion.get(modelo, item_id)
        if item is None:
            raise HTTPException(404, f"No existe {etiqueta} con id {item_id}.")
        for campo, valor in datos.model_dump().items():
            setattr(item, campo, valor)
        try:
            sesion.commit()
        except IntegrityError as exc:
            sesion.rollback()
            raise _traducir_integridad(exc) from exc
        sesion.refresh(item)
        return item

    @router.delete("/{item_id}", status_code=204)
    def borrar(
        item_id: int,
        sesion: Session = Depends(obtener_sesion),
        _: object = Depends(rol_escritura),
    ):
        item = sesion.get(modelo, item_id)
        if item is None:
            raise HTTPException(404, f"No existe {etiqueta} con id {item_id}.")
        try:
            sesion.delete(item)
            sesion.commit()
        except IntegrityError as exc:
            # 🔴 Las FK de canchas y clientes son `RESTRICT`, no `CASCADE`: borrar
            # un cliente **no** puede llevarse su historial de reservas por
            # delante. El operador que quiere sacarlo de las listas lo da de baja
            # (`activo = false`), que es lo que en realidad quiere hacer.
            sesion.rollback()
            raise HTTPException(
                409,
                "No se puede borrar: tiene reservas u otros datos asociados. "
                "Dalo de baja en vez de borrarlo.",
            ) from exc
        return None

    return router


sucursales = construir_abm(
    prefijo="sucursales", etiqueta="sucursales",
    modelo=Sucursal, entrada=SucursalEntrada, salida=SucursalSalida,
    orden=(Sucursal.nombre,),
)

canchas = construir_abm(
    prefijo="canchas", etiqueta="canchas",
    modelo=Cancha, entrada=CanchaEntrada, salida=CanchaSalida,
    orden=(Cancha.sucursal_id, Cancha.orden, Cancha.nombre),
)

clientes = construir_abm(
    prefijo="clientes", etiqueta="clientes",
    modelo=Cliente, entrada=ClienteEntrada, salida=ClienteSalida,
    orden=(Cliente.nombre,),
    # El único maestro que un encargado puede dar de alta: es lo que hace posible
    # tomarle la reserva a alguien que llama por primera vez. Ver `construir_abm`.
    rol_escritura=require_staff,
)

feriados = construir_abm(
    prefijo="feriados", etiqueta="feriados",
    modelo=Feriado, entrada=FeriadoEntrada, salida=FeriadoSalida,
    orden=(Feriado.dia,),
)

tarifas = construir_abm(
    prefijo="tarifas", etiqueta="tarifas",
    modelo=Tarifa, entrada=TarifaEntrada, salida=TarifaSalida,
    orden=(Tarifa.sucursal_id, Tarifa.hora_desde),
)

TODOS = (sucursales, canchas, clientes, feriados, tarifas)
