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
- `cliente_club.edicion` (mismo `aggregate_id`): la corrección de un cliente **provisorio** (ver «Editar un cliente
  provisorio»).

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

## Editar un cliente provisorio (ADR-022, segundo addendum)

Un cliente dado de alta sin conexión sigue siendo **provisorio** (id negativo) hasta que el alta sube y el mapeo baja
por el espejo: horas o días en un club sin internet. En ese lapso el mostrador puede corregirlo (un teléfono mal
anotado, un documento que faltaba, darlo de baja): `editar` actualiza la fila local y encola **`cliente_club.edicion`**.

- **Siempre detrás del alta, nunca reescribiendo el payload pendiente.** No se toca la operación `cliente_club.alta`
  aunque todavía no haya subido: el worker puede tenerla en vuelo, reescribirla no es atómico con el envío, y habría dos
  caminos (alta pendiente / alta subida) donde hoy hay uno. El outbox sube por `(node_id, sequence)` (ADR-020 de
  libraedge), así que la edición llega después del alta y su mapeo ya existe. Si el alta quedó en revisión manual, la
  edición también (`SinMapeo`) y se reintenta en orden al resolverla.
- **Payload `version 1`**: `cliente_id` (negativo), `antes` y `despues` (los mismos campos, sólo los que
  **cambiaron**) y `editada_at`. Los campos son `nombre`, `telefono`, `email`, `documento`, `cuit`,
  `observaciones`, `activo` y `acepta_avisos`. `antes` es lo que el nodo tenía al editar: es la **base** de la
  comparación del central.
- **Qué hace el central** (`aplicar_cliente_edicion`): traduce el id con el mapeo y compara, campo por campo, el valor
  actual del central con la base del nodo. Si ya es el valor nuevo, no hace nada (idempotente); si sigue siendo la base,
  lo cambia; si es **otro** valor —alguien lo editó en el central mientras tanto, o el alta se unió a un cliente que el
  central ya tenía con otros datos— **no aplica nada**: toda la operación va a revisión manual (`EdicionEnConflicto`,
  con el campo, lo del central y lo del nodo), y quien opera el central la reintenta o la descarta
  (`libraedge-central revision`). **A confirmar con el humano**: la alternativa es «gana el último por campo».
- **No vuelve a deduplicar**: cambiar el `documento` o el email no busca a otra persona (el maestro no tiene clave
  única); un duplicado se junta a mano, como siempre.
- Un cliente **definitivo** (id positivo, el del central) sigue sin editarse en el nodo. Y borrar un provisorio tampoco:
  se lo da de baja (`activo = false`), que es una edición.

## En el nodo: las guardas

`clientes` es una tabla que el nodo espeja, y con `AltaEnNodo("clientes")` en el aprovisionamiento sólo deja escribir
las filas con id negativo (ADR-019 de libraedge: cualquier otra da SQLSTATE `LE001`). Lo que la base rechazaría con un
500 se contesta antes con un 409 claro:

- editar o borrar un cliente **del central**: **409 `sin_conexion`** si el nodo no está en línea (misma decisión que con
  las reservas del central) y **409 `solo_en_el_central`** si lo está. Un cliente **provisorio** se edita (ver arriba)
  pero no se borra (**409 `solo_en_el_central`**: se lo da de baja);
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
from sqlalchemy.orm.exc import StaleDataError

from app.servicios import reservas_nodo

logger = logging.getLogger(__name__)

#: La forma de los `datos` de la operación. Si cambia, sube: el central rechaza lo que no entiende.
VERSION = 1
#: El `schema_version` de la `OutboxOperation`: el mismo que usa `libracommerce.erp.offline`.
SCHEMA_VERSION = 1

TIPO_CLIENTE_ALTA = "cliente_club.alta"
TIPO_CLIENTE_EDICION = "cliente_club.edicion"
TIPOS = (TIPO_CLIENTE_ALTA, TIPO_CLIENTE_EDICION)

#: Los datos del cliente que el mostrador corrige, y que viajan en `cliente_club.edicion`: los del alta.
CAMPOS_DE_TEXTO = ("nombre", "telefono", "email", "documento", "cuit", "observaciones")
CAMPOS_BOOLEANOS = ("activo", "acepta_avisos")
CAMPOS_EDITABLES = CAMPOS_DE_TEXTO + CAMPOS_BOOLEANOS

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
    "Un cliente dado de alta sin conexión se puede corregir, pero no borrar hasta que suba al central: dalo de baja."
)
MENSAJE_YA_SUBIO = (
    "Este cliente ya subió al central y recibió su número definitivo: actualizá la lista y corregilo desde ahí."
)
MENSAJE_PORTAL_SOLO_EN_EL_CENTRAL = (
    "El portal de jugadores es del central: el equipo del local no registra cuentas."
)


class ClienteDelNodoError(ValueError):
    """Un alta de cliente del nodo que el central no puede aplicar. Es un `ValueError` a propósito: el receptor de
    LibraEdge la manda a revisión manual y el nodo no traba la cola (ADR-020 de libraedge)."""


class AltaDeClienteInvalida(ClienteDelNodoError):
    """El payload de `cliente_club.alta` no se entiende o trae algo que el central no puede escribir."""


class EdicionDeClienteInvalida(ClienteDelNodoError):
    """El payload de `cliente_club.edicion` no se entiende o trae algo que el central no puede escribir."""


class EdicionEnConflicto(ClienteDelNodoError):
    """Alguien cambió en el central un campo que el nodo también corrigió (o el alta se unió a un cliente con otros
    datos): no se aplica nada y la operación espera a quien opera el central (revisión manual)."""


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
    - `al_editar_cliente`: `(conn, datos)`, como `al_crear_cliente` para la corrección de un cliente provisorio: corre
      adentro de la transacción de la edición y, si levanta, el cambio no queda.
    """

    nodo: Callable[[], str | None]
    id_provisorio: Callable[[Any], int]
    al_crear_cliente: Callable[[Any, dict], None] = _nada
    en_linea: Callable[[], bool] = _sin_conexion
    al_editar_cliente: Callable[[Any, dict], None] = _nada


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

    def al_editar_cliente(conn, datos: dict) -> None:
        local = outbox.nodo()
        if local is not None:
            encolar_edicion(conn, local, datos)

    return ClientesEnNodo(
        nodo=nodo, id_provisorio=id_provisorio, al_crear_cliente=al_crear_cliente, en_linea=outbox.en_linea,
        al_editar_cliente=al_editar_cliente,
    )


def encolar_alta(conn, nodo, datos: Mapping[str, Any]):
    """Encola `cliente_club.alta` **dentro de la transacción de `conn`**. `nodo` es el `NodoLocal` de libracommerce."""
    # `_encolar` es el mismo que usan `offline_caja`, `offline_clientes` y `reservas_nodo`: no hay uno público.
    from libracommerce.erp.offline_caja import _encolar

    return _encolar(conn, nodo, TIPO_CLIENTE_ALTA, AGREGADO_CLIENTE, datos["cliente_id"], datos)


def encolar_edicion(conn, nodo, datos: Mapping[str, Any]):
    """Encola `cliente_club.edicion` **dentro de la transacción de `conn`**. Va al mismo agregado que el alta."""
    from libracommerce.erp.offline_caja import _encolar

    return _encolar(conn, nodo, TIPO_CLIENTE_EDICION, AGREGADO_CLIENTE, datos["cliente_id"], datos)


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


def _limpio(campo: str, valor: Any) -> Any:
    """El valor de un campo como viaja y como se compara: el texto sin espacios de los bordes y `None` si queda vacío;
    los booleanos, `bool` (un `acepta_avisos` nulo es `True`, como en el alta)."""
    if campo in CAMPOS_BOOLEANOS:
        return True if valor is None else bool(valor)
    if valor is None:
        return None
    return str(valor).strip() or None


def datos_de_edicion(cliente_id: int, antes: Mapping[str, Any], despues: Mapping[str, Any], *,
                     editada_at: datetime | None = None) -> dict:
    """El payload de `cliente_club.edicion`: sólo los campos que cambiaron, con su valor anterior (la base de la
    comparación del central) y el nuevo."""
    return {
        "version": VERSION,
        "cliente_id": cliente_id,
        "antes": dict(antes),
        "despues": dict(despues),
        "editada_at": _iso(editada_at or datetime.now(UTC)),
    }


def editar(sesion, cliente, datos: Mapping[str, Any]) -> bool:
    """Aplica `datos` (los campos de `ClienteEntrada`) al `cliente` y devuelve si **encoló** una edición.

    Fuera de un nodo, o con un cliente del central, es el `setattr` de siempre y nada más (la guarda
    `exigir_cliente_editable` ya dejó afuera al del central en un nodo). Con un cliente **provisorio** en un nodo,
    además de actualizar la fila local encola `cliente_club.edicion` **en la misma transacción**, con sólo lo que
    cambió; si no cambió nada, no encola nada. Si el encolado falla, el cambio tampoco queda. No commitea.

    Si entre que se leyó el cliente y se guardó el nodo le recibió su id definitivo (la fila provisoria desapareció),
    levanta `SoloEnElCentral` (409): se corrige ya desde la lista nueva."""
    if not en_un_nodo() or not es_provisorio(cliente.id):
        for campo, valor in datos.items():
            setattr(cliente, campo, valor)
        return False

    antes = {c: _limpio(c, getattr(cliente, c)) for c in CAMPOS_EDITABLES if c in datos}
    despues = {c: _limpio(c, datos[c]) for c in antes}
    cambiados = [c for c in antes if antes[c] != despues[c]]
    for campo, valor in datos.items():
        setattr(cliente, campo, valor)
    if not cambiados:
        return False
    try:
        sesion.flush()
    except StaleDataError as exc:
        sesion.rollback()
        raise SoloEnElCentral(MENSAJE_YA_SUBIO) from exc
    conn = reservas_nodo.conexion_de_la_sesion(sesion)
    if _configuracion is not None:
        _configuracion.al_editar_cliente(
            conn, datos_de_edicion(cliente.id, {c: antes[c] for c in cambiados}, {c: despues[c] for c in cambiados})
        )
    return True


# ── En el nodo: las guardas ──────────────────────────────────────────────────


def _en_linea() -> bool:
    try:
        return bool(_configuracion.en_linea()) if _configuracion is not None else False
    except Exception:
        logger.exception("No se pudo saber si el nodo está en línea: se toma como sin conexión")
        return False


def _exigir_del_central() -> None:
    """Lo que se contesta cuando el cliente es del central: `SinConexion` (409 `sin_conexion`) si el nodo no está en
    línea, `SoloEnElCentral` (409 `solo_en_el_central`) si lo está."""
    if _en_linea():
        raise SoloEnElCentral(MENSAJE_DEL_CENTRAL)
    raise SinConexion(MENSAJE_SIN_CONEXION)


def exigir_cliente_editable(cliente_id: int) -> None:
    """En un nodo, editar un cliente sólo se puede si es **provisorio** (se dio de alta en este nodo: su corrección
    sube como `cliente_club.edicion`). El del central es de sólo lectura. Fuera de un nodo no hace nada.

    Levanta `SinConexion` (409 `sin_conexion`) si el nodo no está en línea, y `SoloEnElCentral` (409
    `solo_en_el_central`) si lo está."""
    if not en_un_nodo() or es_provisorio(cliente_id):
        return
    _exigir_del_central()


def exigir_cliente_modificable(cliente_id: int) -> None:
    """En un nodo, **borrar** un cliente no se puede: el del central es de sólo lectura y el provisorio ya subió con su
    alta (se lo da de baja, que es una edición). Fuera de un nodo no hace nada.

    Levanta `SinConexion` (409 `sin_conexion`) si el nodo no está en línea, y `SoloEnElCentral` (409
    `solo_en_el_central`) si lo está o si el cliente todavía es provisorio."""
    if not en_un_nodo():
        return
    if es_provisorio(cliente_id):
        raise SoloEnElCentral(MENSAJE_PROVISORIO)
    _exigir_del_central()


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


def _valor_editado(campo: str, valor: Any, operacion, *, obligatorio: bool = False) -> Any:
    """Un valor de `antes` o `despues` de `cliente_club.edicion`, validado con los mismos límites que el alta. Los
    textos llegan ya sin espacios de los bordes y `None` si estaban vacíos."""
    quien = f"la edición del nodo {operacion.node_id}"
    if campo in CAMPOS_BOOLEANOS:
        if not isinstance(valor, bool):
            raise EdicionDeClienteInvalida(f"{campo} {valor!r} de {quien} no es un booleano")
        return valor
    if valor is None:
        if obligatorio:
            raise EdicionDeClienteInvalida(f"{quien} deja {campo} vacío")
        return None
    if not isinstance(valor, str):
        raise EdicionDeClienteInvalida(f"{campo} {valor!r} de {quien} no es un texto")
    valor = valor.strip()
    if not valor:
        if obligatorio:
            raise EdicionDeClienteInvalida(f"{quien} deja {campo} vacío")
        return None
    if len(valor) > _LARGOS.get(campo, 10_000_000):
        raise EdicionDeClienteInvalida(f"{campo} de {quien} pasa de {_LARGOS[campo]} caracteres")
    return valor


def _datos_de_edicion(operacion) -> dict:
    """Valida el payload de `cliente_club.edicion` y lo devuelve con los tipos de Python."""
    if operacion.operation_type != TIPO_CLIENTE_EDICION:
        raise EdicionDeClienteInvalida(f"se esperaba {TIPO_CLIENTE_EDICION}, llegó {operacion.operation_type!r}")
    if operacion.schema_version != SCHEMA_VERSION:
        raise EdicionDeClienteInvalida(
            f"schema {operacion.schema_version} de {TIPO_CLIENTE_EDICION} desconocido (se entiende {SCHEMA_VERSION})"
        )
    datos = operacion.payload
    if datos.get("version") != VERSION:
        raise EdicionDeClienteInvalida(
            f"versión {datos.get('version')!r} de los datos de {TIPO_CLIENTE_EDICION} desconocida "
            f"(se entiende {VERSION})"
        )
    id_nodo = datos.get("cliente_id")
    if isinstance(id_nodo, bool) or not isinstance(id_nodo, int) or id_nodo >= 0:
        # Defensa en profundidad: `traducir_id` deja pasar un id positivo tal cual, y el nodo no edita clientes del
        # central. Una edición con un id definitivo editaría a otra persona.
        raise EdicionDeClienteInvalida(
            f"el cliente_id {id_nodo!r} de la edición del nodo {operacion.node_id} no es un id provisorio (un entero "
            "negativo): el nodo sólo sube ediciones de clientes que dio de alta"
        )
    antes, despues = datos.get("antes"), datos.get("despues")
    if not isinstance(antes, dict) or not isinstance(despues, dict) or not despues:
        raise EdicionDeClienteInvalida("la edición no trae `antes` y `despues`, o no cambia ningún campo")
    if set(antes) != set(despues):
        raise EdicionDeClienteInvalida("`antes` y `despues` de la edición no tienen los mismos campos")
    desconocidos = sorted(set(despues) - set(CAMPOS_EDITABLES))
    if desconocidos:
        raise EdicionDeClienteInvalida(f"la edición trae campos que no se editan: {', '.join(desconocidos)}")
    return {
        "cliente_id": id_nodo,
        "antes": {c: _valor_editado(c, antes[c], operacion) for c in despues},
        "despues": {c: _valor_editado(c, despues[c], operacion, obligatorio=c == "nombre") for c in despues},
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


def _en_texto(campo: str, valor: Any) -> str:
    """Un valor para el mensaje de un conflicto."""
    return "(vacío)" if valor is None else repr(valor)


def aplicar_cliente_edicion(conn, operacion) -> None:
    """Aplica `cliente_club.edicion` sobre el cliente que el alta del nodo dejó mapeado.

    Traduce el id con el mapeo (si el alta no se aplicó, `SinMapeo`: revisión manual, y se reintenta en orden al
    resolverla) y compara, **campo por campo**, el valor del central con la base (`antes`) del nodo:

    - ya es el valor nuevo: no hace nada (idempotente: el outbox entrega al menos una vez, y la revisión se reintenta);
    - sigue siendo la base: lo cambia;
    - es **otro** valor: alguien lo cambió en el central mientras tanto. La regla conservadora es **no aplicar nada** de
      la operación (ni siquiera los campos sin conflicto) y mandarla entera a revisión manual (`EdicionEnConflicto`),
      con lo que tiene el central y lo que quería el nodo. A confirmar con el humano (ADR-022, segundo addendum).

    Corre en la transacción del receptor y bloquea la fila (`FOR UPDATE`). Los errores son `ValueError`."""
    from libraedge import mapeo

    datos = _datos_de_edicion(operacion)
    node_id, id_nodo = operacion.node_id, datos["cliente_id"]
    id_central = mapeo.traducir_id(conn, node_id, TABLA_CLIENTES, id_nodo)
    campos = list(datos["despues"])
    fila = conn.execute(
        f"SELECT {', '.join(campos)} FROM clientes WHERE id = ? FOR UPDATE", (id_central,)
    ).fetchone()
    if fila is None:
        raise ClienteDelNodoError(
            f"el cliente {id_central} (el {id_nodo} del nodo {node_id}) ya no existe en el central"
        )

    cambios: dict[str, Any] = {}
    en_conflicto: list[str] = []
    for campo, actual in zip(campos, fila, strict=True):
        actual = _valor_editado(campo, actual, operacion)
        nuevo = datos["despues"][campo]
        if actual == nuevo:
            continue
        if actual == datos["antes"][campo]:
            cambios[campo] = nuevo
        else:
            en_conflicto.append(
                f"{campo}: el central tiene {_en_texto(campo, actual)}, el nodo lo cambió de "
                f"{_en_texto(campo, datos['antes'][campo])} a {_en_texto(campo, nuevo)}"
            )
    if en_conflicto:
        raise EdicionEnConflicto(
            f"el nodo {node_id} corrigió al cliente {id_central} (el {id_nodo} del nodo) y en el central ya era otro "
            f"dato: {'; '.join(en_conflicto)}. No se aplicó nada: reintentar si se resuelve a mano, o descartar"
        )
    if not cambios:
        return
    asignaciones = ", ".join(f"{campo} = ?" for campo in cambios)
    conn.execute(
        f"UPDATE clientes SET {asignaciones}, updated_at = now() WHERE id = ?", (*cambios.values(), id_central)
    )


def aplicadores() -> dict[str, Callable[[Any, Any], None]]:
    """`{operation_type: (conn, operacion) -> None}` de `cliente_club.alta` y `cliente_club.edicion`, para el
    despachador del central."""
    return {TIPO_CLIENTE_ALTA: aplicar_cliente_alta, TIPO_CLIENTE_EDICION: aplicar_cliente_edicion}


def registrar_en(despachador):
    """Registra `cliente_club.alta` y `cliente_club.edicion` en un `libraedge.sync.despacho.Despachador` (el mismo en
    que `libracommerce.erp.offline.registrar_en` y `reservas_nodo.registrar_en` registraron los suyos) y lo devuelve.
    Registrar dos veces un tipo falla al arrancar (es la regla del `Despachador`)."""
    for tipo, aplicador in aplicadores().items():
        despachador.registrar(tipo, SCHEMA_VERSION, aplicador)
    return despachador
