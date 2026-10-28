"""Las reservas que se dan en un nodo de LibraEdge sin conexión, y su vuelta en el central (ADR-022).

Un club sin internet también da reservas (decisión del humano, 2026-10-22). El nodo es la copia
local de LibraClub que corre en la PC del club (LibraEdge): lo que se da ahí tiene que subir al
central **sin pisar** lo que la web o el portal hayan tomado mientras tanto.

> ⚠️ **Vocabulario.** Acá «provisorio» es el **id negativo** de una reserva que se dio en el nodo y
> todavía no tiene el definitivo del central. No tiene nada que ver con `EstadoReserva.PROVISORIA`,
> el turno retenido mientras se espera el pago del portal (`vencer_provisorias.py`). Una reserva del
> nodo es, en el estado, una reserva común: `confirmada` o `pendiente_pago`.

## Las dos operaciones

Las dos con `aggregate_type = "reserva"` y `aggregate_id = "<node_id>:reserva:<id>"`,
`schema_version = 1` (el de las ventas de libracommerce).

| `operation_type` | Lo encola | El central |
|---|---|---|
Cada fila: la operación, quién la encola y qué hace el central.

- **`reserva.creada`**: la encola `servicios/reservas.crear`, en la transacción de la reserva. El central le asigna
  su id, anota el mapeo `(nodo, 'reservas', id provisorio) -> id` y, si choca, la guarda `en_conflicto`.
- **`reserva.estado`**: la encola `servicios/reservas.cambiar_estado`, sólo para una reserva con id provisorio. El
  central aplica el cambio sobre la reserva que le corresponde.

`reserva.estado` existe porque **una reserva que se dio en el nodo se puede cancelar ahí**: sin ella
el `reserva.creada` ya encolado subiría como si nada y la cancha quedaría ocupada en el central.
Una reserva que no se dio en este nodo (id positivo) **no** se cambia desde acá: ver «Las guardas».

## Qué pasa en el central: gana la que llegó primero

El aplicador de `reserva.creada` inserta la reserva en un `SAVEPOINT`. Si la exclusión del central
(`ex_reservas_sin_superposicion`, `id > 0`) la rechaza, es que la cancha ya estaba tomada **cuando
esta operación llegó**: la web, el portal u otro nodo llegaron antes. Entonces la guarda igual con
`estado = 'en_conflicto'`, `conflicto_con_id` = la que ganó y `estado_previo` = lo que era. La
decide la base y no un `SELECT` previo: dos operaciones simultáneas no pueden ganar las dos.

`en_conflicto` **no ocupa la cancha** (no está en `ESTADOS_QUE_OCUPAN`) y baja al nodo por el espejo,
así que se ve en las dos puntas. Cómo se resuelve: `servicios/conflictos.py`.

## Las guardas (en el nodo)

`reservas` es una tabla que el nodo espeja, y con `AltaEnNodo("reservas")` en el aprovisionamiento
el nodo sólo deja escribir las filas con id negativo (ADR-019 de libraedge: cualquier otra da
SQLSTATE `LE001`). Lo que la base rechazaría con un 500 se contesta antes con un 409 claro:

- cancelar o cambiar el estado de una reserva con id positivo: **409 `sin_conexion`** si el nodo no
  está en línea (decisión del humano: espera a la conexión) y **409 `solo_en_el_central`** si lo
  está. Hoy el nodo no tiene cómo subir ese cambio, así que se hace desde la web;
- crear un bloqueo o una serie: **409 `solo_en_el_central`**. Su id saldría de la secuencia del
  nodo y chocaría con los del central.

## Cómo lo cablea el producto (PR 11)

```python
from app.servicios import reservas_nodo
reservas_nodo.configurar(reservas_nodo.desde_el_outbox(OUTBOX))     # nodo y central, una vez al armar la app
reservas_nodo.registrar_en(despachador)                              # sólo el central
```

y en el `Aprovisionamiento` del central: `altas_en_nodo=[..., AltaEnNodo("reservas")]`. Sin
`configurar()`, o con un `nodo()` que devuelve `None` (el central, una instalación común), nada de
esto hace nada.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from libracore.nodo_offline import SinConexion, SoloEnElCentral

from app.models.enums import EstadoReserva, OrigenReserva
from app.models.reservas import WHERE_OCUPA

logger = logging.getLogger(__name__)

#: La forma de los `datos` de las operaciones. Si cambia, sube: el central rechaza lo que no entiende.
VERSION = 1
#: El `schema_version` de la `OutboxOperation`: el mismo que usa `libracommerce.erp.offline`.
SCHEMA_VERSION = 1

TIPO_RESERVA_CREADA = "reserva.creada"
TIPO_RESERVA_ESTADO = "reserva.estado"
TIPOS = (TIPO_RESERVA_CREADA, TIPO_RESERVA_ESTADO)

#: El `aggregate_type` de las dos (el `aggregate_id` es `<node_id>:reserva:<id>`).
AGREGADO_RESERVA = "reserva"
#: La tabla del mapeo `libraedge_mapeo`, y la de los clientes del dominio a los que apunta una reserva.
TABLA_RESERVAS = "reservas"
TABLA_CLIENTES = "clientes"

#: Los estados con los que se puede dar una reserva en el nodo. Los dos que el mostrador ofrece.
ESTADOS_DEL_NODO = (EstadoReserva.CONFIRMADA, EstadoReserva.PENDIENTE_PAGO)

#: El nombre de la restricción del central, igual que en el modelo y la migración. Se compara contra
#: el nombre y no contra el texto del error (que se traduce con el locale del servidor).
CONSTRAINT_SUPERPOSICION = "ex_reservas_sin_superposicion"

MENSAJE_SIN_CONEXION = (
    "Esta reserva es de la web o del portal: cancelarla o marcarla jugada espera a que vuelva la "
    "conexión con el central."
)
MENSAJE_DEL_CENTRAL = (
    "Esta reserva es del central: cancelala o marcala jugada desde la web, no desde el equipo del local."
)
MENSAJE_SOLO_EN_EL_CENTRAL = (
    "Los bloqueos y las canchas fijas se cargan desde el central, no desde el equipo del local."
)
MENSAJE_CONFLICTO_SOLO_EN_EL_CENTRAL = (
    "Los conflictos de reservas se resuelven desde el central: el equipo del local los muestra pero no los cambia."
)
#: Lo que queda anotado en una reserva `en_conflicto` que el club marcó jugada en el nodo.
NOTA_JUGADA_EN_EL_NODO = "El club la marcó como jugada desde el nodo mientras estaba en conflicto: resolverla a mano."


class ReservaDelNodoError(ValueError):
    """Una operación de reservas del nodo que el central no puede aplicar. Es un `ValueError` a propósito: el
    receptor de LibraEdge la manda a revisión manual y el nodo no traba la cola (ADR-020 de libraedge)."""


class ReservaDelNodoInvalida(ReservaDelNodoError):
    """El payload de la operación no se entiende o trae algo que el central no puede escribir."""


# ── La configuración: qué es un nodo y cómo se encola ────────────────────────


def _nada(conn: Any, datos: dict) -> None:
    return None


def _sin_conexion() -> bool:
    return False


@dataclass(frozen=True)
class ReservasEnNodo:
    """Lo que el servicio de reservas necesita saber de LibraEdge para dar reservas en un nodo. Inmutable.

    - `nodo`: el id de este nodo, o `None` si la instancia no es un nodo (el central, una instalación común).
    - `id_provisorio`: `(conn) -> int`, el próximo id negativo del nodo, **sin commitear** (va en la
      transacción de la reserva). `libraedge.mapeo.siguiente_id_provisorio`.
    - `al_crear_reserva` / `al_cambiar_estado`: `(conn, datos)`, corren **adentro de la transacción** de la
      reserva: si levantan, la reserva no queda (una reserva que se da en el nodo y no sube no es «a medias»:
      el central no la ve y la cancha se puede vender dos veces). Lo normal es encolar en el outbox.
    - `en_linea`: si el nodo ve al central. Sólo decide qué 409 se contesta (ver «Las guardas»).
    """

    nodo: Callable[[], str | None]
    id_provisorio: Callable[[Any], int]
    al_crear_reserva: Callable[[Any, dict], None] = _nada
    al_cambiar_estado: Callable[[Any, dict], None] = _nada
    en_linea: Callable[[], bool] = _sin_conexion


_configuracion: ReservasEnNodo | None = None


def configurar(reservas: ReservasEnNodo | None) -> None:
    """Registra la `ReservasEnNodo` del proceso (o la saca, con `None`). La llama el producto al armar la app, una
    vez. Es global y es del proceso, como `libracore.altas_en_nodo.configurar`."""
    global _configuracion
    if reservas is not None and not isinstance(reservas, ReservasEnNodo):
        raise TypeError(f"se esperaba una ReservasEnNodo, llegó {type(reservas).__name__}")
    _configuracion = reservas


def configuracion() -> ReservasEnNodo | None:
    return _configuracion


def nodo_actual() -> str | None:
    """El id del nodo si esta instancia es un nodo **y** hay configuración; si no, `None`. Se lee en cada llamada."""
    if _configuracion is None:
        return None
    return _configuracion.nodo() or None


def en_un_nodo() -> bool:
    return nodo_actual() is not None


def es_del_nodo(reserva_id: int | None) -> bool:
    """Si la reserva se dio en este nodo y todavía no tiene su id definitivo: un id negativo."""
    return reserva_id is not None and reserva_id < 0


def desde_el_outbox(outbox) -> ReservasEnNodo:
    """La `ReservasEnNodo` de este producto sobre el `Outbox` de `libracommerce.erp.offline` (el mismo de las
    ventas, la caja y los clientes): la identidad del nodo es la del outbox, el id provisorio sale de
    `libraedge.mapeo` y los ganchos encolan **en la transacción de la reserva**.

    Se arma igual en el nodo y en el central: fuera de un nodo (`outbox.nodo()` es `None`) no se pide ningún id
    provisorio ni se encola nada, y no hace falta que libraedge esté instalado."""

    def nodo() -> str | None:
        local = outbox.nodo()
        return local.node_id if local is not None else None

    def id_provisorio(conn) -> int:
        try:
            from libraedge.mapeo import siguiente_id_provisorio
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise RuntimeError(
                "Falta libraedge >= 0.18 para dar reservas en un nodo: instalar libracommerce[offline]"
            ) from exc
        return siguiente_id_provisorio(conn)

    def encolar(tipo: str):
        def gancho(conn, datos: dict) -> None:
            local = outbox.nodo()
            if local is not None:
                encolar_operacion(conn, local, tipo, datos)

        return gancho

    return ReservasEnNodo(
        nodo=nodo,
        id_provisorio=id_provisorio,
        al_crear_reserva=encolar(TIPO_RESERVA_CREADA),
        al_cambiar_estado=encolar(TIPO_RESERVA_ESTADO),
        en_linea=outbox.en_linea,
    )


def encolar_operacion(conn, nodo, tipo: str, datos: Mapping[str, Any]):
    """Encola `tipo` **dentro de la transacción de `conn`**. `nodo` es el `NodoLocal` de libracommerce."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo de operación de reservas desconocido: {tipo!r}")
    # `_encolar` es el mismo que usan `offline_caja` y `offline_clientes`: no hay uno público.
    from libracommerce.erp.offline_caja import _encolar

    return _encolar(conn, nodo, tipo, AGREGADO_RESERVA, datos["reserva_id"], datos)


def conexion_de_la_sesion(sesion):
    """La conexión del motor (`?` como marcador, filas por posición) **sobre la misma transacción** de la sesión de
    SQLAlchemy. El outbox de LibraEdge se escribe con esa interfaz, y tiene que entrar en la transacción de la
    reserva: sin esto serían dos conexiones y una reserva podría quedar sin su operación, o al revés.

    No se cierra ni se commitea: es de la sesión."""
    from libracore.db._postgres import ConnectionWrapper

    return ConnectionWrapper(sesion.connection().connection.driver_connection)


# ── En el nodo: las guardas ──────────────────────────────────────────────────


def _en_linea() -> bool:
    try:
        return bool(_configuracion.en_linea()) if _configuracion is not None else False
    except Exception:
        logger.exception("No se pudo saber si el nodo está en línea: se toma como sin conexión")
        return False


def exigir_reserva_modificable(reserva_id: int) -> None:
    """En un nodo, cambiar el estado de una reserva que **no se dio acá** (id positivo: la web, el portal u otro
    nodo) no se puede. Fuera de un nodo, y para una reserva del nodo, no hace nada.

    Levanta `SinConexion` (409 `sin_conexion`) si el nodo no está en línea: decisión del humano, espera a la
    conexión. Con conexión levanta `SoloEnElCentral` (409 `solo_en_el_central`): el nodo no tiene cómo subir ese
    cambio y su base rechaza la escritura sobre una fila del central, así que se hace desde la web."""
    if not en_un_nodo() or es_del_nodo(reserva_id):
        return
    if _en_linea():
        raise SoloEnElCentral(MENSAJE_DEL_CENTRAL)
    raise SinConexion(MENSAJE_SIN_CONEXION)


def exigir_central(mensaje: str = MENSAJE_SOLO_EN_EL_CENTRAL) -> None:
    """En un nodo, lo que no se puede hacer ahí (dar un bloqueo o una cancha fija, resolver un conflicto):
    `SoloEnElCentral`. En el central, no hace nada."""
    if en_un_nodo():
        raise SoloEnElCentral(mensaje)


def solo_en_el_central() -> None:
    """Dependencia de FastAPI: 409 `solo_en_el_central` en un nodo, nada en el central."""
    from fastapi import HTTPException

    try:
        exigir_central()
    except SoloEnElCentral as exc:
        raise HTTPException(409, exc.detalle()) from exc


# ── En el nodo: el encolado ──────────────────────────────────────────────────


def _iso(valor: datetime | None) -> str | None:
    return None if valor is None else valor.isoformat()


def _plata(valor) -> str | None:
    """Plata como texto (no `float` en JSON)."""
    return None if valor is None else str(valor)


def datos_de_creada(reserva, *, creada_at: datetime | None = None) -> dict:
    """El payload de `reserva.creada`: `reserva` es la fila de `reservas` ya guardada (con su id provisorio)."""
    return {
        "version": VERSION,
        "reserva_id": reserva.id,
        "cancha_id": reserva.cancha_id,
        "cliente_id": reserva.cliente_id,
        "estado": reserva.estado.value,
        "origen": reserva.origen.value,
        "comienza_at": _iso(reserva.comienza_at),
        "termina_at": _iso(reserva.termina_at),
        "precio": _plata(reserva.precio),
        "sena": _plata(reserva.sena),
        "observaciones": reserva.observaciones,
        "creada_at": _iso(creada_at or datetime.now(UTC)),
    }


def datos_de_estado(reserva_id: int, estado: EstadoReserva, motivo: str | None) -> dict:
    """El payload de `reserva.estado`."""
    return {"version": VERSION, "reserva_id": reserva_id, "estado": estado.value, "motivo": motivo}


def siguiente_id(conn) -> int:
    """El id provisorio (negativo) para una reserva que se está dando en el nodo. No commitea."""
    if _configuracion is None:
        raise RuntimeError("no hay reservas en nodo configuradas: reservas_nodo.configurar(...)")
    id_ = int(_configuracion.id_provisorio(conn))
    if id_ >= 0:
        raise ValueError(f"un id provisorio es negativo, no {id_}")
    return id_


def avisar_creada(conn, reserva) -> None:
    """Le avisa al gancho que se dio `reserva` en el nodo. No hace nada fuera de un nodo ni para un id positivo."""
    if _configuracion is None or not es_del_nodo(reserva.id) or not nodo_actual():
        return
    _configuracion.al_crear_reserva(conn, datos_de_creada(reserva))


def avisar_estado(conn, reserva_id: int, estado: EstadoReserva, motivo: str | None) -> None:
    """Le avisa al gancho que `reserva_id` (del nodo) cambió de estado."""
    if _configuracion is None or not es_del_nodo(reserva_id) or not nodo_actual():
        return
    _configuracion.al_cambiar_estado(conn, datos_de_estado(reserva_id, estado, motivo))


# ── En el central: validar ───────────────────────────────────────────────────


def _verificar(operacion, tipo: str) -> None:
    if operacion.operation_type != tipo:
        raise ReservaDelNodoInvalida(f"se esperaba {tipo}, llegó {operacion.operation_type!r}")
    if operacion.schema_version != SCHEMA_VERSION:
        raise ReservaDelNodoInvalida(
            f"schema {operacion.schema_version} de {tipo} desconocido (se entiende {SCHEMA_VERSION})"
        )
    if operacion.payload.get("version") != VERSION:
        raise ReservaDelNodoInvalida(
            f"versión {operacion.payload.get('version')!r} de los datos de {tipo} desconocida (se entiende {VERSION})"
        )


def _entero(datos: Mapping, campo: str, operacion, *, firma: str | None = None) -> int:
    valor = datos.get(campo)
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ReservaDelNodoInvalida(
            f"{campo} {valor!r} de {operacion.operation_type} del nodo {operacion.node_id} no es un entero"
        )
    if firma == "negativo" and valor >= 0:
        raise ReservaDelNodoInvalida(
            f"el reserva_id {valor!r} del nodo {operacion.node_id} no es un id provisorio (un entero negativo): "
            "el nodo sólo sube reservas con id provisorio"
        )
    if firma == "positivo" and valor <= 0:
        raise ReservaDelNodoInvalida(f"{campo} {valor!r} del nodo {operacion.node_id} no es un id del central")
    return valor


def _fecha(datos: Mapping, campo: str, operacion, *, obligatoria: bool = True) -> datetime | None:
    crudo = datos.get(campo)
    if crudo is None and not obligatoria:
        return None
    try:
        fecha = datetime.fromisoformat(crudo)
    except (TypeError, ValueError) as exc:
        raise ReservaDelNodoInvalida(f"{campo} {crudo!r} no es una fecha ISO 8601") from exc
    if fecha.tzinfo is None:
        # Una fecha sin zona se leería como UTC en la base: la reserva de las 20:00 aparecería a las 17:00.
        raise ReservaDelNodoInvalida(f"{campo} {crudo!r} no trae zona horaria")
    return fecha


def _plata_de(datos: Mapping, campo: str) -> Decimal | None:
    crudo = datos.get(campo)
    if crudo is None:
        return None
    try:
        valor = Decimal(str(crudo))
    except InvalidOperation as exc:
        raise ReservaDelNodoInvalida(f"{campo} {crudo!r} no es un importe") from exc
    if not valor.is_finite() or valor < 0:
        raise ReservaDelNodoInvalida(f"{campo} {crudo!r} no es un importe válido")
    return valor


def _estado_de(datos: Mapping, *, permitidos: tuple[EstadoReserva, ...] | None = None) -> EstadoReserva:
    try:
        estado = EstadoReserva(datos.get("estado"))
    except ValueError as exc:
        raise ReservaDelNodoInvalida(f"estado {datos.get('estado')!r} desconocido") from exc
    if permitidos is not None and estado not in permitidos:
        raise ReservaDelNodoInvalida(
            f"estado {estado.value!r} no se puede dar en un nodo (sólo {[e.value for e in permitidos]})"
        )
    return estado


def _datos_de_creada(operacion) -> dict:
    """Valida el payload de `reserva.creada` y lo devuelve con los tipos de Python."""
    _verificar(operacion, TIPO_RESERVA_CREADA)
    datos = operacion.payload
    comienza_at = _fecha(datos, "comienza_at", operacion)
    termina_at = _fecha(datos, "termina_at", operacion)
    if termina_at <= comienza_at:
        raise ReservaDelNodoInvalida("la reserva termina antes de empezar")
    precio, sena = _plata_de(datos, "precio"), _plata_de(datos, "sena")
    if sena is not None and precio is not None and sena > precio:
        raise ReservaDelNodoInvalida(f"la seña {sena} supera el precio {precio}")
    try:
        origen = OrigenReserva(datos.get("origen"))
    except ValueError as exc:
        raise ReservaDelNodoInvalida(f"origen {datos.get('origen')!r} desconocido") from exc
    return {
        "reserva_id": _entero(datos, "reserva_id", operacion, firma="negativo"),
        "cancha_id": _entero(datos, "cancha_id", operacion, firma="positivo"),
        "cliente_id": _entero(datos, "cliente_id", operacion),
        "estado": _estado_de(datos, permitidos=ESTADOS_DEL_NODO),
        "origen": origen,
        "comienza_at": comienza_at,
        "termina_at": termina_at,
        "precio": precio,
        "sena": sena,
        "observaciones": datos.get("observaciones"),
        "creada_at": _fecha(datos, "creada_at", operacion, obligatoria=False),
    }


def _datos_de_estado(operacion) -> dict:
    _verificar(operacion, TIPO_RESERVA_ESTADO)
    datos = operacion.payload
    motivo = datos.get("motivo")
    if motivo is not None and (not isinstance(motivo, str) or len(motivo) > 200):
        raise ReservaDelNodoInvalida("el motivo no es un texto de hasta 200 caracteres")
    return {"reserva_id": _entero(datos, "reserva_id", operacion), "estado": _estado_de(datos), "motivo": motivo}


# ── En el central: aplicar ───────────────────────────────────────────────────


def _mapeo():
    from libraedge import mapeo

    return mapeo


def _es_superposicion(exc: BaseException) -> bool:
    """Si el `IntegrityError` es el de la exclusión del central. Por el nombre de la restricción, no por el texto."""
    causa = getattr(exc, "__cause__", None)
    diag = getattr(causa, "diag", None)
    return getattr(diag, "constraint_name", None) == CONSTRAINT_SUPERPOSICION


def _cliente_del_central(conn, node_id: str, cliente_id: int) -> int:
    """El cliente (del dominio) de la reserva, en el central. Un id negativo es un cliente que el nodo dio de alta y se
    traduce con el mapeo (`erp.offline.id_del_central`); uno positivo ya es del central. Que exista se verifica
    acá: una FK rota sería un `IntegrityError`, que el receptor lee como «duplicado» y la reserva se perdería
    pareciendo un reintento."""
    from libracommerce.erp.offline import id_del_central

    id_central = id_del_central(conn, node_id, TABLA_CLIENTES, cliente_id)
    if conn.execute("SELECT 1 FROM clientes WHERE id = ?", (id_central,)).fetchone() is None:
        raise ReservaDelNodoInvalida(
            f"el cliente {id_central} de la reserva del nodo {node_id} no existe en el central"
        )
    return id_central


def _vencimiento_en_el_central(datos: dict, estado: EstadoReserva) -> datetime | None:
    """El `vence_at` de la reserva que sube de un nodo: **lo decide el central**, el nodo no lo manda.

    Una `pendiente_pago` tiene el mismo plazo de seña que la que se tomó en la web
    (`reservas.vencimiento_de_sena`), contado desde que **el nodo la tomó** (`creada_at`) y no desde
    que llegó: el jugador oyó «tenés 24 horas» en el mostrador, y que el club haya estado sin
    internet no se las acorta ni se las alarga. Una `en_conflicto` no vence (no ocupa la cancha, y
    cuando se resuelva `servicios/conflictos` le da un plazo nuevo). Una confirmada tampoco."""
    if estado is not EstadoReserva.PENDIENTE_PAGO:
        return None
    from app.servicios.reservas import vencimiento_de_sena
    from app.tiempo import ahora

    return vencimiento_de_sena(datos["creada_at"] or ahora(), datos["comienza_at"])


def _insertar(conn, datos: dict, *, cliente_id: int, estado: EstadoReserva, ganadora: int | None = None,
              estado_previo: EstadoReserva | None = None, motivo: str | None = None) -> int:
    cursor = conn.execute(
        """INSERT INTO reservas
               (cancha_id, cliente_id, estado, origen, comienza_at, termina_at, precio, sena, motivo,
                observaciones, conflicto_con_id, estado_previo, vence_at, created_at)
           VALUES (?, ?, ?::estado_reserva, ?::origen_reserva, ?, ?, ?, ?, ?, ?, ?, ?::estado_reserva, ?,
                   COALESCE(?, now()))""",
        (
            datos["cancha_id"], cliente_id, estado.value, datos["origen"].value, datos["comienza_at"],
            datos["termina_at"], datos["precio"], datos["sena"], motivo, datos["observaciones"], ganadora,
            estado_previo.value if estado_previo else None, _vencimiento_en_el_central(datos, estado),
            datos["creada_at"],
        ),
    )
    # `ConnectionWrapper` agrega `RETURNING id` a todo INSERT de una tabla con `id`, y lo deja en `lastrowid`.
    return cursor.lastrowid


def _quien_ocupa(conn, datos: dict) -> int | None:
    """La reserva del central que ocupa esa cancha en ese rango (la más vieja), o `None`."""
    fila = conn.execute(
        f"SELECT id FROM reservas WHERE cancha_id = ? AND {WHERE_OCUPA} "
        "AND periodo && tstzrange(?, ?, '[)') ORDER BY id LIMIT 1",
        (datos["cancha_id"], datos["comienza_at"], datos["termina_at"]),
    ).fetchone()
    return fila[0] if fila else None


def aplicar_reserva_creada(conn, operacion) -> None:
    """Aplica `reserva.creada` en el central: crea la reserva con su propio id y anota el mapeo
    `(nodo, 'reservas', id provisorio) -> id`. **Si la cancha ya estaba tomada, gana la que ya estaba** y ésta queda
    `en_conflicto`. Todo en la transacción del receptor. Idempotente.

    Los errores son `ValueError` (revisión manual); un `IntegrityError` que no sea el de la exclusión también se
    traduce: el receptor lo leería como «duplicado»."""
    from libraedge.sync.reconciliacion import savepoint

    datos = _datos_de_creada(operacion)
    mapeo = _mapeo()
    node_id, id_nodo = operacion.node_id, datos["reserva_id"]

    id_central = mapeo.traducir_id(conn, node_id, TABLA_RESERVAS, id_nodo, exigir=False)
    if id_central is not None:
        # Entregada otra vez (el outbox entrega al menos una vez). Si la reserva mapeada no es ésta, el nodo reusó
        # un id provisorio (una PC reemplazada con el mismo `node_id`): revisión manual, no se pisa nada.
        actual = conn.execute(
            "SELECT cancha_id, comienza_at, termina_at FROM reservas WHERE id = ?", (id_central,)
        ).fetchone()
        if actual is None:
            raise ReservaDelNodoError(
                f"la reserva {id_nodo} del nodo {node_id} ya estaba mapeada a la {id_central} y esa ya no existe"
            )
        if (actual[0], actual[1], actual[2]) != (datos["cancha_id"], datos["comienza_at"], datos["termina_at"]):
            raise ReservaDelNodoError(
                f"el nodo {node_id} reusó el id provisorio {id_nodo}: ya estaba mapeado a la reserva {id_central} del "
                "central y ahora llega otra cancha u horario. Revisar a mano"
            )
        return

    if conn.execute("SELECT 1 FROM canchas WHERE id = ?", (datos["cancha_id"],)).fetchone() is None:
        raise ReservaDelNodoInvalida(
            f"la cancha {datos['cancha_id']} de la reserva {id_nodo} del nodo {node_id} no existe"
        )
    cliente_id = _cliente_del_central(conn, node_id, datos["cliente_id"])

    try:
        with savepoint(conn, "reserva_del_nodo"):
            id_central = _insertar(conn, datos, cliente_id=cliente_id, estado=datos["estado"])
    except sqlite3.IntegrityError as exc:
        if not _es_superposicion(exc):
            raise ReservaDelNodoInvalida(
                f"el central no puede guardar la reserva {id_nodo} del nodo {node_id}: {exc}"
            ) from exc
        ganadora = _quien_ocupa(conn, datos)
        logger.info("reserva.creada del nodo %s: la %s choca con la reserva %s del central; queda en_conflicto",
                    node_id, id_nodo, ganadora)
        id_central = _insertar(
            conn, datos, cliente_id=cliente_id, estado=EstadoReserva.EN_CONFLICTO, ganadora=ganadora,
            estado_previo=datos["estado"],
            motivo=f"Chocó con la reserva {ganadora}, que llegó antes al central." if ganadora else
            "Chocó con otra reserva que llegó antes al central.",
        )
    try:
        mapeo.anotar_mapeo(conn, node_id, TABLA_RESERVAS, id_nodo, id_central)
    except mapeo.MapeoEnConflicto as exc:
        raise ReservaDelNodoError(str(exc)) from exc


def aplicar_reserva_estado(conn, operacion) -> None:
    """Aplica `reserva.estado` sobre la reserva del central: la traduce con el mapeo (si el `reserva.creada` no se
    aplicó, `SinMapeo`: revisión manual) y hace el cambio que `TRANSICIONES` permite. Idempotente.

    Una reserva `en_conflicto` se puede cancelar desde el nodo (resuelve el conflicto). Marcarla jugada **no** la
    saca del conflicto —ocuparía una cancha que otra reserva ya tiene—: queda `en_conflicto` con una nota."""
    from app.servicios.reservas import TRANSICIONES

    datos = _datos_de_estado(operacion)
    id_central = _mapeo().traducir_id(conn, operacion.node_id, TABLA_RESERVAS, datos["reserva_id"])
    fila = conn.execute(
        "SELECT estado, observaciones FROM reservas WHERE id = ? FOR UPDATE", (id_central,)
    ).fetchone()
    if fila is None:
        raise ReservaDelNodoError(
            f"la reserva {id_central} (la {datos['reserva_id']} del nodo {operacion.node_id}) no existe"
        )
    actual, nuevo = EstadoReserva(fila[0]), datos["estado"]
    if actual is nuevo:
        return
    if actual is EstadoReserva.EN_CONFLICTO and nuevo is not EstadoReserva.CANCELADA:
        if NOTA_JUGADA_EN_EL_NODO not in (fila[1] or ""):
            conn.execute(
                "UPDATE reservas SET observaciones = ?, updated_at = now() WHERE id = ?",
                ((fila[1] + "\n" if fila[1] else "") + NOTA_JUGADA_EN_EL_NODO, id_central),
            )
        return
    if actual is not EstadoReserva.EN_CONFLICTO and nuevo not in TRANSICIONES[actual]:
        raise ReservaDelNodoError(
            f"la reserva {id_central} está {actual.value} y el nodo {operacion.node_id} la pasó a {nuevo.value}: "
            "no es una transición válida. Revisar a mano"
        )
    conn.execute(
        """UPDATE reservas SET estado = ?::estado_reserva, motivo = COALESCE(?, motivo), vence_at = NULL,
                  conflicto_con_id = NULL, estado_previo = NULL, updated_at = now()
            WHERE id = ?""",
        (nuevo.value, datos["motivo"], id_central),
    )


def aplicadores() -> dict[str, Callable[[Any, Any], None]]:
    """`{operation_type: (conn, operacion) -> None}` de las dos operaciones, para el despachador del central."""
    return {TIPO_RESERVA_CREADA: aplicar_reserva_creada, TIPO_RESERVA_ESTADO: aplicar_reserva_estado}


def registrar_en(despachador):
    """Registra `reserva.creada` y `reserva.estado` en un `libraedge.sync.despacho.Despachador` (el mismo en que
    `libracommerce.erp.offline.registrar_en` registró los de venta, caja y clientes) y lo devuelve. Registrar dos
    veces un tipo falla al arrancar (es la regla del `Despachador`)."""
    for tipo, aplicador in aplicadores().items():
        despachador.registrar(tipo, SCHEMA_VERSION, aplicador)
    return despachador
