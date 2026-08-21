"""Reservas, bloqueos y series.

El router valida, delega y traduce errores a códigos. Las reglas están en
`app/servicios/reservas.py`.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin, require_staff
from app.db import obtener_sesion
from app.models.enums import ESTADOS_QUE_OCUPAN, EstadoReserva
from app.models.maestros import Cancha, Cliente
from app.models.reservas import Reserva, Serie
from app.schemas.reservas import (
    BloqueoEntrada,
    CambioDeEstado,
    ReservaEntrada,
    ReservaSalida,
    SerieCreada,
    SerieEntrada,
    SerieSalida,
)
from app.servicios import disponibilidad, tarifario
from app.servicios import facturacion as servicio_facturacion
from app.servicios import reservas as servicio
from app.tiempo import TZ, ahora

router = APIRouter(prefix="/api/reservas", tags=["reservas"])


def _traducir(fn):
    """Las excepciones del servicio, a códigos HTTP. En un solo lugar."""

    def envuelto(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except servicio.Superpuesta as exc:
            raise HTTPException(409, str(exc)) from exc
        except servicio.TransicionInvalida as exc:
            raise HTTPException(409, str(exc)) from exc
        except tarifario.SinTarifa as exc:
            # 422 y no 500: falta un dato que el operador tiene que cargar, no
            # se rompió nada.
            raise HTTPException(422, str(exc)) from exc
        except servicio.ReservaInvalida as exc:
            raise HTTPException(400, str(exc)) from exc

    return envuelto


@router.get("", response_model=list[ReservaSalida])
def listar(
    desde: datetime | None = None,
    hasta: datetime | None = None,
    cancha_id: int | None = None,
    sucursal_id: int | None = None,
    solo_ocupadas: bool = True,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    consulta = select(Reserva).join(Cancha, Reserva.cancha_id == Cancha.id)
    if desde is not None:
        consulta = consulta.where(Reserva.termina_at > desde)
    if hasta is not None:
        consulta = consulta.where(Reserva.comienza_at < hasta)
    if cancha_id is not None:
        consulta = consulta.where(Reserva.cancha_id == cancha_id)
    if sucursal_id is not None:
        consulta = consulta.where(Cancha.sucursal_id == sucursal_id)
    if solo_ocupadas:
        consulta = consulta.where(Reserva.estado.in_(ESTADOS_QUE_OCUPAN))
    return list(sesion.scalars(consulta.order_by(Reserva.comienza_at)).all())


@router.get("/{reserva_id}", response_model=ReservaSalida)
def obtener(
    reserva_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None:
        raise HTTPException(404, "No existe esa reserva.")
    return reserva


@router.post("", response_model=ReservaSalida, status_code=201)
def crear(
    datos: ReservaEntrada,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    reserva = _traducir(servicio.crear)(
        sesion,
        cancha_id=datos.cancha_id,
        cliente_id=datos.cliente_id,
        comienza_at=_con_zona(datos.comienza_at),
        duracion_min=datos.duracion_min,
        estado=datos.estado,
        origen=datos.origen,
        precio=datos.precio,
        observaciones=datos.observaciones,
    )
    sesion.commit()
    sesion.refresh(reserva)
    return reserva


@router.post("/bloqueos", response_model=ReservaSalida, status_code=201)
def bloquear(
    datos: BloqueoEntrada,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    bloqueo = _traducir(servicio.crear_bloqueo)(
        sesion,
        cancha_id=datos.cancha_id,
        comienza_at=_con_zona(datos.comienza_at),
        termina_at=_con_zona(datos.termina_at),
        motivo=datos.motivo,
    )
    sesion.commit()
    sesion.refresh(bloqueo)
    return bloqueo


@router.post("/{reserva_id}/estado", response_model=ReservaSalida)
def cambiar_estado(
    reserva_id: int,
    datos: CambioDeEstado,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    reserva = _traducir(servicio.cambiar_estado)(
        sesion, reserva_id, datos.estado, datos.motivo
    )
    sesion.commit()
    sesion.refresh(reserva)
    return reserva


@router.post("/vencer-provisorias")
def vencer(
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
) -> dict[str, int]:
    """Cancela las provisorias vencidas. Lo llama un cron, o el operador.

    Es un endpoint y no sólo una tarea de fondo para que se pueda **ver** que
    funciona: un barrido que sólo corre en un scheduler es un barrido del que
    nadie sabe si corrió.
    """
    cuantas = servicio.vencer_provisorias(sesion)
    sesion.commit()
    return {"canceladas": cuantas}


class FacturaSalida(BaseModel):
    id: int
    tipo: int
    punto_venta: int
    numero: int
    fecha: str
    total: float
    #: Vacío mientras ARCA no lo haya dado. **No es un error**: la factura
    #: existe y lo que falta es el CAE, que se reintenta.
    cae: str = ""
    cae_vto: str = ""


@router.post("/{reserva_id}/facturar", response_model=FacturaSalida, status_code=201)
async def facturar(
    reserva_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
):
    """Emite el comprobante de una reserva.

    🔑 **Admin y no staff.** El encargado de mostrador toma reservas y cobra; qué
    se le factura a quién es del dueño. Es la misma línea que separa el alta de
    canchas del alta de clientes en este producto.
    """
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None:
        raise HTTPException(404, "no existe esa reserva")
    cliente = sesion.get(Cliente, reserva.cliente_id) if reserva.cliente_id else None
    try:
        factura = await servicio_facturacion.facturar_reserva(reserva, cliente)
    except servicio_facturacion.FacturacionNoConfigurada as e:
        raise HTTPException(503, str(e)) from e
    except servicio_facturacion.ReservaYaFacturada as e:
        # 409 y no 400: el pedido está bien formado, lo que pasa es que el
        # estado del recurso no lo admite.
        raise HTTPException(409, str(e)) from e
    except servicio_facturacion.SinPrecio as e:
        raise HTTPException(422, str(e)) from e
    sesion.commit()
    return FacturaSalida(
        id=factura["id"], tipo=factura["tipo"], punto_venta=factura["punto_venta"],
        numero=factura["numero"], fecha=str(factura["fecha"]),
        total=float(factura["total"]), cae=factura.get("cae") or "",
        cae_vto=factura.get("cae_vto") or "",
    )


@router.get("/{reserva_id}/factura", response_model=FacturaSalida | None)
def ver_factura(
    reserva_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """El comprobante de una reserva, o `null`. Lo puede ver el mostrador."""
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None:
        raise HTTPException(404, "no existe esa reserva")
    factura = servicio_facturacion.factura_de_reserva(reserva)
    if factura is None:
        return None
    return FacturaSalida(
        id=factura["id"], tipo=factura["tipo"], punto_venta=factura["punto_venta"],
        numero=factura["numero"], fecha=str(factura["fecha"]),
        total=float(factura["total"]), cae=factura.get("cae") or "",
        cae_vto=factura.get("cae_vto") or "",
    )


@router.post("/series", response_model=SerieCreada, status_code=201)
def crear_serie(
    datos: SerieEntrada,
    hasta: date | None = Query(default=None),
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Una cancha fija. Devuelve las reservas creadas **y las salteadas**."""
    serie = Serie(**datos.model_dump())
    sesion.add(serie)
    sesion.flush()
    creadas, salteadas = servicio.materializar_serie(sesion, serie, hasta)
    sesion.commit()
    return SerieCreada(
        serie=SerieSalida.model_validate(serie, from_attributes=True),
        creadas=[ReservaSalida.model_validate(r, from_attributes=True) for r in creadas],
        salteadas=salteadas,
    )


@router.get("/series/listado", response_model=list[SerieSalida])
def listar_series(
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    # 🔴 `/series/listado` y no `/series`, y el motivo es el `GET /{reserva_id}`
    # declarado más arriba: matchea **cualquier** segmento único, así que un
    # `GET /api/reservas/series` entraría por ahí con `reserva_id="series"` y
    # contestaría un 422 confuso en vez de la lista. Con dos segmentos no hay
    # ambigüedad, y la ruta deja de depender del orden de declaración.
    return list(sesion.scalars(select(Serie).order_by(Serie.dia_semana, Serie.hora)).all())


def _con_zona(valor: datetime) -> datetime:
    """Un datetime sin offset se toma como hora local del complejo.

    🔴 Es lo contrario de lo que hace PostgreSQL, que asume UTC — y esa
    diferencia son tres horas. Un cliente que manda `2026-08-20T20:00:00` sin
    offset quiere decir las 20:00 del complejo: interpretarlo como UTC pone la
    reserva a las 17:00 y el operador ve un turno que nunca cargó.
    """
    return valor if valor.tzinfo is not None else valor.replace(tzinfo=TZ)


@router.get("/agenda/proximas", response_model=list[ReservaSalida])
def proximas(
    sucursal_id: int,
    limite: int = Query(default=20, ge=1, le=200),
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    return disponibilidad.proximas(sesion, sucursal_id, ahora(), limite)


@router.get("/estados/catalogo")
def catalogo_de_estados() -> dict[str, list[str]]:
    """Los estados y cuáles ocupan la cancha.

    Lo sirve la API en vez de que el frontend lleve su propia copia: la lista de
    los que ocupan es la misma que la del constraint, y dos copias de una lista
    que tiene que coincidir terminan no coincidiendo.
    """
    return {
        "todos": [estado.value for estado in EstadoReserva],
        "ocupan": [estado.value for estado in ESTADOS_QUE_OCUPAN],
    }
