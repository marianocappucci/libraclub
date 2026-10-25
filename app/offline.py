"""La costura de LibraClub con LibraEdge: lo único del nodo sin conexión que es de este producto (ADR-023).

El nodo es la instancia de LibraClub que corre en la PC del club y sincroniza con el central (el VPS) por LibraEdge.
Sin internet, en el club se **vende en el buffet, se opera la caja, se cobran las canchas, se cargan consumos y se dan
reservas** (decisión del humano, 2026-10-22). Todo lo genérico es de los motores: el aprovisionamiento es de
LibraEdge, las ventas y la caja suben por la capa ERP de LibraCommerce (ADR-067, ADR-069, ADR-071 y ADR-072), la
facturación sin red es la cola de comprobantes de LibraCore (ADR-079). Lo que queda acá es declarativo; el modelo es
VentaLibra.

| Pieza | Qué aporta este producto |
|---|---|
| `aprovisionamiento` | las tablas de referencia (el reparto de autoridad), las sucursales y las altas en el nodo |
| `OUTBOX` | la identidad del nodo, si está en línea y que el arqueo es por movimientos con turno (`caja_con_turno`) |
| `GANCHOS_DE_CAJA` | turnos, cobros, egresos, anulaciones y cierre del día suben al central como operaciones |
| `CONEXION` / `cola()` | la factura conjunta (reserva más consumos) sale por la cola de ARCA, nunca con número local |
| `solo_en_el_central` | la guarda de lo que el nodo no hace |

## Quién manda sobre qué

El central es la autoridad de los **maestros** (sucursales, canchas, tarifas, feriados, horarios, clientes, usuarios,
el catálogo del buffet, `arca_config`): bajan al nodo por el espejo y el nodo no los escribe. El **nodo** es la
autoridad de lo que genera sin red: ventas del buffet, stock de su sucursal, caja, facturas y la cola de ARCA
(`cola_arca`): suben como operaciones y no se espejan. Las **reservas** y los **clientes** son de los dos
(`AltaEnNodo`): bajan, y el nodo da los suyos con un id provisorio negativo (PR 12, ADR-022 y su addendum).

## Identidad: `LIBRAEDGE_NODE_ID` (y `LIBRACLUB_EDGE_NODE_ID`, por la regla del motor)

`nodo()` es `libraedge.identidad.nodo_actual("LIBRACLUB")`. Es la **identidad** del nodo y la escribe el instalador.
LibraEdge está incluido en todos los planes (libraedge ADR-014): no hay guarda comercial al registrar (`sin_guarda`).
El prefijo de numeración (`LIBRAEDGE_PREFIJO`, `S02`) lo asigna el central; un nodo sin prefijo no vende.

## Aprovisionar (en el central)

    LIBRAEDGE_APROVISIONAMIENTO=app.offline:aprovisionamiento libraedge-central nodo publicar
    libraedge-central nodo sucursales | registrar <node_id> --sucursal <id o nombre> | estado | dar-de-baja <id>
    LIBRAEDGE_DESPACHADOR=app.routers.sincronizacion_offline:despachador libraedge-central revision listar ...
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from libracommerce.erp import offline_stock
from libracommerce.erp.offline import NodoLocal, Outbox
from libracommerce.erp.offline_caja import caja_con_outbox
from libracore.cola_arca import ColaDeArca
from libracore.ganchos_de_caja import GanchosDeCaja
from libracore.nodo_offline import (
    VARIABLE_ESTADO,
    ConexionDelNodo,
    RechazoDelCentral,
    SinConexion,
    esta_en_linea,
    guarda_solo_en_el_central,
)
from libraedge.altas import AltaEnNodo, Referencia
from libraedge.identidad import nodo_actual, prefijo_actual

from app.servicios import clientes_nodo

#: El prefijo de las variables del producto (`LIBRACLUB_DATABASE_URL`, `LIBRACLUB_EDGE_NODE_ID`).
PREFIJO = "LIBRACLUB"

#: El `origen_producto` de la cola de comprobantes (libracore ADR-079).
PRODUCTO = "libraclub"

#: Las operaciones propias de LibraClub y de la cola, con su versión (`schema_version`).
TIPO_COLA_PEDIDO = "cola.pedido"
TIPO_FACTURA_CONJUNTA = "club.factura_conjunta"
SCHEMA_VERSION = 1

#: El reparto de autoridad: qué tablas manda el central y el nodo sólo espeja. **Sólo los nombres**: la clave la lee
#: LibraEdge de la base. El porqué de cada una, en DECISIONS.md ADR-023.
#:
#: 🔴 NO están, a propósito:
#: - lo que genera el **nodo** y sube como operación: `sales` y sus tablas, `stock_movements`, `caja_movimientos`,
#:   `turnos_caja`, `cierres_diarios`, `facturas`, `cc_*`, `cola_arca`, `venta_links`, `venta_origen_nodo`;
#: - `arca_credenciales_servicio` y el almacén de claves (`secretos_instancia`): **el ticket de ARCA lo presta el
#:   central**, la clave privada no sale del VPS. `arca_config` sí (CUIT, punto de venta, ambiente: no es secreto);
#: - lo que sólo existe en la web: el portal (`cuentas_de_jugador`, `pagos_de_reserva`, `busquedas_de_jugadores`,
#:   `anotados_en_partido`), los torneos y los eventos (ADR-024), los avisos y la copia de Mercado Pago.
TABLAS_DE_REFERENCIA = frozenset({
    # LibraCore y libraauth: la sesión, el gate de módulos y de Términos, las cajas y facturar.
    "usuarios", "aceptaciones_terminos", "modulos", "cajas", "arca_config",
    # LibraCommerce: lo que lee el buffet para vender (productos, precios, depósitos y unidades).
    "branches", "locations", "units", "categories", "catalog_items", "item_variants", "item_codes",
    "price_lists", "item_prices", "commerce_settings",
    # Propias de LibraClub: los maestros y la agenda. `reservas` baja y además el nodo da las suyas (`altas_en_nodo`).
    "sucursales", "canchas", "clientes", "tarifas", "feriados", "franjas_de_atencion", "series", "reservas",
})

#: Los maestros que el nodo **no escribe**: LibraEdge les instala una guarda en la base del nodo y un intento de
#: escribirlos da un error claro en vez de pisarse con el espejo en el próximo ciclo. No están `usuarios`
#: (`espejar_usuario` hace un upsert idempotente), `cajas` (el arranque asegura una por sucursal), `reservas` ni
#: `clientes` (se dan de alta en el nodo, con id provisorio: ADR-022 y su addendum).
TABLAS_SOLO_LECTURA = frozenset({
    "sucursales", "canchas", "tarifas", "feriados", "franjas_de_atencion", "series",
    "branches", "locations", "units", "categories", "catalog_items", "item_variants", "item_codes", "price_lists",
    "item_prices", "commerce_settings", "arca_config", "modulos",
})

#: Las reservas se dan en el nodo con un id provisorio negativo (PR 12). Lo que las referencia **sin clave foránea** y
#: hay que reapuntar al id definitivo cuando el central lo asigna: el vínculo de la venta del buffet
#: (`sales.source_id` cuando `source_type='reserva'`). Las claves foráneas (`avisos`, `pagos_de_reserva`) se
#: encuentran solas en el catálogo de la base. La referencia de los cobros de caja es un texto
#: (`reserva-<id>-<azar>`): no se puede reapuntar, y `servicios/caja.py` la lee con las dos formas del id.
#:
#: Los **clientes** del club (`clientes`, no los `clients` de LibraCore) también se dan de alta en el nodo: quien llama
#: por primera vez se anota ahí para tomarle el turno. No declara referencias: `reservas.cliente_id`,
#: `series.cliente_id` y `cuentas_de_jugador.cliente_id` tienen clave foránea y `libraedge` las lee del catálogo
#: (`tests/test_clientes_en_el_nodo.py` ata que no haya otra columna de cliente sin FK).
ALTAS_EN_EL_NODO = (
    *clientes_nodo.altas_en_nodo(),
    AltaEnNodo("reservas", referencias=(Referencia("sales", "source_id", (("source_type", "reserva"),)),)),
)


# ── La identidad y la conexión del nodo ─────────────────────────────────────────────────────────────────────────────


def nodo() -> str | None:
    """El id de este nodo, o `None` si la instancia no es un nodo (el central, o una instalación común).

    Se lee en cada llamada: activar el nodo no exige reiniciar nada y la suite no depende del orden de los tests."""
    return nodo_actual(PREFIJO)


def nodo_local() -> NodoLocal | None:
    """La identidad de este nodo con su prefijo de numeración, para el outbox de LibraCommerce."""
    node_id = nodo()
    if node_id is None:
        return None
    return NodoLocal(node_id=node_id, prefijo=prefijo_actual() or "")


def en_linea() -> bool:
    """Si el nodo ve al central: lo que dice el archivo de estado del proceso del nodo (`LIBRAEDGE_ESTADO`).

    Es la de libracore (ADR-074): el último ciclo sincronizó y la última sincronización buena es reciente. Sin archivo,
    viejo o ilegible, sin conexión. La ruta se lee en cada llamada."""
    return esta_en_linea((os.environ.get(VARIABLE_ESTADO) or "").strip() or None)


#: Lo que LibraCore pregunta antes de salir a ARCA o a MercadoPago. Fuera de un nodo, nada cambia. Las dos funciones
#: se llaman por nombre en cada pregunta (no se atan al construirla): así un test puede cambiarlas.
CONEXION = ConexionDelNodo(nodo=lambda: nodo(), en_linea=lambda: en_linea())

#: El outbox de LibraEdge para `libracommerce.erp.offline.con_outbox`. El mismo en el nodo y en el central: fuera de
#: un nodo (`nodo_local()` es `None`) no encola nada. Sin `extra_de_venta`: el vínculo con la reserva viaja en
#: `source_type` / `source_id` (libracommerce ADR-072).
#:
#: 🔑 `caja_con_turno=True`: el arqueo de LibraClub es contra los **movimientos de caja con turno**
#: (`servicios/caja.py` escribe el `turno_id` en cada cobro), no contra las ventas del turno. El central recalcula el
#: arqueo del turno cerrado como lo hizo el nodo (libracommerce ADR-069).
OUTBOX = Outbox(nodo=nodo_local, en_linea=en_linea, caja_con_turno=True)

#: Los ganchos de la caja para `libracore.db.turnos` / `caja` / `cierre_diario` (`ganchos=`) y para el router del
#: cierre diario: en un nodo encolan en el `OUTBOX` el turno que se abre o se cierra, cada cobro, egreso y anulación,
#: y el cierre del día (libracore ADR-076, libracommerce ADR-069); **fuera de un nodo** no hacen nada, como
#: `GanchosDeCaja()`.
#:
#: 🔑 El cobro del buffet y el pago de una reserva suben **por acá**, como `caja.movimiento`: la venta del buffet se
#: registra con `pagos=[]` (ADR-021), así que la plata no viaja con `venta.registrada` y no se duplica.
GANCHOS_DE_CAJA = caja_con_outbox(GanchosDeCaja(), OUTBOX)

#: El stock de la sucursal de un nodo (libracommerce ADR-071): desde la carga inicial **lo mueve sólo el nodo**. En un
#: nodo encola `stock.movimiento` por cada fila del ledger que no viaja con una venta (reposiciones y ajustes del
#: buffet); en el central se niega (`DepositoDeSucursalConNodo`, 409) a mover un depósito de una sucursal con nodo
#: activo. Fuera de un nodo y de una sucursal con nodo no cambia nada. Una vez, en las dos puntas, al importar este
#: módulo.
offline_stock.configurar(OUTBOX)

#: Lo que el nodo no hace: `Depends(solo_en_el_central)` contesta 409 `solo_en_el_central` en un nodo y no hace nada
#: en el central ni en una instalación común.
solo_en_el_central = guarda_solo_en_el_central(nodo=lambda: nodo())

_LECTURAS = frozenset({"GET", "HEAD", "OPTIONS"})


def escritura_solo_en_el_central(request: Request) -> None:
    """Como `solo_en_el_central`, pero **sólo para lo que escribe**: las lecturas pasan. Es lo que se le pone a un
    router entero cuyos datos manda el central (maestros, usuarios, facturación manual): el nodo los lee del espejo y
    no los cambia.
    """
    if request.method not in _LECTURAS:
        solo_en_el_central()


def configurar_reservas() -> None:
    """Enchufa las reservas del nodo (PR 12, ADR-022) al `OUTBOX`.

    `servicios/reservas_nodo.py` necesita saber qué es un nodo y cómo se encola: esa configuración se arma sobre el
    `OUTBOX`, **igual en el nodo y en el central**, una vez al armar la app (`crear_app` llama a esta función). Fuera
    de un nodo no pide ningún id provisorio ni encola nada. El registro de `reserva.creada` y `reserva.estado` en el
    despachador del central es el otro punto: `app/routers/sincronizacion_offline.registrar_reservas`. Las altas en el
    nodo de `reservas` ya están en `ALTAS_EN_EL_NODO`."""
    from app.servicios import reservas_nodo

    reservas_nodo.configurar(reservas_nodo.desde_el_outbox(OUTBOX))


def configurar_clientes() -> None:
    """Enchufa el alta de clientes en el nodo (ADR-022, addendum) al `OUTBOX`: igual que `configurar_reservas`, en el
    nodo y en el central, una vez al armar la app, y sin efecto fuera de un nodo. El registro de `cliente_club.alta` en
    el despachador del central es `app/routers/sincronizacion_offline.registrar_clientes`; su `AltaEnNodo`,
    `ALTAS_EN_EL_NODO`."""
    clientes_nodo.configurar(clientes_nodo.desde_el_outbox(OUTBOX))


# ── Encolar una operación propia ────────────────────────────────────────────────────────────────────────────────────


def _ahora_utc() -> str:
    return datetime.now(UTC).isoformat()


def encolar_operacion(conn, tipo: str, agregado: str, id_local: Any, payload: Mapping[str, Any], *,
                      commit: bool = False) -> None:
    """Encola `tipo` en el outbox de este nodo, **en la transacción de `conn`** (sin confirmar, salvo `commit=True`).

    Es el contrato de ADR-025 de LibraEdge: `operation_id = <nodo>:<secuencia>`, `aggregate_id =
    <nodo>:<agregado>:<id local>`, la secuencia es una sola por nodo (la misma de las ventas y la caja, así que el
    central
    las recibe en el orden en que ocurrieron). Levanta `RuntimeError` fuera de un nodo: encolar en el central dejaría
    una
    operación que nadie sube."""
    from libraedge.db.repository import NodeRepository
    from libraedge.domain.sync import OutboxOperation

    node_id = nodo()
    if node_id is None:
        raise RuntimeError("Encolar una operación es del nodo: esta instancia no es un nodo de LibraEdge.")
    repo = NodeRepository(conn)
    secuencia = repo.next_sequence(commit=False)
    repo.enqueue_operation(OutboxOperation(
        operation_id=f"{node_id}:{secuencia}", node_id=node_id, sequence=secuencia, operation_type=tipo,
        aggregate_type=agregado, aggregate_id=f"{node_id}:{agregado}:{id_local}", occurred_at=_ahora_utc(),
        schema_version=SCHEMA_VERSION, payload=dict(payload),
    ), commit=False)
    if commit:
        conn.commit()


# ── Facturar sin red: la cola de ARCA ───────────────────────────────────────────────────────────────────────────────

_cliente_de_ticket = None


def _version_esquema_del_nodo() -> str | None:
    """La misma versión de esquema que manda el proceso del nodo (`LIBRAEDGE_VERSION_ESQUEMA`, `alembic` por defecto),
    para que el central conteste 409 si no coinciden."""
    from libracore.db.core import get_connection
    from libraedge.cli import version_esquema_del_nodo

    with get_connection() as conn:
        return version_esquema_del_nodo(conn, os.environ.get("LIBRAEDGE_VERSION_ESQUEMA"))


def cliente_de_ticket():
    """El `ClienteDeTicket` de LibraEdge de este nodo (uno por proceso: guarda el ticket en memoria hasta que vence).
    Lo arma recién al primer uso: fuera de un nodo no hay a quién pedirle y `cliente_desde_entorno` levantaría."""
    global _cliente_de_ticket
    if _cliente_de_ticket is None:
        from libraedge.sync.ticket import cliente_desde_entorno

        version: list[str | None] = []

        def version_esquema() -> str | None:
            if not version:
                version.append(_version_esquema_del_nodo())
            return version[0]

        _cliente_de_ticket = cliente_desde_entorno(version_esquema=version_esquema)
    return _cliente_de_ticket


async def obtener_ta(arca: dict, servicio: str = "wsfe") -> dict:
    """El `obtener_ta(arca, servicio=)` de `ColaDeArca`, sobre el transporte de LibraEdge.

    **No** el de un solo parámetro de VentaLibra: la cola lo llama con `servicio=` para los que no son `wsfe`
    (LibraClub no
    tiene `wscpe`, pero el contrato es uno). Un corte (sin red, 5xx, esquema distinto) llega como `SinConexion` y el
    pedido queda `esperando`; un rechazo del central (nodo revocado, sin ARCA) como `RechazoDelCentral`, con el
    mensaje del
    central, y se informa en vez de reintentarse."""
    base = cliente_de_ticket().para_servicio(sin_conexion=SinConexion, rechazo=RechazoDelCentral)
    return await base(arca, servicio=servicio)


def subir_pedido(payload: dict) -> None:
    """El `al_cambiar` de la cola: encola el estado del pedido (`cola.pedido`) para que el central lo vea, y, si el
    pedido de una factura conjunta quedó **emitido**, la factura misma (`club.factura_conjunta`), las dos en una sola
    transacción.

    Corre **después** de confirmar el cambio de la cola y no tiene transacción propia: abre la suya. Si falla, el
    motor lo
    registra y no deshace el comprobante (ya está emitido en ARCA)."""
    from libracore.db.core import get_connection

    from app.servicios import factura_del_nodo

    with get_connection() as conn:
        encolar_operacion(conn, TIPO_COLA_PEDIDO, "cola_arca", payload["id_en_el_nodo"], payload)
        extra = factura_del_nodo.payload_de_la_factura_conjunta(payload, conn)
        if extra is not None:
            encolar_operacion(conn, TIPO_FACTURA_CONJUNTA, "factura_conjunta", extra["reserva_id"], extra)
        conn.commit()


def cola() -> ColaDeArca:
    """La cola de comprobantes de ARCA de este producto (libracore ADR-079). El mismo armado en el nodo y en el
    central: en el central no hace nada (`encolar` se rehúsa y `procesar_cola` no emite). Se arma en cada llamada (es
    barata) para que
    un test pueda cambiar la conexión o el numerador."""
    from app.servicios import factura_del_nodo

    return ColaDeArca(
        producto=PRODUCTO,
        emisores={"documento": factura_del_nodo.emitir_documento},
        conexion=CONEXION,
        obtener_ta=obtener_ta,
        al_cambiar=subir_pedido,
    )


def arrancar_cola() -> Any:
    """En un nodo, arranca el hilo que emite lo que quedó en la cola cuando vuelve la conexión (libracore ADR-079,
    punto 7).
    Devuelve el `Event` que lo para, o `None` si la instancia no es un nodo."""
    from libracore.cola_arca import arrancar_cola_al_volver

    return arrancar_cola_al_volver(cola())


# ── El aprovisionamiento del central ────────────────────────────────────────────────────────────────────────────────


def _conectar():
    """La base de la instancia, para el CLI de LibraEdge (que corre sin la app): la misma URL que arma `app/asgi.py`.
    En LibraClub el dominio y LibraCore son la misma base (ADR-020)."""
    from libracore.db.core import conectar
    from libracore.db.url_de_instancia import url_de_instancia

    return conectar(url_de_instancia("libraclub", requerida=True))


def nodos_del_central() -> list[dict]:
    """Los nodos registrados en esta instancia: la misma lista que «Sucursal sin internet»."""
    from libracore.db.core import get_connection
    from libraedge.pantalla_del_central import nodos_de_la_instancia

    with get_connection() as conn:
        return nodos_de_la_instancia(conn, [])


def listar_sucursales(conn) -> list[dict]:
    """Las sucursales a las que se puede atar un nodo: las del **dominio** (`sucursales`), que es de lo que cuelgan las
    canchas, las cajas y el depósito del buffet (`locations.branch_id`). Las `branches` de LibraCommerce quedan vacías
    en este producto."""
    filas = conn.execute("SELECT id, nombre, activa FROM sucursales ORDER BY nombre").fetchall()
    return [{"id": f[0], "nombre": f[1], "activa": bool(f[2])} for f in filas]


def _aprovisionamiento():
    from libraedge.aprovisionamiento import Aprovisionamiento, sin_guarda

    return Aprovisionamiento(
        prefijo=PREFIJO, tablas_de_referencia=TABLAS_DE_REFERENCIA, listar_sucursales=listar_sucursales,
        # Sin guarda comercial: LibraEdge está incluido en todos los planes (libraedge ADR-014).
        verificar_alta=sin_guarda, conectar=_conectar,
        tablas_solo_lectura=TABLAS_SOLO_LECTURA, altas_en_nodo=ALTAS_EN_EL_NODO,
        # Un depósito activo sin sucursal no es de ningún nodo: la guarda del central no lo ve y la carga inicial no
        # lo trae. El registro se niega hasta que tenga una (libracommerce ADR-071, libraedge ADR-023).
        validar_registro=offline_stock.depositos_sin_sucursal,
    )


#: Lo que el central necesita para aprovisionar los nodos de este producto (`LIBRAEDGE_APROVISIONAMIENTO`).
aprovisionamiento = _aprovisionamiento()

