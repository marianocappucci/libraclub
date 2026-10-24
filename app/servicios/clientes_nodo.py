"""Los clientes del club que se dan de alta en un nodo de LibraEdge sin conexión, y su vuelta en el central (ADR-022,
addendum).

Un club sin internet también da reservas (ADR-022), y quien llama o viene por primera vez **no está en la lista**: hay
que darlo de alta ahí mismo para tomarle el turno. Hasta este cambio el alta usaba la secuencia local del nodo; su id
chocaba con uno del central, o lo pisaba el espejo, y la reserva subía con un `cliente_id` que en el central es de
**otra persona**.

> ⚠️ **No es el cliente de LibraCore.** Acá se habla de `clientes`, el maestro de **este** producto (a quien se le toma
> la reserva). Los `clients` de LibraCore (los de la factura y la cuenta corriente) tienen su propio alta en el nodo:
> `libracore.altas_en_nodo` y `libracommerce.erp.offline_clientes` (`cliente.alta`, ADR-077 / ADR-070). Este módulo
> copia **su patrón**, no lo comparte, porque las tablas, las claves y la deduplicación son otras.

## La operación

- `operation_type`: `cliente_club.alta`. `aggregate_type = "cliente_club"`, `aggregate_id = "<nodo>:cliente_club:<id>"`.
- La encola `agregar`, en la transacción del alta.
- El central usa al cliente que ya existe o lo crea, y anota el mapeo.

`cliente_club.alta` y **no** `cliente.alta`: ese tipo ya lo registra `libracommerce.erp.offline.registrar_en` (para los
`clients` del buffet), y el `Despachador` falla al arrancar si se registra dos veces un mismo tipo.

`schema_version = 1`. Payload `version 1`: `cliente_id` (negativo), `nombre`, `telefono`, `email`, `documento`, `cuit`,
`activo`, `acepta_avisos`, `observaciones`, `creada_at` (ISO con zona).

## Qué hace el central (`aplicar_cliente_alta`, idempotente por `libraedge_mapeo`)

En la transacción del receptor:

1. Si el mapeo `(nodo, 'clientes', id provisorio)` ya está, no crea nada **siempre que el cliente mapeado sea la misma
   persona** (si no, el nodo reusó un id provisorio, una PC reemplazada con el mismo `node_id`: `ClienteDelNodoError`,
   revisión manual; las reservas a ese id irían a otra persona). El outbox entrega al menos una vez.
2. Si no, **busca a la persona** entre los clientes activos del central (ver «A quién se considera la misma persona»).
   Si la encuentra, usa **ésa** y no toca sus datos: el central es la autoridad del maestro.
3. Si no existe, la crea con el id de la secuencia de la base.
4. Anota el mapeo. Ese mapeo es también lo que le dice al nodo el id definitivo: `libraedge_mapeo` baja por el espejo y
   el nodo reapunta lo que referenciaba al provisorio (`reservas.cliente_id`, `cuentas_de_jugador.cliente_id`, por las
   FK del catálogo) y borra su fila.

### A quién se considera la misma persona

El producto no declara ninguna clave única sobre `clientes` (el maestro es «Juan de los martes»: el nombre no
identifica), así que lo que sirve es lo que **ya usa para identificar a alguien**:

- **`documento` y `cuit`**: son los datos «para facturar» (`facturacion` los manda como receptor). Identifican a una
  persona. Se comparan normalizados (sin puntos, guiones ni espacios, sin mayúsculas).
- **`email`**: el portal de jugadores entra por el email (`uq_cuentas_jugador_email`): es lo que ata a una persona con
  su cuenta. Es la clave más débil (una familia puede compartir uno), así que va **última**.

Se prueban en ese orden y la primera que encuentra gana. Una coincidencia **se descarta si choca con otra clave
fuerte**: si los dos tienen `documento` (o `cuit`) y son distintos, no son la misma persona aunque compartan el email.
**No se deduplica por nombre ni por teléfono**: dos «Juan Pérez» sin documento ni email son dos clientes (el nodo no
puede saber que son el mismo, y fusionar por el nombre es peor que duplicar: un duplicado se junta a mano, una reserva
atada a otra persona no se nota). Sólo se miran los clientes **activos** y con id del central (positivo): a quien se
dio de baja no se le cuelgan reservas nuevas, y un provisorio no es una persona que el central tenga.

## Qué se traduce

`reserva.creada` lleva un `cliente_id`; si es negativo, `reservas_nodo.aplicar_reserva_creada` lo traduce con el mismo
mapeo (`libracommerce.erp.offline.id_del_central`, tabla `clientes`). **El orden lo da el outbox**: las operaciones de
un nodo se aplican en el orden en que se encolaron (ADR-020 de libraedge), y el alta se encola en el mismo request que
precede a la reserva. Si el alta quedó en revisión manual, la reserva se rechaza (`VinculoNoSincronizado`) en vez de
quedar atada a nadie, y se reintenta al resolver el alta.

## En el nodo: las guardas

`clientes` es una tabla que el nodo espeja, y con `AltaEnNodo("clientes")` en el aprovisionamiento sólo deja escribir
las filas con id negativo (ADR-019 de libraedge: cualquier otra da SQLSTATE `LE001`). Lo que la base rechazaría con un
500 se contesta antes con un 409 claro:

- editar o borrar un cliente: **409 `sin_conexion`** si el nodo no está en línea (misma decisión que con las reservas
  del central) y **409 `solo_en_el_central`** si lo está. Un cliente provisorio tampoco se edita: la operación que ya
  se encoló llevaría los datos viejos y el cambio se perdería cuando baje el definitivo;
- registrarse en el portal de jugadores: **409 `solo_en_el_central`** (el portal es público y no corre en el equipo del
  local).

## Cómo está cableado (PR 11, ADR-023)

- `app/offline.configurar_clientes()` (la llama `crear_app`, en el nodo y en el central): `clientes_nodo.configurar(
  clientes_nodo.desde_el_outbox(OUTBOX))`.
- `app/routers/sincronizacion_offline.registrar_clientes(despachador)` (sólo el central): `clientes_nodo.registrar_en`.
- `app/offline.ALTAS_EN_EL_NODO` suma `AltaEnNodo("clientes")` (`clientes_nodo.altas_en_nodo()`), y
  `clientes` ya no está en `TABLAS_SOLO_LECTURA`: el nodo escribe ahí las filas con id negativo.
- `app/main.py` no le pone a los clientes la guarda general de los maestros (`maestros.CON_ALTA_EN_NODO`): su alta es la
  de este módulo y las demás guardas, las de arriba.

Sin `configurar()`, o con un `nodo()` que devuelve `None` (el central, una instalación común), nada de esto hace nada.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from libracore.nodo_offline import SinConexion, SoloEnElCentral

from app.servicios import reservas_nodo

logger = logging.getLogger(__name__)

#: La forma de los `datos` de la operación. Si cambia, sube: el central rechaza lo que no entiende.
VERSION = 1
#: El `schema_version` de la `OutboxOperation`: el mismo que usa `libracommerce.erp.offline`.
SCHEMA_VERSION = 1

TIPO_CLIENTE_ALTA = "cliente_club.alta"
TIPOS = (TIPO_CLIENTE_ALTA,)

#: El `aggregate_type` de la operación (el `aggregate_id` es `<node_id>:cliente_club:<id>`).
AGREGADO_CLIENTE = "cliente_club"
#: La tabla del mapeo `libraedge_mapeo`: la de los clientes del dominio (no la `clients` de LibraCore).
TABLA_CLIENTES = reservas_nodo.TABLA_CLIENTES

#: Las tablas con alta en el nodo que este módulo suma al `Aprovisionamiento` del PR 11. Nombres, no `AltaEnNodo`: ver
#: el docstring.
ALTAS_EN_NODO = (TABLA_CLIENTES,)

#: Largos de las columnas de `clientes` (el central valida antes de escribir: un `DataError` ajeno no es un
#: `ValueError`).
_LARGOS = {"nombre": 120, "telefono": 40, "email": 120, "documento": 20, "cuit": 13}

MENSAJE_SIN_CONEXION = (
    "Este cliente es del central: editarlo o borrarlo espera a que vuelva la conexión con el central."
)
MENSAJE_DEL_CENTRAL = (
    "Los clientes se editan y se borran desde el central, no desde el equipo del local: desde acá sólo se dan de alta."
)
MENSAJE_PROVISORIO = (
    "Este cliente se dio de alta sin conexión y todavía no subió al central: corregilo desde la web cuando suba."
)
MENSAJE_PORTAL_SOLO_EN_EL_CENTRAL = (
    "El portal de jugadores es del central: el equipo del local no registra cuentas."
)


class ClienteDelNodoError(ValueError):
    """Un alta de cliente del nodo que el central no puede aplicar. Es un `ValueError` a propósito: el receptor de
    LibraEdge la manda a revisión manual y el nodo no traba la cola (ADR-020 de libraedge)."""


class AltaDeClienteInvalida(ClienteDelNodoError):
    """El payload de `cliente_club.alta` no se entiende o trae algo que el central no puede escribir."""


# ── La configuración: qué es un nodo y cómo se encola ────────────────────────


def _nada(conn: Any, datos: dict) -> None:
    return None


def _sin_conexion() -> bool:
    return False


@dataclass(frozen=True)
class ClientesEnNodo:
    """Lo que el alta de clientes necesita saber de LibraEdge para dar de alta en un nodo. Inmutable.

    - `nodo`: el id de este nodo, o `None` si la instancia no es un nodo (el central, una instalación común).
    - `id_provisorio`: `(conn) -> int`, el próximo id negativo del nodo, **sin commitear** (va en la transacción del
      alta). `libraedge.mapeo.siguiente_id_provisorio`.
    - `al_crear_cliente`: `(conn, datos)`, corre **adentro de la transacción** del alta: si levanta, el cliente no
      queda (un cliente que se da de alta en el nodo y no sube no es «a medias»: el central no lo ve y la próxima
      reserva a su nombre se rechaza). Lo normal es encolar en el outbox.
    - `en_linea`: si el nodo ve al central. Sólo decide qué 409 se contesta (ver «En el nodo: las guardas»).
    """

    nodo: Callable[[], str | None]
    id_provisorio: Callable[[Any], int]
    al_crear_cliente: Callable[[Any, dict], None] = _nada
    en_linea: Callable[[], bool] = _sin_conexion


_configuracion: ClientesEnNodo | None = None


def configurar(clientes: ClientesEnNodo | None) -> None:
    """Registra la `ClientesEnNodo` del proceso (o la saca, con `None`). La llama el producto al armar la app, una vez.
    Es global y es del proceso, como `reservas_nodo.configurar` y `libracore.altas_en_nodo.configurar`."""
    global _configuracion
    if clientes is not None and not isinstance(clientes, ClientesEnNodo):
        raise TypeError(f"se esperaba una ClientesEnNodo, llegó {type(clientes).__name__}")
    _configuracion = clientes


def configuracion() -> ClientesEnNodo | None:
    return _configuracion


def nodo_actual() -> str | None:
    """El id del nodo si esta instancia es un nodo **y** hay configuración; si no, `None`. Se lee en cada llamada."""
    if _configuracion is None:
        return None
    return _configuracion.nodo() or None


def en_un_nodo() -> bool:
    return nodo_actual() is not None


def es_provisorio(cliente_id: int | None) -> bool:
    """Si el cliente se dio de alta en este nodo y todavía no tiene su id definitivo: un id negativo."""
    return cliente_id is not None and cliente_id < 0


def altas_en_nodo() -> list:
    """`[AltaEnNodo("clientes")]` para el `Aprovisionamiento` del central. Importa `libraedge` recién acá."""
    from libraedge.altas import AltaEnNodo

    return [AltaEnNodo(tabla) for tabla in ALTAS_EN_NODO]


def desde_el_outbox(outbox) -> ClientesEnNodo:
    """La `ClientesEnNodo` de este producto sobre el `Outbox` de `libracommerce.erp.offline` (el mismo de las ventas,
    la caja, los clientes de LibraCore y las reservas): la identidad del nodo es la del outbox, el id provisorio sale
    de `libraedge.mapeo` y el gancho encola **en la transacción del alta**.

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
                "Falta libraedge >= 0.18 para dar de alta clientes en un nodo: instalar libracommerce[offline]"
            ) from exc
        return siguiente_id_provisorio(conn)

    def al_crear_cliente(conn, datos: dict) -> None:
        local = outbox.nodo()
        if local is not None:
            encolar_alta(conn, local, datos)

    return ClientesEnNodo(
        nodo=nodo, id_provisorio=id_provisorio, al_crear_cliente=al_crear_cliente, en_linea=outbox.en_linea
    )


def encolar_alta(conn, nodo, datos: Mapping[str, Any]):
    """Encola `cliente_club.alta` **dentro de la transacción de `conn`**. `nodo` es el `NodoLocal` de libracommerce."""
    # `_encolar` es el mismo que usan `offline_caja`, `offline_clientes` y `reservas_nodo`: no hay uno público.
    from libracommerce.erp.offline_caja import _encolar

    return _encolar(conn, nodo, TIPO_CLIENTE_ALTA, AGREGADO_CLIENTE, datos["cliente_id"], datos)


# ── En el nodo: el alta ──────────────────────────────────────────────────────


def _iso(valor: datetime | None) -> str | None:
    return None if valor is None else valor.isoformat()


def datos_de_alta(cliente, *, creada_at: datetime | None = None) -> dict:
    """El payload de `cliente_club.alta`: `cliente` es la fila de `clientes` ya guardada (con su id provisorio)."""
    return {
        "version": VERSION,
        "cliente_id": cliente.id,
        "nombre": cliente.nombre,
        "telefono": cliente.telefono,
        "email": cliente.email,
        "documento": cliente.documento,
        "cuit": cliente.cuit,
        "activo": bool(cliente.activo),
        "acepta_avisos": True if cliente.acepta_avisos is None else bool(cliente.acepta_avisos),
        "observaciones": cliente.observaciones,
        "creada_at": _iso(creada_at or datetime.now(UTC)),
    }


def siguiente_id(conn) -> int:
    """El id provisorio (negativo) para un cliente que se está dando de alta en el nodo. No commitea."""
    if _configuracion is None:
        raise RuntimeError("no hay clientes en nodo configurados: clientes_nodo.configurar(...)")
    id_ = int(_configuracion.id_provisorio(conn))
    if id_ >= 0:
        raise ValueError(f"un id provisorio es negativo, no {id_}")
    return id_


def agregar(sesion, cliente):
    """Agrega `cliente` a la sesión. **Fuera de un nodo es `sesion.add` y nada más** (el id lo asigna la base al
    commit, como siempre).

    En un nodo le pone un id provisorio negativo, lo guarda (`flush`) y encola `cliente_club.alta` **en la misma
    transacción**: si algo falla, no queda ni el cliente ni la operación. No commitea."""
    if not en_un_nodo():
        sesion.add(cliente)
        return cliente

    conn = reservas_nodo.conexion_de_la_sesion(sesion)
    cliente.id = siguiente_id(conn)
    sesion.add(cliente)
    sesion.flush()
    if _configuracion is not None:
        _configuracion.al_crear_cliente(conn, datos_de_alta(cliente))
    return cliente


# ── En el nodo: las guardas ──────────────────────────────────────────────────


def _en_linea() -> bool:
    try:
        return bool(_configuracion.en_linea()) if _configuracion is not None else False
    except Exception:
        logger.exception("No se pudo saber si el nodo está en línea: se toma como sin conexión")
        return False


def exigir_cliente_modificable(cliente_id: int) -> None:
    """En un nodo, editar o borrar un cliente no se puede (el del central es de sólo lectura, el provisorio ya subió
    con sus datos). Fuera de un nodo no hace nada.

    Levanta `SinConexion` (409 `sin_conexion`) si el nodo no está en línea, y `SoloEnElCentral` (409
    `solo_en_el_central`) si lo está o si el cliente todavía es provisorio."""
    if not en_un_nodo():
        return
    if es_provisorio(cliente_id):
        raise SoloEnElCentral(MENSAJE_PROVISORIO)
    if _en_linea():
        raise SoloEnElCentral(MENSAJE_DEL_CENTRAL)
    raise SinConexion(MENSAJE_SIN_CONEXION)


def exigir_central_para_el_portal() -> None:
    """El portal de jugadores crea su `Cliente` por su cuenta: en un nodo, `SoloEnElCentral`. En el central, nada."""
    if en_un_nodo():
        raise SoloEnElCentral(MENSAJE_PORTAL_SOLO_EN_EL_CENTRAL)


# ── En el central: validar ───────────────────────────────────────────────────


def _texto(datos: Mapping, campo: str, operacion, *, obligatorio: bool = False) -> str | None:
    valor = datos.get(campo)
    if valor is None:
        if obligatorio:
            raise AltaDeClienteInvalida(f"el alta del nodo {operacion.node_id} no trae {campo}")
        return None
    if not isinstance(valor, str):
        raise AltaDeClienteInvalida(f"{campo} {valor!r} del alta del nodo {operacion.node_id} no es un texto")
    valor = valor.strip()
    if obligatorio and not valor:
        raise AltaDeClienteInvalida(f"el alta del nodo {operacion.node_id} no trae {campo}")
    if len(valor) > _LARGOS.get(campo, 10_000_000):
        raise AltaDeClienteInvalida(
            f"{campo} del alta del nodo {operacion.node_id} pasa de {_LARGOS[campo]} caracteres"
        )
    return valor or None


def _booleano(datos: Mapping, campo: str, operacion, *, por_defecto: bool) -> bool:
    valor = datos.get(campo, por_defecto)
    if not isinstance(valor, bool):
        raise AltaDeClienteInvalida(f"{campo} {valor!r} del alta del nodo {operacion.node_id} no es un booleano")
    return valor


def _fecha(datos: Mapping, campo: str, operacion) -> datetime | None:
    crudo = datos.get(campo)
    if crudo is None:
        return None
    try:
        fecha = datetime.fromisoformat(crudo)
    except (TypeError, ValueError) as exc:
        raise AltaDeClienteInvalida(f"{campo} {crudo!r} no es una fecha ISO 8601") from exc
    if fecha.tzinfo is None:
        raise AltaDeClienteInvalida(f"{campo} {crudo!r} no trae zona horaria")
    return fecha


def _datos_de_alta(operacion) -> dict:
    """Valida el payload de `cliente_club.alta` y lo devuelve con los tipos de Python."""
    if operacion.operation_type != TIPO_CLIENTE_ALTA:
        raise AltaDeClienteInvalida(f"se esperaba {TIPO_CLIENTE_ALTA}, llegó {operacion.operation_type!r}")
    if operacion.schema_version != SCHEMA_VERSION:
        raise AltaDeClienteInvalida(
            f"schema {operacion.schema_version} de {TIPO_CLIENTE_ALTA} desconocido (se entiende {SCHEMA_VERSION})"
        )
    datos = operacion.payload
    if datos.get("version") != VERSION:
        raise AltaDeClienteInvalida(
            f"versión {datos.get('version')!r} de los datos de {TIPO_CLIENTE_ALTA} desconocida (se entiende {VERSION})"
        )
    id_nodo = datos.get("cliente_id")
    if isinstance(id_nodo, bool) or not isinstance(id_nodo, int) or id_nodo >= 0:
        raise AltaDeClienteInvalida(
            f"el cliente_id {id_nodo!r} del alta del nodo {operacion.node_id} no es un id provisorio (un entero "
            "negativo): el nodo sólo sube altas con id provisorio"
        )
    observaciones = datos.get("observaciones")
    if observaciones is not None and not isinstance(observaciones, str):
        raise AltaDeClienteInvalida("observaciones no es un texto")
    return {
        "cliente_id": id_nodo,
        "nombre": _texto(datos, "nombre", operacion, obligatorio=True),
        "telefono": _texto(datos, "telefono", operacion),
        "email": _texto(datos, "email", operacion),
        "documento": _texto(datos, "documento", operacion),
        "cuit": _texto(datos, "cuit", operacion),
        "activo": _booleano(datos, "activo", operacion, por_defecto=True),
        "acepta_avisos": _booleano(datos, "acepta_avisos", operacion, por_defecto=True),
        "observaciones": observaciones,
        "creada_at": _fecha(datos, "creada_at", operacion),
    }


# ── En el central: la misma persona ──────────────────────────────────────────

_NO_ALFANUMERICO = re.compile(r"[^0-9A-Za-z]")


def _clave_documento(valor: str | None) -> str:
    """Un documento o CUIT para comparar: sin puntos, guiones ni espacios, en mayúsculas. Vacío si no hay."""
    return _NO_ALFANUMERICO.sub("", valor or "").upper()


def _clave_email(valor: str | None) -> str:
    return (valor or "").strip().lower()


def _clave_nombre(valor: str | None) -> str:
    return " ".join((valor or "").lower().split())


def _hay_choque(existente: Mapping, datos: Mapping) -> bool:
    """Si el cliente del central y el alta tienen **otro** `documento` o `cuit` distinto: no son la misma persona,
    aunque compartan el email."""
    for campo in ("documento", "cuit"):
        a, b = _clave_documento(existente[campo]), _clave_documento(datos[campo])
        if a and b and a != b:
            return True
    return False


def _es_la_misma_persona(existente: Mapping, datos: Mapping) -> bool:
    """Para el reintento de un alta ya mapeada: la clave más fuerte que los dos traen decide; si no comparten ninguna,
    el nombre."""
    for campo in ("documento", "cuit"):
        a, b = _clave_documento(existente[campo]), _clave_documento(datos[campo])
        if a and b:
            return a == b
    a, b = _clave_email(existente["email"]), _clave_email(datos["email"])
    if a and b:
        return a == b
    return _clave_nombre(existente["nombre"]) == _clave_nombre(datos["nombre"])


_COLUMNAS_PARA_COMPARAR = "id, nombre, email, documento, cuit"


def _cliente_existente(conn, datos: Mapping) -> int | None:
    """El cliente activo del central al que corresponde el alta, o `None`. `documento`, después `cuit`, después
    `email`; el primero que encuentra (el de menor id) y no choca con otra clave fuerte. Sin ninguna de las tres claves
    no deduplica."""
    consultas = []
    if _clave_documento(datos["documento"]):
        consultas.append((
            "regexp_replace(upper(documento), '[^0-9A-Z]', '', 'g') = ?", _clave_documento(datos["documento"]),
        ))
    if _clave_documento(datos["cuit"]):
        consultas.append(("regexp_replace(upper(cuit), '[^0-9A-Z]', '', 'g') = ?", _clave_documento(datos["cuit"])))
    if _clave_email(datos["email"]):
        consultas.append(("lower(btrim(email)) = ?", _clave_email(datos["email"])))
    for condicion, valor in consultas:
        filas = conn.execute(
            f"SELECT {_COLUMNAS_PARA_COMPARAR} FROM clientes WHERE activo AND id > 0 AND {condicion} ORDER BY id",
            (valor,),
        ).fetchall()
        for fila in filas:
            existente = {"id": fila[0], "nombre": fila[1], "email": fila[2], "documento": fila[3], "cuit": fila[4]}
            if not _hay_choque(existente, datos):
                return existente["id"]
    return None


def _insertar(conn, datos: Mapping) -> int:
    cursor = conn.execute(
        """INSERT INTO clientes
               (nombre, telefono, email, documento, cuit, activo, acepta_avisos, observaciones, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, now()))""",
        (
            datos["nombre"], datos["telefono"], datos["email"], datos["documento"], datos["cuit"], datos["activo"],
            datos["acepta_avisos"], datos["observaciones"], datos["creada_at"],
        ),
    )
    # `ConnectionWrapper` agrega `RETURNING id` a todo INSERT de una tabla con `id`, y lo deja en `lastrowid`.
    return cursor.lastrowid


# ── En el central: aplicar ───────────────────────────────────────────────────


def aplicar_cliente_alta(conn, operacion) -> None:
    """Aplica `cliente_club.alta` en el central: usa al cliente que ya tiene (la misma persona) o lo crea con su propio
    id, y anota el mapeo `(nodo, 'clientes', id provisorio) -> id`. Todo en la transacción del receptor: o queda el
    cliente y su mapeo, o ninguno. Idempotente.

    Los errores son `ValueError` (revisión manual): un `IntegrityError` ajeno lo leería el receptor como «duplicado»."""
    from libraedge import mapeo

    datos = _datos_de_alta(operacion)
    node_id, id_nodo = operacion.node_id, datos["cliente_id"]

    id_central = mapeo.traducir_id(conn, node_id, TABLA_CLIENTES, id_nodo, exigir=False)
    if id_central is not None:
        # Entregada otra vez (el outbox entrega al menos una vez). Si el cliente mapeado no es esta persona, el nodo
        # reusó un id provisorio (una PC reemplazada con el mismo `node_id`): revisión manual, no se pisa nada.
        fila = conn.execute(
            f"SELECT {_COLUMNAS_PARA_COMPARAR} FROM clientes WHERE id = ?", (id_central,)
        ).fetchone()
        if fila is None:
            raise ClienteDelNodoError(
                f"el alta del cliente {id_nodo} del nodo {node_id} ya estaba mapeada al {id_central} "
                "y ese cliente ya no existe"
            )
        existente = {"id": fila[0], "nombre": fila[1], "email": fila[2], "documento": fila[3], "cuit": fila[4]}
        if not _es_la_misma_persona(existente, datos):
            raise ClienteDelNodoError(
                f"el nodo {node_id} reusó el id provisorio {id_nodo}: ya estaba mapeado al cliente {id_central} del "
                f"central ({existente['nombre']!r}) y ahora llega el alta de {datos['nombre']!r}. Una reserva a ese "
                "id iría a otra persona: revisar a mano"
            )
        return

    id_central = _cliente_existente(conn, datos)
    if id_central is not None:
        logger.info(
            "cliente_club.alta del nodo %s: el cliente provisorio %s es el %s del central (ya existía)",
            node_id, id_nodo, id_central,
        )
    else:
        id_central = _insertar(conn, datos)
    try:
        mapeo.anotar_mapeo(conn, node_id, TABLA_CLIENTES, id_nodo, id_central)
    except mapeo.MapeoEnConflicto as exc:
        raise ClienteDelNodoError(str(exc)) from exc


def aplicadores() -> dict[str, Callable[[Any, Any], None]]:
    """`{operation_type: (conn, operacion) -> None}` de `cliente_club.alta`, para el despachador del central."""
    return {TIPO_CLIENTE_ALTA: aplicar_cliente_alta}


def registrar_en(despachador):
    """Registra `cliente_club.alta` en un `libraedge.sync.despacho.Despachador` (el mismo en que
    `libracommerce.erp.offline.registrar_en` y `reservas_nodo.registrar_en` registraron los suyos) y lo devuelve.
    Registrar dos veces un tipo falla al arrancar (es la regla del `Despachador`)."""
    for tipo, aplicador in aplicadores().items():
        despachador.registrar(tipo, SCHEMA_VERSION, aplicador)
    return despachador
