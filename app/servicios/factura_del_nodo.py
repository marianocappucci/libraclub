"""La factura conjunta en un nodo de LibraEdge: el emisor de la cola de ARCA y lo que el central hace con lo que sube
(ADR-023).

La factura conjunta es la de una **reserva con sus consumos del buffet** (`servicios/facturacion.py`). En el central
se emite como siempre (`facturar_reserva`, con `get_next_numero_with_arca`). En un nodo **no puede**: sin red, esa
función cae a la numeración local, y un número local choca con el de ARCA y con el del central (libracore ADR-074).
Por eso en un nodo `POST /api/reservas/{id}/facturar` no emite: **deja el pedido en la cola** (`libracore.cola_arca`,
ADR-079) y, si hay conexión, lo emite en el momento; si no, sale solo cuando vuelve.

| Pieza | Dónde corre | Qué hace |
|---|---|---|
| `emitir_documento(pedido, ctx)` | nodo | el emisor `documento` de la cola: numera con el ticket prestado y emite |
| `facturar_desde_el_nodo(...)` | nodo | lo que contesta `POST .../facturar`: emitida, o `en_cola` |
| `payload_de_la_factura_conjunta(...)` | nodo | la operación `club.factura_conjunta` que sube la factura emitida |
| `aplicar_factura_conjunta(conn, op)` | central | escribe la factura con su número y CAE, la ata a la reserva y a
sus cobros |
| `aplicar_movimiento_de_club(aplicar)` | central | traduce el id provisorio de la reserva en la referencia de un
cobro |
| `armar_despachador()` | central | las operaciones de la capa ERP más las de LibraClub |

## El emisor es idempotente por la marca de la factura

`facturas.observaciones = "Reserva <id>"` (`facturacion.observacion_de_reserva`). Si el proceso murió entre «ARCA
emitió» y «el nodo anotó», la factura ya está creada: el emisor la encuentra por la marca y no emite otra. Si está
**sin CAE**, vuelve a pedirlo con un ticket nuevo (no numera ni crea otra).

## Qué sube y qué recibe el central

`cola.pedido` (el estado del pedido: lo que la web consulta) lo encola `al_cambiar` de la cola. Cuando el pedido queda
**emitido** sube además `club.factura_conjunta` con la factura (`libracore.facturas_del_nodo.payload_factura`) y la
reserva a la que pertenece **con el id del nodo** (puede ser el provisorio). El central: (1) escribe la factura con el
mismo número y CAE (`aplicar_factura_del_nodo`, idempotente por la clave del comprobante ante ARCA), (2) traduce la
reserva con el mapeo (`id_del_central`; si todavía no subió, `ValueError`: revisión manual detrás de su
`reserva.creada`), (3) le pone el `factura_id` **del central** y (4) ata los cobros de esa reserva que estaban sin
factura.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from libracommerce.erp.offline import (
    SCHEMA_VERSION as SCHEMA_VERSION_ERP,
)
from libracommerce.erp.offline import (
    aplicadores,
    con_outbox,
    id_del_central,
)
from libracommerce.erp.offline_caja import TIPO_MOVIMIENTO
from libracore.arca_facturacion import ambiente_de, solicitar_cae
from libracore.cola_arca import encolar_y_emitir
from libracore.db import cola_arca as db_cola
from libracore.db import facturas as db_facturas
from libracore.facturas_del_nodo import VERSION as VERSION_FACTURA
from libracore.facturas_del_nodo import aplicar_factura_del_nodo, payload_factura

from app import db, offline
from app.models.maestros import Cancha, Cliente
from app.models.reservas import Reserva
from app.servicios import caja, facturacion
from app.servicios.buffet import GANCHOS_PROPIOS
from app.tiempo import hoy

logger = logging.getLogger(__name__)

#: La forma del payload de `club.factura_conjunta`. Si cambia, sube: el central rechaza lo que no entiende.
VERSION = 1

#: El `source_type` del vínculo de la venta del buffet con la reserva, y la tabla del mapeo a la que corresponde su
#: `source_id` cuando es provisorio (libracommerce ADR-072). Lo declara el central en
#: `registrar_en(tablas_de_origen=)`.
TABLAS_DE_ORIGEN = {"reserva": "reservas"}

#: La tabla del mapeo de las reservas (`libraedge_mapeo`), la misma que usa `servicios/reservas_nodo.py` (PR 12,
#: ADR-022).
TABLA_RESERVAS = "reservas"


class FacturaConjuntaError(ValueError):
    """La factura conjunta del nodo no se puede aplicar en el central. Es un `ValueError` a propósito: el receptor de
    LibraEdge la manda a revisión manual y el nodo no traba la cola detrás de ella (ADR-020 de libraedge)."""


# ── En el nodo: el emisor de la cola ────────────────────────────────────────────────────────────────────────────────


def _reserva_para_facturar(reserva_id: int):
    """La reserva con su cliente, el nombre de la cancha y el punto de venta de su sucursal, leídos del dominio."""
    with db.fabrica_de_sesiones()() as sesion:
        reserva = sesion.get(Reserva, reserva_id)
        if reserva is None:
            raise LookupError(f"No existe la reserva {reserva_id}.")
        cliente = sesion.get(Cliente, reserva.cliente_id) if reserva.cliente_id else None
        cancha = sesion.get(Cancha, reserva.cancha_id)
        punto = cancha.sucursal.punto_venta_arca if cancha else None
        return reserva, cliente, (cancha.nombre if cancha else "cancha"), punto


async def emitir_documento(pedido: dict, ctx) -> dict:
    """El emisor `documento` de la cola de ARCA: emite la factura conjunta de la reserva `pedido["origen_id"]`.

    Numera con `ctx.numerar` (el ticket que presta el central; **nunca local**), toma la fecha de
    `ctx.fecha_de_la_factura`
    (la del hecho si ARCA todavía la admite) y pide el CAE. Devuelve `{"factura_id", "cae"}`; sin CAE el motor deja
    el pedido
    `a_revisar`. Es idempotente (ver el docstring del módulo). Los errores de red y de rechazo del central los
    clasifica el
    motor: este emisor no los atrapa."""
    reserva_id = int(pedido["origen_id"])
    previa = facturacion.factura_del_nodo_de(reserva_id)
    if previa is not None:
        if not previa.get("cae"):
            ta, arca = await ctx.ticket()
            previa = await solicitar_cae(previa["id"], previa, ta, arca)
        return _resultado(previa)

    reserva, cliente, cancha_nombre, punto_de_la_sucursal = _reserva_para_facturar(reserva_id)
    c = facturacion.comprobante_de(reserva, cliente, cancha_nombre, punto_de_la_sucursal)

    numero, ta, arca = await ctx.numerar(c.punto_venta, c.tipo)
    ambiente = ambiente_de(arca)
    fecha = ctx.fecha_de_la_factura(c.punto_venta, c.tipo, ambiente)
    factura_id = db_facturas.create_factura(
        c.tipo, c.punto_venta, numero, fecha.isoformat(),
        (cliente.cuit or "") if cliente else "",
        (cliente.nombre if cliente else "Consumidor Final"),
        # Sin campo de condición frente al IVA en `Cliente`, el receptor es Consumidor Final (ver
        # `tipo_de_comprobante`).
        facturacion.IVA_CODES["Consumidor Final"],
        c.lineas, float(c.neto), float(c.iva), float(c.total),
        observaciones=facturacion.observacion_de_reserva(reserva_id),
        # Del MISMO `arca` con el que se acaba de pedir el número, como en `facturar_reserva`.
        ambiente=ambiente,
    )
    factura = await solicitar_cae(factura_id, db_facturas.get_factura(factura_id), ta, arca)
    # Los cobros que ya estaban en la caja del nodo, atados a esta factura (el central ata los suyos al aplicarla).
    caja.vincular_cobros_a_factura(reserva_id, factura_id)
    return _resultado(factura)


def _resultado(factura: dict) -> dict:
    resultado = {"factura_id": int(factura["id"]), "cae": factura.get("cae") or ""}
    if factura.get("cae_error"):
        resultado["cae_error"] = str(factura["cae_error"])
    return resultado


# ── En el nodo: lo que contesta POST /api/reservas/{id}/facturar ────────────────────────────────────────────────────


async def _encolar_y_emitir(reserva_id: int, usuario_id: int | None) -> dict:
    return await encolar_y_emitir(
        offline.cola(), "documento", reserva_id, datos={"reserva_id": reserva_id},
        # La fecha del hecho es la del día en que se pidió el comprobante, como en el central (`hoy()`): si pasan más
        # de lo que ARCA admite hasta que salga, el motor usa la de hoy.
        fecha_ref=hoy().isoformat(), concepto=1, usuario_id=usuario_id,
    )


def facturar_desde_el_nodo(reserva, usuario_id: int | None) -> dict:
    """La factura conjunta de `reserva` en un nodo: la deja en la cola y, con conexión, la emite ya.

    Devuelve `{"estado": "emitido", "factura": {...}}` o `{"estado": "en_cola", "pedido": {...}, "mensaje": ...}`.
    Validaciones y errores: los del central (`FacturacionNoConfigurada`, `SinPrecio`, `ReservaYaFacturada`). Corre en el
    hilo del request, con un loop propio (`asyncio.run`), como `facturar_reserva`."""
    if not facturacion.hay_base():
        raise facturacion.FacturacionNoConfigurada("Falta LIBRACLUB_LIBRACORE_DATABASE_URL en esta instancia.")
    if reserva.precio is None or reserva.precio <= 0:
        raise facturacion.SinPrecio("La reserva no tiene precio cargado.")
    if reserva.factura_id is not None or facturacion.factura_del_nodo_de(reserva.id) is not None:
        raise facturacion.ReservaYaFacturada(f"La reserva {reserva.id} ya tiene comprobante.")
    try:
        pedido = asyncio.run(_encolar_y_emitir(reserva.id, usuario_id))
    except db_cola.PedidoYaResuelto as e:
        raise facturacion.ReservaYaFacturada(
            f"La factura de la reserva {reserva.id} ya está {e.estado}: se resuelve desde la cola de comprobantes."
        ) from e
    if pedido["estado"] == db_cola.ESTADO_EMITIDO:
        return {"estado": "emitido", "factura": db_facturas.get_factura(int(pedido["resultado"]["factura_id"]))}
    return {"estado": "en_cola", "pedido": pedido, "mensaje": _mensaje_del_pedido(pedido)}


def _mensaje_del_pedido(pedido: dict) -> str:
    estado = pedido["estado"]
    if estado == db_cola.ESTADO_ESPERANDO:
        return pedido.get("ultimo_error") or (
            "Sin conexión: la factura queda en la cola y se emite sola cuando vuelva la conexión."
        )
    if estado in db_cola.ESTADOS_DE_REVISION:
        return pedido.get("ultimo_error") or "La factura necesita que alguien la revise."
    return f"La factura está {estado}."


# ── En el nodo: la operación que sube la factura ────────────────────────────────────────────────────────────────────


def payload_de_la_factura_conjunta(pedido: dict, conn) -> dict | None:
    """El payload de `club.factura_conjunta` para un `cola.pedido` que quedó **emitido**, o `None` si no corresponde
    (otro
    estado, otro tipo, o una factura que el nodo no tiene). Lo arma `subir_pedido`, en la transacción de `conn`."""
    if pedido.get("estado") != db_cola.ESTADO_EMITIDO or pedido.get("origen_tipo") != db_cola.ORIGEN_DOCUMENTO:
        return None
    factura_id = (pedido.get("resultado") or {}).get("factura_id")
    if factura_id is None:
        return None
    factura = db_facturas.get_factura(int(factura_id), conn=conn)
    if factura is None:
        logger.error(
            "Nodo: el pedido %s de la cola salió con la factura %s y la factura no está",
            pedido.get("id_en_el_nodo"), factura_id,
        )
        return None
    return {
        "version": VERSION,
        "reserva_id": int(pedido["origen_id"]),
        "factura": payload_factura(factura),
    }


# ── En el central: lo que sube del nodo ─────────────────────────────────────────────────────────────────────────────


def aplicar_factura_conjunta(conn, operacion) -> None:
    """Aplica `club.factura_conjunta`: escribe la factura del nodo con su número y CAE, la ata a la reserva y a sus
    cobros.

    Todo en la transacción del receptor. Idempotente: la factura por la clave ante ARCA, el vínculo porque si la
    reserva ya tiene esa factura no hace nada. Los errores son `ValueError` (revisión manual): la reserva todavía no
    subió (su `reserva.creada` quedó en revisión), la reserva ya tiene **otra** factura, o el central ya tiene ese
    comprobante con
    otro total u otro CAE (`FacturaEnConflicto`)."""
    if operacion.operation_type != offline.TIPO_FACTURA_CONJUNTA:
        raise ValueError(f"se esperaba {offline.TIPO_FACTURA_CONJUNTA}, llegó {operacion.operation_type!r}")
    if operacion.schema_version != SCHEMA_VERSION_ERP:
        raise ValueError(f"schema {operacion.schema_version} de {offline.TIPO_FACTURA_CONJUNTA} desconocido")
    datos = operacion.payload
    if datos.get("version") != VERSION:
        raise ValueError(f"versión {datos.get('version')!r} de {offline.TIPO_FACTURA_CONJUNTA} desconocida")
    if (datos.get("factura") or {}).get("version") != VERSION_FACTURA:
        raise ValueError("versión de la factura del nodo desconocida")

    reserva_nodo = int(datos["reserva_id"])
    reserva_id = id_del_central(conn, operacion.node_id, TABLA_RESERVAS, reserva_nodo)
    fila = conn.execute("SELECT factura_id FROM reservas WHERE id = ?", (reserva_id,)).fetchone()
    if fila is None:
        raise FacturaConjuntaError(
            f"la reserva {reserva_id} (la {reserva_nodo} del nodo {operacion.node_id}) no existe en el central"
        )

    factura = dict(datos["factura"])
    if reserva_id != reserva_nodo:
        # La marca dice el id que la reserva tenía en el nodo; en el central es el definitivo.
        factura["observaciones"] = facturacion.observacion_de_reserva(reserva_id)
    factura_id, _creada = aplicar_factura_del_nodo(factura, conn=conn)

    if fila[0] is not None and fila[0] != factura_id:
        raise FacturaConjuntaError(
            f"la reserva {reserva_id} ya tiene la factura {fila[0]} en el central y el nodo {operacion.node_id} "
            f"le emitió la {factura_id}: dos comprobantes por la misma reserva. Revisar a mano"
        )
    if fila[0] is None:
        conn.execute("UPDATE reservas SET factura_id = ?, updated_at = now() WHERE id = ?", (factura_id, reserva_id))
    caja.vincular_cobros_a_factura(reserva_id, factura_id, conn=conn)


def aplicar_movimiento_de_club(aplicar: Callable[[Any, Any], None]) -> Callable[[Any, Any], None]:
    """Envuelve el aplicador de `caja.movimiento` de LibraCommerce con lo propio de LibraClub: **el cobro de una
    reserva**.

    La referencia de un cobro es `reserva-<id>-<azar>` y es lo único que lo ata a su reserva (`servicios/caja.py`). Un
    cobro hecho en el nodo a una reserva que se dio ahí lleva el id **provisorio** (`reserva--3-ab12`); el central lo
    traduce con el mapeo de las reservas antes de escribirlo, así `cobros_de_reserva` y el pendiente lo ven en la
    reserva con su id definitivo. Si la reserva todavía no subió, `ValueError` (revisión manual detrás de su
    `reserva.creada`). Después, si la
    reserva **ya tiene factura** en el central (la factura subió antes que el cobro), ata el cobro a ella."""

    def aplicar_con_la_reserva(conn, operacion) -> None:
        datos = operacion.payload
        referencia = datos.get("referencia") or ""
        id_en_la_referencia = caja._id_de_referencia(referencia)
        id_central = id_en_la_referencia
        if id_en_la_referencia is not None and id_en_la_referencia < 0:
            id_central = id_del_central(conn, operacion.node_id, TABLA_RESERVAS, id_en_la_referencia)
            nueva = referencia.replace(f"-{id_en_la_referencia}-", f"-{id_central}-", 1)
            operacion = replace(operacion, payload={**datos, "referencia": nueva})
        aplicar(conn, operacion)
        if id_central is not None:
            _atar_el_cobro_a_la_factura(conn, operacion, id_central)

    return aplicar_con_la_reserva


def _atar_el_cobro_a_la_factura(conn, operacion, reserva_id: int) -> None:
    from libracore.db import caja as db_caja

    fila = conn.execute("SELECT factura_id FROM reservas WHERE id = ?", (reserva_id,)).fetchone()
    if fila is None or fila[0] is None:
        return
    movimiento = db_caja.get_movimiento_de_origen(operacion.node_id, operacion.payload["movimiento_id"], conn=conn)
    if movimiento is None or movimiento["factura_id"] is not None:
        return
    conn.execute("UPDATE caja_movimientos SET factura_id = ? WHERE id = ?", (fila[0], movimiento["id"]))
    db_caja.al_libro_de_clientes(conn, [movimiento["id"]])


# ── En el central: el despachador ───────────────────────────────────────────────────────────────────────────────────


def armar_despachador(registrar_extra: Callable[[Any], Any] | None = None):
    """Las operaciones que el central de LibraClub sabe aplicar: las trece de la capa ERP de LibraCommerce (venta, caja,
    clientes y stock) con los ganchos del buffet y el vínculo `reserva` traducido, `cola.pedido` (libracore ADR-079),
    `club.factura_conjunta` y, si se pasa, las de las reservas (`registrar_extra`: `reservas_nodo.registrar_en`, PR
    12).

    Es `registrar_en` de LibraCommerce abierto en sus dos pasos (`aplicadores` + `registrar`) por un solo motivo: el
    aplicador de `caja.movimiento` se reemplaza por su versión con la reserva (`aplicar_movimiento_de_club`), y un
    tipo no se puede
    registrar dos veces."""
    from libracore.cola_arca import aplicar_pedido_del_nodo
    from libraedge.sync.despacho import Despachador

    por_tipo = aplicadores(con_outbox(GANCHOS_PROPIOS, offline.OUTBOX), tablas_de_origen=TABLAS_DE_ORIGEN)
    por_tipo[TIPO_MOVIMIENTO] = aplicar_movimiento_de_club(por_tipo[TIPO_MOVIMIENTO])
    por_tipo[offline.TIPO_COLA_PEDIDO] = lambda conn, op: aplicar_pedido_del_nodo(op.payload, conn=conn)
    por_tipo[offline.TIPO_FACTURA_CONJUNTA] = aplicar_factura_conjunta

    despachador = Despachador()
    for tipo, aplicador in por_tipo.items():
        despachador.registrar(tipo, SCHEMA_VERSION_ERP, aplicador)
    if registrar_extra is not None:
        registrar_extra(despachador)
    return despachador
