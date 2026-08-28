"""Reservas, bloqueos y series.

El router valida, delega y traduce errores a códigos. Las reglas están en
`app/servicios/reservas.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
    SalteadaSalida,
    SerieCreada,
    SerieEnLista,
    SerieEntrada,
    SerieSalida,
)
from app.servicios import buffet as servicio_buffet
from app.servicios import caja as servicio_caja
from app.servicios import cobro_qr, disponibilidad, tarifario
from app.servicios import facturacion as servicio_facturacion
from app.servicios import pagos as servicio_pagos
from app.servicios import reservas as servicio
from app.servicios.caja import SinTurnoAbierto
from app.tiempo import TZ, a_local, ahora

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
        except servicio.FueraDelHorario as exc:
            # 422 y no 400: el pedido está bien formado y el dato es corregible
            # —otra hora, u otro horario de atención cargado—, igual que
            # `SinTarifa`. Un 400 lo leería como "el cliente mandó cualquier
            # cosa", que manda a mirar el request y no la configuración.
            raise HTTPException(422, str(exc)) from exc
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


class CobroDeTurnoEntrada(BaseModel):
    #: Cuánto entra ahora. Puede ser menos que el total: una seña es eso.
    monto: Decimal = Field(gt=0)
    medio_pago: str
    referencia_externa: str = ""


class CobroDeTurno(BaseModel):
    id: int
    fecha: str
    monto: float
    medio_pago: str
    concepto: str
    #: A qué comprobante quedó atado. `null` mientras el turno no se facturó.
    factura_id: int | None = None


class EstadoDeCobro(BaseModel):
    #: Alquiler + buffet consumido. Es el mismo número que factura el turno.
    total: float
    cobrado: float
    pendiente: float
    cobros: list[CobroDeTurno]


def _exigir_base_de_caja() -> None:
    """503 con el nombre de la variable si la instancia no tiene base de LibraCore.

    La caja vive del lado del motor. Sin esto el mostrador recibiría un error de
    conexión de psycopg, que no dice qué hay que configurar.
    """
    if not servicio_facturacion.hay_base():
        raise HTTPException(
            503,
            "La caja no está configurada en esta instancia: falta "
            "LIBRACLUB_LIBRACORE_DATABASE_URL.",
        )


def _estado_de_cobro(reserva: Reserva) -> EstadoDeCobro:
    """Cuánto vale el turno, cuánto entró y cuánto falta.

    🔑 **El total se arma igual que el del comprobante** —alquiler más buffet
    consumido— y no desde `reserva.precio` a secas. Si salieran de dos lados, la
    pantalla diría «pendiente $0» sobre un turno con tres gaseosas sin cobrar.
    """
    precio = Decimal(str(reserva.precio or 0))
    total = precio + servicio_buffet.total_consumido(reserva.id)
    cobros = servicio_caja.cobros_de_reserva(reserva.id)
    cobrado = sum((Decimal(str(c["monto"])) for c in cobros), Decimal("0"))
    return EstadoDeCobro(
        total=float(total),
        cobrado=float(cobrado),
        # `max(0, ...)`: un cobro de más no se muestra como pendiente negativo.
        pendiente=float(max(Decimal("0"), total - cobrado)),
        cobros=[
            CobroDeTurno(
                id=c["id"], fecha=str(c["fecha"]), monto=float(c["monto"]),
                medio_pago=c.get("medio_pago") or "", concepto=c.get("concepto") or "",
                factura_id=c.get("factura_id"),
            )
            for c in cobros
        ],
    )


@router.get("/{reserva_id}/cobros", response_model=EstadoDeCobro)
def ver_cobros(
    reserva_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Lo cobrado de un turno. De mostrador: es quien cobra."""
    _exigir_base_de_caja()
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None:
        raise HTTPException(404, "no existe esa reserva")
    return _estado_de_cobro(reserva)


@router.post("/{reserva_id}/cobros", response_model=EstadoDeCobro, status_code=201)
def cobrar_turno(
    reserva_id: int,
    datos: CobroDeTurnoEntrada,
    sesion: Session = Depends(obtener_sesion),
    usuario: dict = Depends(require_staff),
):
    """Registra plata de este turno en la caja abierta, atada a su comprobante.

    🔑 **Es lo que la pantalla de Caja no puede hacer.** Ahí el cobro se carga
    como monto más concepto libre, sin vínculo con nada: sirve para un ingreso
    suelto y deja el comprobante del turno viéndose «sin cobrar». Acá el
    movimiento nace sabiendo de qué reserva es y, si ya se facturó, contra qué
    comprobante va.

    Si todavía no se facturó, `factura_id` queda en `None` y lo completa
    `facturar_reserva` cuando se emita — ver `servicios/caja.py`.

    **No exige que el monto sea el pendiente**: una seña es un cobro parcial, y
    un vuelto mal contado es un problema del mostrador, no algo que la API tenga
    que impedir.
    """
    _exigir_base_de_caja()
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None:
        raise HTTPException(404, "no existe esa reserva")

    cancha = sesion.get(Cancha, reserva.cancha_id)
    cliente = sesion.get(Cliente, reserva.cliente_id) if reserva.cliente_id else None
    # El concepto lo arma el backend y no la pantalla: es el texto que después
    # se lee en el arqueo y en el historial de caja, y dos pantallas escribiendo
    # el suyo terminan con dos formatos para el mismo hecho.
    concepto = (
        f"Turno {a_local(reserva.comienza_at):%d-%m-%Y %H:%M}"
        f" — {cancha.nombre if cancha else 'cancha'}"
        f"{f' — {cliente.nombre}' if cliente else ''}"
    )
    try:
        servicio_caja.registrar_ingreso(
            usuario, datos.monto, concepto, datos.medio_pago,
            referencia=servicio_caja.referencia_de_cobro(reserva.id),
            factura_id=reserva.factura_id,
        )
    except servicio_caja.SinTurnoAbierto as e:
        raise HTTPException(409, str(e)) from e
    except servicio_caja.MedioDePagoInvalido as e:
        raise HTTPException(422, str(e)) from e
    return _estado_de_cobro(reserva)


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
    # El nombre de la cancha va a la línea del comprobante. Se resuelve acá y no
    # dentro del servicio para que `servicios/facturacion.py` no dependa del
    # modelo del dominio: ya depende de dos bases, alcanza.
    cancha = sesion.get(Cancha, reserva.cancha_id)
    try:
        factura = await servicio_facturacion.facturar_reserva(
            reserva, cliente, cancha.nombre if cancha else "cancha"
        )
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


# ── Cobro con QR de MercadoPago en el mostrador ──────────────────────────
#
# 🔑 **Staff y no admin, al revés que facturar.** Cobrar es lo que hace el
# encargado del mostrador todo el día; a quién se le factura qué es del dueño.
# La factura que sale sola de este cobro no rompe esa línea: el que decidió que
# se emita fue el dueño, al prender el toggle en Configuración — el encargado no
# elige nada.


class QrDisponible(BaseModel):
    #: Si la instancia tiene cargadas las tres credenciales del QR.
    disponible: bool
    #: Si al acreditarse el pago se emite la factura sola.
    auto_facturar: bool


@router.get("/mp/estado", response_model=QrDisponible)
def estado_de_mercadopago(_: object = Depends(require_staff)):
    """Si este mostrador puede cobrar por QR, y si eso factura solo.

    Lo lee la pantalla para no ofrecer un botón que únicamente puede fallar.
    **No devuelve ninguna credencial**: son tres booleanos colapsados en uno.

    La ruta va antes que `/{reserva_id}/...` en el archivo por prolijidad, pero
    no dependen del orden: `mp/estado` son dos segmentos.
    """
    return QrDisponible(
        disponible=cobro_qr.esta_configurado(),
        auto_facturar=cobro_qr.auto_facturar_prendida(),
    )


class QrPuesto(BaseModel):
    referencia: str
    monto: float


class QrEstado(BaseModel):
    #: `aprobado`, `pendiente`, `rechazado`, `sin_orden`.
    estado: str
    payment_id: str | None = None
    #: El comprobante que salió solo, si la automática está prendida.
    factura_id: int | None = None


def _reserva_y_cancha(sesion: Session, reserva_id: int) -> tuple[Reserva, str]:
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None:
        raise HTTPException(404, "no existe esa reserva")
    cancha = sesion.get(Cancha, reserva.cancha_id)
    return reserva, (cancha.nombre if cancha else "cancha")


@router.post("/{reserva_id}/mp-qr", response_model=QrPuesto, status_code=201)
async def poner_en_el_qr(
    reserva_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Pone el total del turno —cancha más buffet— a cobrar en el QR de la caja.

    No devuelve ninguna imagen: el QR es el cartel impreso del mostrador y no
    cambia nunca; lo que cambia es cuánto cobra. Ver `servicios/cobro_qr.py`.
    """
    reserva, cancha_nombre = _reserva_y_cancha(sesion, reserva_id)
    try:
        pago = await cobro_qr.poner_en_el_qr(sesion, reserva, cancha_nombre)
    except cobro_qr.QrNoConfigurado as exc:
        raise HTTPException(400, str(exc)) from exc
    except cobro_qr.SinPrecio as exc:
        raise HTTPException(422, str(exc)) from exc
    except servicio_pagos.PagoInvalido as exc:
        # 409 y no 400: el pedido está bien formado, lo que no admite la
        # operación es el estado del turno.
        raise HTTPException(409, str(exc)) from exc
    except cobro_qr.QrError as exc:
        # 502: el que falló es MercadoPago, y el mensaje lleva su status y su
        # cuerpo adentro — que es lo único que le dice al operador si se
        # equivocó de POS ID o si el problema es de ellos.
        raise HTTPException(502, str(exc)) from exc
    sesion.commit()
    return QrPuesto(referencia=pago.referencia, monto=float(pago.monto))


@router.delete("/{reserva_id}/mp-qr", status_code=204)
async def bajar_del_qr(
    reserva_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Saca del QR la orden de este turno: el cartel queda sin nada que cobrar.

    🔴 **Sin esto, el próximo que escanee paga el turno anterior.** Idempotente:
    sin orden pendiente no hace nada.
    """
    await cobro_qr.bajar_del_qr(sesion, reserva_id)
    sesion.commit()


@router.get("/{reserva_id}/mp-status", response_model=QrEstado)
async def estado_del_qr(
    reserva_id: int,
    sesion: Session = Depends(obtener_sesion),
    usuario: dict = Depends(require_staff),
):
    """Si el QR de este turno ya se pagó. Lo pollea la pantalla cada 3 segundos.

    🔑 **Es un GET con efectos**, igual que el de Contalibra: acá es donde entran
    el movimiento de caja y la factura. Es idempotente — el segundo tick sale de
    lo ya sellado y no vuelve a cobrar nada.
    """
    reserva, cancha_nombre = _reserva_y_cancha(sesion, reserva_id)
    cliente = sesion.get(Cliente, reserva.cliente_id) if reserva.cliente_id else None
    try:
        estado = await cobro_qr.estado_del_cobro(
            sesion, reserva, cliente, cancha_nombre, usuario
        )
    except cobro_qr.QrNoConfigurado as exc:
        raise HTTPException(400, str(exc)) from exc
    except SinTurnoAbierto as exc:
        # Cobrar sin turno abierto deja la plata fuera del arqueo. El pago **ya
        # quedó sellado como aprobado** cuando esto salta, así que el 409 no
        # pierde nada: el encargado abre el turno y el tick siguiente completa
        # la caja y la factura.
        raise HTTPException(409, str(exc)) from exc
    except cobro_qr.QrError as exc:
        raise HTTPException(502, str(exc)) from exc
    sesion.commit()
    return QrEstado(**estado)


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
        salteadas=[
            SalteadaSalida(comienza_at=x.comienza_at, motivo=x.motivo, detalle=x.detalle)
            for x in salteadas
        ],
    )


@router.get("/series/listado", response_model=list[SerieEnLista])
def listar_series(
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    # 🔴 `/series/listado` y no `/series`, y el motivo es el `GET /{reserva_id}`
    # declarado más arriba: matchea **cualquier** segmento único, así que un
    # `GET /api/reservas/series` entraría por ahí con `reserva_id="series"` y
    # contestaría un 422 confuso en vez de la lista. Con dos segmentos no hay
    # ambigüedad, y la ruta deja de depender del orden de declaración.
    series = list(
        sesion.scalars(select(Serie).order_by(Serie.dia_semana, Serie.hora)).all()
    )
    if not series:
        return []

    # Los tres agregados en una sola consulta y no una por serie: el listado de
    # un complejo con veinte canchas fijas serían sesenta viajes a la base.
    ahora_local = ahora()
    filas = sesion.execute(
        select(
            Reserva.serie_id,
            func.max(Reserva.comienza_at),
            func.count(Reserva.id).filter(Reserva.comienza_at >= ahora_local),
        )
        .where(
            Reserva.serie_id.in_([s.id for s in series]),
            Reserva.estado.in_(ESTADOS_QUE_OCUPAN),
        )
        .group_by(Reserva.serie_id)
    ).all()
    por_serie = {f[0]: (f[1], f[2]) for f in filas}

    canchas = {c.id: c.nombre for c in sesion.scalars(select(Cancha))}
    clientes = {c.id: c.nombre for c in sesion.scalars(select(Cliente))}

    salida = []
    for serie in series:
        ultima, proximas = por_serie.get(serie.id, (None, 0))
        salida.append(
            SerieEnLista(
                **{c.name: getattr(serie, c.name) for c in Serie.__table__.columns
                   if c.name in SerieSalida.model_fields},
                cliente=clientes.get(serie.cliente_id, f"#{serie.cliente_id}"),
                cancha=canchas.get(serie.cancha_id, f"#{serie.cancha_id}"),
                materializada_hasta=a_local(ultima).date() if ultima else None,
                proximas=proximas,
            )
        )
    return salida


@router.post("/series/{serie_id}/extender", response_model=SerieCreada)
def extender_serie(
    serie_id: int,
    hasta: date | None = Query(default=None),
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Genera las ocurrencias que faltan de una serie ya creada.

    🔴 **Sin esto, una cancha fija se apaga sola a los 90 días.** Una serie sin
    fin no materializa reservas infinitas —`HORIZONTE_SERIE`—, así que se genera
    una ventana y se extiende. Hasta ahora sólo se generaba al crearla: pasada
    la ventana, el grupo de los martes llegaba y el turno estaba libre para
    cualquiera, sin que nada hubiera fallado.

    Es idempotente en lo que importa: las ocurrencias que ya existen chocan
    consigo mismas y salen como salteadas con motivo `ocupada`, no duplicadas.
    """
    serie = sesion.get(Serie, serie_id)
    if serie is None:
        raise HTTPException(404, "no existe esa serie")
    if not serie.activa:
        raise HTTPException(409, "esa serie está dada de baja")
    creadas, salteadas = servicio.materializar_serie(sesion, serie, hasta)
    sesion.commit()
    return SerieCreada(
        serie=SerieSalida.model_validate(serie, from_attributes=True),
        creadas=[ReservaSalida.model_validate(r, from_attributes=True) for r in creadas],
        salteadas=[
            SalteadaSalida(comienza_at=x.comienza_at, motivo=x.motivo, detalle=x.detalle)
            for x in salteadas
        ],
    )


class BajaDeSerie(BaseModel):
    #: Si además se cancelan las reservas futuras que quedaron generadas.
    cancelar_futuras: bool = True
    motivo: str = Field(default="", max_length=200)


@router.post("/series/{serie_id}/baja", response_model=dict)
def dar_de_baja_serie(
    serie_id: int,
    datos: BajaDeSerie,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Corta una cancha fija. Devuelve cuántas reservas futuras se cancelaron.

    🔑 **Desactivar la serie NO borra sus reservas, y por eso `cancelar_futuras`
    existe y viene en `True`.** Las ocurrencias ya materializadas son filas de
    `reservas` como cualquier otra: sin cancelarlas, el grupo que dejó de venir
    sigue ocupando la cancha todos los martes hasta que se agote la ventana, y
    esos turnos no se pueden vender. Es el resultado que nadie espera de "dar de
    baja".

    🔴 **Sólo las FUTURAS.** Las pasadas se conservan tal cual: son historia
    —se jugaron, se cobraron, están en la caja y en las facturas— y cancelarlas
    reescribiría el pasado. La reserva de la semana que viene se cancela; la del
    martes pasado, no.
    """
    serie = sesion.get(Serie, serie_id)
    if serie is None:
        raise HTTPException(404, "no existe esa serie")

    canceladas = 0
    if datos.cancelar_futuras:
        futuras = sesion.scalars(
            select(Reserva).where(
                Reserva.serie_id == serie_id,
                Reserva.comienza_at >= ahora(),
                Reserva.estado.in_(ESTADOS_QUE_OCUPAN),
            )
        ).all()
        for reserva in futuras:
            # Por el servicio y no con un UPDATE masivo: la transición valida
            # qué estados se pueden cancelar, y el motivo queda escrito en la
            # reserva — que es lo que después contesta "por qué se cayó este
            # turno".
            servicio.cambiar_estado(
                sesion, reserva.id, EstadoReserva.CANCELADA,
                motivo=datos.motivo or f"Baja de la cancha fija #{serie_id}",
            )
            canceladas += 1

    serie.activa = False
    sesion.commit()
    return {"serie_id": serie_id, "canceladas": canceladas}


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
