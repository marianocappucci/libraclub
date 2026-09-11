"""El buffet: catálogo, stock, consumo cargado a la cancha y venta de mostrador.

La venta de mostrador se cobra en el acto y por eso vive acá el cobro: en
efectivo o cualquier medio anotado a mano, y **con el QR de MercadoPago** desde
el 2026-09-08 (ver `servicios/cobro_qr.py`, sección de la venta de buffet).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin, require_staff
from app.config import es_produccion
from app.db import obtener_sesion
from app.models.reservas import Reserva
from app.servicios import buffet as servicio
from app.servicios import caja as servicio_caja
from app.servicios import cobro_qr, facturacion
from app.servicios import pagos as servicio_pagos

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


class EstadoDelQr(BaseModel):
    #: `aprobado`, `pendiente`, `rechazado`, `sin_orden`.
    estado: str
    payment_id: str | None = None
    #: Siempre `None` en una venta de buffet: no se factura sola. Va igual para
    #: que la pantalla pueda usar el mismo tipo que el poll del turno.
    factura_id: int | None = None


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


# ── El cobro con QR de la venta de mostrador ─────────────────────────────
#
# 🔑 **Tres rutas y ninguna imagen**: el QR es el cartel impreso de la caja, que
# no cambia nunca; lo que cambia es cuánto cobra. Espejan las tres de
# `routers/reservas.py` (`mp-qr`, `DELETE mp-qr`, `mp-status`) porque son la
# misma operación sobre otra cosa que se cobra.
#
# ⚠️ **La disponibilidad se pregunta a `GET /api/reservas/mp/estado`**, que ya
# existe y no se duplica acá: si esta instancia tiene las tres credenciales
# cargadas es un hecho **de la instancia**, no del turno ni de la venta. Un
# segundo endpoint que lo calcule igual es una segunda puerta al mismo cuarto.
#
# 🔴 **Las tres son `def` y no `async def`, a propósito.** Las corrutinas de
# `servicios/cobro_qr.py` son `async` sólo en los bordes: lo que esperan de
# MercadoPago va por `httpx` asincrónico, pero entre medio leen y escriben la
# base con la `Session` sincrónica. uvicorn corre con **un solo proceso**: con
# `await` desde el loop, cada consulta frenaba la instancia entera —y el poll
# pega cada 3 segundos—. Como `def` corren en el threadpool, y la corrutina va
# con `asyncio.run` en un loop propio de ese hilo: lo sincrónico bloquea a ese
# hilo y a nadie más. La firma del servicio no cambia: el arreglo va del lado
# de quien llama.


class VentaConQr(BaseModel):
    #: El borrador que quedó esperando el escaneo. Es lo que el poll consulta.
    venta_id: int
    numero: str
    referencia: str
    monto: float


@router.post("/ventas/qr", response_model=VentaConQr, status_code=201)
def poner_venta_en_el_qr(
    datos: ConsumoEntrada,
    sucursal_id: int,
    sesion: Session = Depends(obtener_sesion),
    usuario: dict = Depends(require_staff),
):
    """Deja la venta en borrador y pone su total a cobrar en el QR del mostrador.

    🔴 **El stock no se mueve acá.** La venta queda en borrador —ver
    `buffet.preparar_consumo`— y se confirma recién cuando MercadoPago acredita.
    Un QR que nadie escanea no deja stock descontado por una venta que no
    ocurrió.

    Sólo venta de mostrador: un consumo cargado a una cancha no se cobra por
    separado, se cobra con el turno y por el QR del turno.
    """
    _exigir_base()
    if datos.reserva_id is not None:
        raise HTTPException(
            422,
            "El consumo de una cancha se cobra con el turno, no por separado: "
            "usá el QR de la reserva.",
        )
    try:
        venta = servicio.preparar_consumo(
            sucursal_id=sucursal_id,
            lineas=[(x.item_id, x.cantidad) for x in datos.lineas],
            usuario_id=int(usuario["id"]),
        )
    except servicio.ProductoInexistente as e:
        raise HTTPException(404, str(e)) from e
    except (servicio.VentaVacia, ValueError) as e:
        raise HTTPException(422, str(e)) from e

    try:
        # En un loop propio de este hilo, no en el de uvicorn: ver arriba.
        pago = asyncio.run(cobro_qr.poner_venta_en_el_qr(sesion, venta))
    except cobro_qr.QrNoConfigurado as e:
        raise HTTPException(400, str(e)) from e
    except cobro_qr.NadaQueCobrar as e:
        raise HTTPException(409, str(e)) from e
    except servicio_pagos.PagoInvalido as e:
        raise HTTPException(409, str(e)) from e
    except cobro_qr.QrError as e:
        # 502: el que falló es MercadoPago, y el mensaje lleva su status y su
        # cuerpo adentro.
        raise HTTPException(502, str(e)) from e
    sesion.commit()
    return VentaConQr(
        venta_id=venta.id, numero=venta.number,
        referencia=pago.referencia, monto=float(pago.monto),
    )


@router.delete("/ventas/{venta_id}/mp-qr", status_code=204)
def bajar_venta_del_qr(
    venta_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Saca del QR la orden de esa venta: el cartel queda sin nada que cobrar.

    🔴 **Sin esto, el próximo que escanee paga las gaseosas del anterior.**
    Idempotente: sin orden pendiente no hace nada. El borrador de la venta queda
    donde está, sin stock movido y sin plata anotada.
    """
    # En un loop propio de este hilo, no en el de uvicorn: ver arriba.
    asyncio.run(cobro_qr.bajar_venta_del_qr(sesion, venta_id))
    sesion.commit()


@router.get("/ventas/{venta_id}/mp-status", response_model=EstadoDelQr)
def estado_del_qr_de_la_venta(
    venta_id: int,
    sesion: Session = Depends(obtener_sesion),
    usuario: dict = Depends(require_staff),
):
    """Si el QR de esa venta ya se pagó. Lo pollea la pantalla cada 3 segundos.

    🔑 **Es un GET con efectos**, igual que el del turno: acá es donde se
    confirma la venta —o sea, donde se mueve el stock— y donde entra el
    movimiento de caja. Idempotente: el segundo tick sale de lo ya sellado.
    """
    _exigir_base()
    try:
        # En un loop propio de este hilo, no en el de uvicorn: ver arriba.
        estado = asyncio.run(cobro_qr.estado_del_cobro_de_venta(sesion, venta_id, usuario))
    except cobro_qr.QrNoConfigurado as e:
        raise HTTPException(400, str(e)) from e
    except servicio_caja.SinTurnoAbierto as e:
        # El pago **ya quedó sellado como aprobado** cuando esto salta, así que
        # el 409 no pierde nada: el encargado abre el turno y el tick siguiente
        # confirma la venta y completa la caja.
        raise HTTPException(409, str(e)) from e
    except cobro_qr.QrError as e:
        raise HTTPException(502, str(e)) from e
    sesion.commit()
    return EstadoDelQr(**estado)


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


# ── El simulador del cobro por QR, sólo fuera de producción ──────────────


def construir_router_de_simulacion_qr(entorno: str) -> APIRouter | None:
    """`POST /api/buffet/ventas/qr/simular`, **si esto no es producción**.

    🔴 **Es lo único que separa dev de regalar mercadería.** Este endpoint
    confirma una venta y anota el ingreso sin que haya entrado un peso: montado
    en la instancia de un complejo, cualquiera con la URL vacía el buffet. Por
    eso devuelve `None` en producción y el router **no se monta** — no alcanza un
    `if` adentro del handler. Mismo criterio, y misma redacción, que
    `reservas.construir_router_de_simulacion_qr`.

    🔑 **Llama a las MISMAS funciones que el camino real**: `preparar_consumo`,
    `crear_pago_de_buffet`, `aplicar_pago_aprobado` y `_completar_venta`. Lo
    único que se saltea es lo que no se puede tener sin credenciales —crear la
    orden en MercadoPago y consultarla—, y por eso cubre los dos pasos: sin
    credenciales `poner_venta_en_el_qr` falla al crear la orden, así que no llega
    a existir el pago que después habría que sellar.

    ⚠️ **Tiene su propio sondeo y no reusa el de `/api/reservas`.** Los dos
    routers se montan con el mismo gate, así que hoy están o no están juntos —
    pero preguntar por uno para ofrecer el botón del otro es medir una cosa
    distinta de la que se va a llamar, y el día que se separen la pantalla ofrece
    un botón que no existe.
    """
    if es_produccion(entorno):
        return None

    simulador = APIRouter(prefix="/api/buffet", tags=["buffet"])

    @simulador.get("/mp-qr/simulacion")
    def hay_simulador(_: object = Depends(require_staff)):
        """Cómo la pantalla se entera de que puede ofrecer el botón de simular.

        Vive adentro de este router y ése es todo el diseño: si el simulador no
        se montó, esta ruta tampoco existe y el frontend recibe un 404. No hay
        criterio que repetir.
        """
        return {"disponible": True}

    @simulador.post("/ventas/qr/simular")
    def simular_cobro_de_venta(
        datos: ConsumoEntrada,
        sucursal_id: int,
        sesion: Session = Depends(obtener_sesion),
        usuario: dict = Depends(require_staff),
    ):
        """Hace de cuenta que alguien escaneó el QR y pagó la venta. Dev y demo.

        Deja lo mismo que el cobro real: la venta confirmada —con su stock
        descontado— el pago aprobado y el movimiento en la caja del turno
        abierto.
        """
        _exigir_base()
        if datos.reserva_id is not None:
            raise HTTPException(422, "El consumo de una cancha se cobra con el turno.")
        try:
            venta = servicio.preparar_consumo(
                sucursal_id=sucursal_id,
                lineas=[(x.item_id, x.cantidad) for x in datos.lineas],
                usuario_id=int(usuario["id"]),
            )
        except servicio.ProductoInexistente as e:
            raise HTTPException(404, str(e)) from e
        except (servicio.VentaVacia, ValueError) as e:
            raise HTTPException(422, str(e)) from e

        try:
            pago = servicio_pagos.crear_pago_de_buffet(
                sesion, venta.id, Decimal(str(venta.total))
            )
        except servicio_pagos.PagoInvalido as e:
            raise HTTPException(409, str(e)) from e

        servicio_pagos.aplicar_pago_aprobado(
            sesion, pago, payment_id=f"simulado-{pago.id}", estado_mp="approved"
        )
        try:
            resultado = cobro_qr._completar_venta(sesion, pago, usuario)
        except servicio_caja.SinTurnoAbierto as e:
            # 🔑 Mismo 409 que el cobro real: sin caja abierta la plata quedaría
            # fuera del arqueo, y el simulador no es excusa para saltearlo.
            raise HTTPException(409, str(e)) from e
        sesion.commit()
        return {
            **resultado, "simulado": True,
            "venta_id": venta.id, "numero": venta.number,
            "monto": float(venta.total),
        }

    return simulador
