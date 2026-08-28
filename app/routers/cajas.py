"""Las cajas: los mostradores de cada sucursal.

Una caja es un cajón físico, y vive en una sede. Una sede puede tener más de una
—el mostrador y el buffet son dos cajones distintos—, que es la decisión que tomó
el humano el 2026-08-28.

🔑 **El turno se abre SOBRE una caja**, y el arqueo del cierre es el de ese
cajón. Sin eso, dos personas en dos sedes distintas arquean contra el mismo
montón y ningún reporte por sede es posible.

🔴 **Las cajas viven en la base de LibraCore y las sucursales en la del
dominio**, así que `sucursal_id` es un entero sin FK. Es el mismo caso que
`reservas.factura_id` — ver `servicios/facturacion.py`.

Todo de admin: dar de alta un mostrador es configurar el complejo, no operar. El
mostrador elige entre las que existen, no las crea.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from libracore import medios_pago
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin, require_staff
from app.db import obtener_sesion
from app.models.maestros import Sucursal
from app.routers.facturacion import exigir_base
from app.servicios import caja as servicio

router = APIRouter(prefix="/api/cajas", tags=["cajas"])


class CajaEntrada(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    descripcion: str = ""
    #: Los medios que ESTE mostrador acepta. Vacío = todos los del producto.
    medios_pago: list[str] = []


class CajaNueva(CajaEntrada):
    sucursal_id: int


class CajaEditada(CajaEntrada):
    activo: bool = True


class CajaSalida(BaseModel):
    id: int
    nombre: str
    descripcion: str = ""
    medios_pago: list[str] = []
    activo: bool = True
    es_default: bool = False
    sucursal_id: int | None = None


def _salida(c: dict) -> CajaSalida:
    return CajaSalida(
        id=c["id"], nombre=c["nombre"], descripcion=c.get("descripcion") or "",
        medios_pago=c.get("medios_pago") or [], activo=bool(c.get("activo", 1)),
        es_default=bool(c.get("es_default", 0)), sucursal_id=c.get("sucursal_id"),
    )


@router.get("/medios-disponibles")
def medios_disponibles(_: object = Depends(require_staff)) -> list[dict]:
    """Los medios que este producto admite, para el selector del alta.

    🔑 Es el subconjunto de este producto y no el vocabulario entero del motor:
    un complejo no cobra con cheque ni con Cuenta DNI, y ofrecer un medio que
    después el cobro rechaza con un 422 es peor que no ofrecerlo.
    """
    return [
        {"valor": m, "etiqueta": medios_pago.label(m)} for m in servicio.MEDIOS_PAGO
    ]


@router.get("", response_model=list[CajaSalida])
def listar(
    sucursal_id: int,
    _: object = Depends(require_staff),
) -> list[CajaSalida]:
    """Los mostradores de una sede. Lo lee el mostrador: es lo que elige al abrir."""
    exigir_base()
    return [_salida(c) for c in servicio.cajas_de(sucursal_id)]


@router.post("", response_model=CajaSalida, status_code=201)
def crear(
    datos: CajaNueva,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
) -> CajaSalida:
    exigir_base()
    if sesion.get(Sucursal, datos.sucursal_id) is None:
        raise HTTPException(404, "no existe esa sucursal")
    try:
        return _salida(servicio.crear_caja(
            datos.nombre.strip(), datos.descripcion.strip(),
            datos.medios_pago, datos.sucursal_id,
        ))
    except servicio.MedioDePagoInvalido as e:
        raise HTTPException(422, str(e)) from e


@router.put("/{caja_id}", response_model=CajaSalida)
def editar(
    caja_id: int,
    datos: CajaEditada,
    _: object = Depends(require_admin),
) -> CajaSalida:
    exigir_base()
    if servicio.caja_de(caja_id) is None:
        raise HTTPException(404, "no existe esa caja")
    try:
        return _salida(servicio.actualizar_caja(
            caja_id, datos.nombre.strip(), datos.descripcion.strip(),
            datos.medios_pago, datos.activo,
        ))
    except servicio.MedioDePagoInvalido as e:
        raise HTTPException(422, str(e)) from e


@router.delete("/{caja_id}", status_code=204)
def borrar(caja_id: int, _: object = Depends(require_admin)) -> None:
    """Baja de un mostrador.

    El motor la rechaza si tiene movimientos o si es la caja por defecto, y los
    dos mensajes explican por qué: borrar una caja con movimientos dejaría
    arqueos apuntando a nada.
    """
    exigir_base()
    if servicio.caja_de(caja_id) is None:
        raise HTTPException(404, "no existe esa caja")
    try:
        servicio.borrar_caja(caja_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
