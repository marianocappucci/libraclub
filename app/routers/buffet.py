"""El buffet: catálogo, stock y consumo cargado a la cancha."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin, require_staff
from app.db import obtener_sesion
from app.models.reservas import Reserva
from app.servicios import buffet as servicio
from app.servicios import caja as servicio_caja
from app.servicios import facturacion

router = APIRouter(prefix="/api/buffet", tags=["buffet"])


class ProductoEntrada(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    precio: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    costo: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    stock_minimo: Decimal = Field(default=Decimal("0"), ge=0)
    activo: bool = True


class ProductoSalida(BaseModel):
    item_id: int
    nombre: str
    precio: float
    activo: bool
    stock: float
    stock_minimo: float
    bajo_minimo: bool


class AjusteEntrada(BaseModel):
    item_id: int
    #: Positiva repone, negativa descuenta (rotura, vencido). Cero no se acepta:
    #: un ajuste que no ajusta nada sólo ensucia el historial.
    cantidad: Decimal
    motivo: str = Field(min_length=1, max_length=200)


class LineaEntrada(BaseModel):
    item_id: int
    cantidad: Decimal = Field(gt=0)


class ConsumoEntrada(BaseModel):
    lineas: list[LineaEntrada] = Field(min_length=1)
    #: `null` = venta de mostrador, que se cobra en el acto.
    reserva_id: int | None = None
    #: Sólo para la venta de mostrador: cómo se cobra. Va a la caja del turno.
    medio_pago: str | None = None


class VentaSalida(BaseModel):
    id: int
    numero: str
    total: float
    reserva_id: int | None = None


def _exigir_base() -> None:
    if not facturacion.hay_base():
        raise HTTPException(
            503,
            "El buffet no está configurado en esta instancia: falta "
            "LIBRACLUB_LIBRACORE_DATABASE_URL.",
        )


@router.get("/productos", response_model=list[ProductoSalida])
def productos(sucursal_id: int, _: object = Depends(require_staff)):
    """El catálogo con el stock de esa sucursal. De mostrador: es lo que se ve
    para vender."""
    _exigir_base()
    return [ProductoSalida(**{**f, "precio": float(f["precio"]),
                              "stock": float(f["stock"]),
                              "stock_minimo": float(f["stock_minimo"])})
            for f in servicio.stock_de(sucursal_id)]


@router.post("/productos", response_model=ProductoSalida, status_code=201)
def crear_producto(
    datos: ProductoEntrada, sucursal_id: int, _: object = Depends(require_admin)
):
    """Alta de producto. De admin: define precio, que es plata."""
    _exigir_base()
    item = servicio.guardar_producto(
        item_id=None, nombre=datos.nombre, precio=datos.precio, costo=datos.costo,
        stock_minimo=datos.stock_minimo, activo=datos.activo,
    )
    return _fila(sucursal_id, item.id)


@router.put("/productos/{item_id}", response_model=ProductoSalida)
def editar_producto(
    item_id: int,
    datos: ProductoEntrada,
    sucursal_id: int,
    _: object = Depends(require_admin),
):
    _exigir_base()
    try:
        servicio.guardar_producto(
            item_id=item_id, nombre=datos.nombre, precio=datos.precio,
            costo=datos.costo, stock_minimo=datos.stock_minimo, activo=datos.activo,
        )
    except servicio.ProductoInexistente as e:
        raise HTTPException(404, str(e)) from e
    return _fila(sucursal_id, item_id)


def _fila(sucursal_id: int, item_id: int) -> ProductoSalida:
    fila = next(f for f in servicio.stock_de(sucursal_id) if f["item_id"] == item_id)
    return ProductoSalida(**{**fila, "precio": float(fila["precio"]),
                             "stock": float(fila["stock"]),
                             "stock_minimo": float(fila["stock_minimo"])})


@router.post("/ajustes", response_model=ProductoSalida)
def ajustar(
    datos: AjusteEntrada, sucursal_id: int, usuario: dict = Depends(require_staff)
):
    """Reposición o baja de stock.

    De **mostrador**: el que recibe la entrega del proveedor y el que ve que se
    rompió una botella es el encargado. Pedirle admin haría que no se cargue.
    """
    _exigir_base()
    try:
        servicio.ajustar_stock(
            sucursal_id=sucursal_id, item_id=datos.item_id, cantidad=datos.cantidad,
            motivo=datos.motivo, usuario_id=int(usuario["id"]),
        )
    except servicio.ProductoInexistente as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return _fila(sucursal_id, datos.item_id)


@router.post("/consumos", response_model=VentaSalida, status_code=201)
def consumir(
    datos: ConsumoEntrada,
    sucursal_id: int,
    sesion: Session = Depends(obtener_sesion),
    usuario: dict = Depends(require_staff),
):
    """Registra un consumo: descuenta stock y, si es de mostrador, cobra.

    🔑 **Con `reserva_id` NO se cobra acá.** El consumo queda colgado de la
    reserva y se cobra cuando se cobra el turno, en una sola operación y con una
    sola factura. Cobrarlo dos veces es exactamente lo que este diseño evita.
    """
    _exigir_base()
    if datos.reserva_id is not None:
        reserva = sesion.get(Reserva, datos.reserva_id)
        if reserva is None:
            raise HTTPException(404, "no existe esa reserva")
        if reserva.factura_id is not None:
            # Si ya se facturó, el consumo nuevo no entraría en ese comprobante
            # y quedaría cobrado sin respaldo. Se corta.
            raise HTTPException(
                409, "esa reserva ya está facturada: el consumo no entraría en el comprobante"
            )

    try:
        venta = servicio.registrar_consumo(
            sucursal_id=sucursal_id,
            lineas=[(x.item_id, x.cantidad) for x in datos.lineas],
            usuario_id=int(usuario["id"]),
            reserva_id=datos.reserva_id,
        )
    except servicio.ProductoInexistente as e:
        raise HTTPException(404, str(e)) from e
    except (servicio.VentaVacia, ValueError) as e:
        raise HTTPException(422, str(e)) from e

    if datos.reserva_id is None:
        if not datos.medio_pago:
            raise HTTPException(422, "una venta de mostrador necesita medio de pago")
        try:
            servicio_caja.cobrar(
                usuario, venta.total, f"Buffet {venta.number}", datos.medio_pago,
                referencia=f"buffet-{venta.id}",
            )
        except servicio_caja.SinTurnoAbierto as e:
            raise HTTPException(409, str(e)) from e
        except servicio_caja.MedioDePagoInvalido as e:
            raise HTTPException(422, str(e)) from e

    return VentaSalida(
        id=venta.id, numero=venta.number, total=float(venta.total),
        reserva_id=datos.reserva_id,
    )


@router.get("/reservas/{reserva_id}/consumos")
def consumos_de(reserva_id: int, _: object = Depends(require_staff)):
    """Lo que se consumió durante ese turno, para mostrarlo en el detalle."""
    _exigir_base()
    ventas = servicio.consumos_de_reserva(reserva_id)
    return {
        "total": float(sum((v.total for v in ventas), Decimal("0"))),
        "lineas": [
            {
                "descripcion": linea.description_snapshot,
                "cantidad": float(linea.quantity),
                "precio_unitario": float(linea.unit_price),
                "importe": float(Decimal(linea.quantity) * Decimal(linea.unit_price)),
            }
            for venta in ventas
            for linea in venta.items
        ],
    }
