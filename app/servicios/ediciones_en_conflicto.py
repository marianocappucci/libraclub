"""Las ediciones de clientes por revisar: ver los dos cambios y elegir cuál queda (ADR-022, tercer y cuarto addendum).

Cuando la PC del club corrige un cliente que todavía no tenía su número definitivo, el cambio sube como
`cliente_club.edicion` (`clientes_nodo`). Si en la web alguien ya había cambiado ese mismo dato, el central no pisa
nada: toda la operación queda en la revisión manual de LibraEdge (`sync_inbox.status = 'manual_review'`). Este módulo es
lo que le deja a quien atiende la web **ver los dos cambios y elegir cuál queda**, sin pasar por la línea de comandos.

## Qué es «una edición por revisar»

Una operación `cliente_club.edicion` en revisión manual, cuyo cliente ya tiene su número definitivo (el alta se aplicó:
hay mapeo) y que se entiende (el payload es válido y el cliente existe). Se mira el estado de **ahora** y no el texto
del motivo: el motivo es un mensaje, no un contrato. Son de dos clases:

- **Choca**: hoy hay al menos un campo que el central tiene distinto de lo que el nodo vio y de lo que el nodo quiso
  poner. Hay que elegir.
- **Ya no choca** (cuarto addendum): sigue en revisión manual pero ningún campo choca hoy (alguien volvió el dato de la
  web al valor anterior, o la edición esperaba su alta y el alta ya se aplicó). Aplicarla es seguro: no hay nada que
  elegir. Se puede **aplicar** (los campos `se_aplica`; los `igual` ya están) o **descartar**.

Quedan afuera, porque la pantalla no puede resolverlas con seguridad, las que **no se pueden mostrar**: el alta del
cliente todavía no se aplicó (`SinMapeo`: se reintenta en orden al resolver el alta), el payload no se entiende o el
cliente ya no existe en el central. Esas siguen por `libraedge-central revision`.

Cada campo de la edición cae en uno de tres estados (`clientes_nodo.clasificar_campo`, la misma regla del aplicador):

- `conflicto`: la web lo tiene en otro valor. Se elige: **la web** (queda como está) o **la PC** (se pone el valor que
  se cargó en la PC).
- `se_aplica`: la web sigue como estaba cuando se corrigió en la PC. Se aplica sin preguntar.
- `igual`: la web ya tiene el valor nuevo. No hay nada que hacer.

## Cómo se resuelve (`resolver`, `descartar`)

Una sola transacción, sobre la **misma conexión de la sesión** (`reservas_nodo.conexion_de_la_sesion`):

1. Bloquea la fila del cliente (`FOR UPDATE`) y vuelve a mirar el estado de la operación **ya con el candado**: si otra
   persona la resolvió mientras tanto, `EdicionYaResuelta` y no se aplica nada otra vez.
2. **Control optimista**: la pantalla manda el valor de la web que mostró (`vistos`, de cada campo de la edición). Si
   alguno ya no es ése, el cliente cambió de nuevo en la web: `CambioEnLaWeb` (con la vista nueva) y no se pisa nada.
3. Pide una elección (`web` o `pc`) por **cada** campo en conflicto, ni más ni menos.
4. `libraedge.sync.revision.reintentar` con un manejador propio en lugar del aplicador registrado: el manejador pone los
   valores elegidos (más los que no chocaban) y anota la fila de `actividad_log`; el receptor de LibraEdge deja la
   operación `applied` y confirma todo junto. Es la API de la librería (`revision.reintentar`), no el CLI. Quedan
   `resuelto_por` y `resolucion = 'reintentada y aplicada'` en `sync_inbox`, igual que con `libraedge-central revision
   reintentar`; lo que se eligió, campo por campo, queda en `actividad_log`.

`resolver` no usa `descartar` de la librería: dejaría la operación `discarded` y el nodo, al reenviarla, recibiría
«descartada en el central» en vez de `duplicate` (ver `libraedge.sync.receiver`). Una edición que **ya no choca** se
aplica con este mismo `resolver`, sin elecciones: no hay una segunda copia del camino.

`descartar` (cuarto addendum) es la otra salida, sin vuelta atrás: deja la operación `discarded` con
`libraedge.sync.revision.descartar` (con motivo y quién) y no toca al cliente. Tiene las mismas garantías: una
transacción con el cliente en `FOR UPDATE`, el estado vuelto a mirar (`EdicionYaResuelta`), el control optimista con
`vistos` (`CambioEnLaWeb`: si el dato volvió a chocar no se descarta algo que la persona no vio) y su fila en
`actividad_log`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.servicios import clientes_nodo, reservas_nodo
from app.servicios.clientes_nodo import (
    CAMPO_EN_CONFLICTO,
    CAMPO_SE_APLICA,
    CAMPOS_EDITABLES,
    TABLA_CLIENTES,
    TIPO_CLIENTE_EDICION,
)

#: Cómo se llama cada campo en la pantalla y en el log de actividad (sin jerga).
ETIQUETAS_DE_CAMPO = {
    "nombre": "Nombre",
    "telefono": "Teléfono",
    "email": "Email",
    "documento": "Documento",
    "cuit": "CUIT",
    "observaciones": "Observaciones",
    "activo": "Activo",
    "acepta_avisos": "Acepta avisos",
}

#: Las dos opciones de cada campo en conflicto.
ELEGIR_WEB = "web"
ELEGIR_PC = "pc"
ELECCIONES = (ELEGIR_WEB, ELEGIR_PC)
_TEXTO_DE_ELECCION = {ELEGIR_WEB: "lo de la web", ELEGIR_PC: "lo de la PC"}

MENSAJE_SOLO_EN_LA_WEB = "Estos cambios se resuelven desde la web, no desde la PC del club."

#: El motivo que queda en `sync_inbox.resolucion` al descartar (la librería lo exige). La PC del club lo lee si reenvía.
MOTIVO_DE_DESCARTE = "Descartada a mano desde la web: el cliente se dejó como estaba en la web."


class EdicionEnRevisionError(Exception):
    """Base de lo que puede salir mal al resolver. La API lo traduce a un código HTTP."""


class EdicionNoEncontrada(EdicionEnRevisionError, LookupError):
    """No hay una edición de cliente en revisión con ese identificador."""


class EdicionYaResuelta(EdicionEnRevisionError):
    """Otra persona ya la resolvió (o el motor la aplicó): no se vuelve a aplicar."""


class EleccionInvalida(EdicionEnRevisionError, ValueError):
    """Falta elegir en algún campo, se eligió en uno que no choca, o la elección no es `web` ni `pc`."""


class CambioEnLaWeb(EdicionEnRevisionError):
    """El cliente cambió de nuevo en la web desde que se mostró la pantalla: la pantalla recarga en vez de pisar."""


class EdicionNoAplicable(EdicionEnRevisionError):
    """El receptor de LibraEdge la rechazó al aplicarla (el cliente ya no existe, un valor inválido): sigue en revisión,
    con el motivo nuevo."""


@dataclass(frozen=True)
class CampoEnRevision:
    campo: str
    etiqueta: str
    #: `conflicto`, `se_aplica` o `igual` (`clientes_nodo.clasificar_campo`).
    estado: str
    #: Lo que la PC tenía cuando se corrigió.
    antes: Any
    #: Lo que hay hoy en la web.
    web: Any
    #: Lo que se cargó en la PC.
    pc: Any


@dataclass(frozen=True)
class EdicionEnRevision:
    operacion_id: str
    #: El número definitivo del cliente (el de la web).
    cliente_id: int
    #: Cómo se llama hoy en la web.
    cliente_nombre: str
    recibida_at: str | None
    campos: list[CampoEnRevision] = field(default_factory=list)

    @property
    def en_conflicto(self) -> list[CampoEnRevision]:
        return [c for c in self.campos if c.estado == CAMPO_EN_CONFLICTO]

    @property
    def ya_no_choca(self) -> bool:
        """Sigue en revisión pero hoy no hay nada para elegir: se puede aplicar (o descartar) sin riesgo."""
        return not self.en_conflicto


# ── Leer ─────────────────────────────────────────────────────────────────────


def _hay_inbox(conn) -> bool:
    """Si esta base tiene la tabla de LibraEdge. Toda instancia migrada la tiene (`0014_libraedge`); preguntar evita que
    una instalación vieja, sin ella, tire el aviso con un error."""
    return conn.execute("SELECT to_regclass('sync_inbox') IS NOT NULL").fetchone()[0]


def _operacion(conn, operacion_id: str):
    """`(estado, operación, recibida_at)` de la fila de `sync_inbox`, o `None` si no existe. La operación es `None` si
    no se guardó su contenido (las aplicadas)."""
    from libraedge.domain.sync import OutboxOperation

    fila = conn.execute(
        "SELECT status, operation_json, received_at FROM sync_inbox WHERE operation_id = ?", (operacion_id,)
    ).fetchone()
    if fila is None:
        return None
    estado, crudo, recibida = fila[0], fila[1], fila[2]
    if not crudo:
        return estado, None, None if recibida is None else str(recibida)
    datos = json.loads(crudo)
    operacion = OutboxOperation(
        operation_id=datos["operation_id"], node_id=datos["node_id"], sequence=int(datos["sequence"]),
        operation_type=datos["operation_type"], aggregate_type=datos["aggregate_type"],
        aggregate_id=datos["aggregate_id"], occurred_at=datos["occurred_at"],
        schema_version=int(datos["schema_version"]), payload=datos["payload"],
    )
    return estado, operacion, None if recibida is None else str(recibida)


def _id_central(conn, operacion, datos: dict) -> int | None:
    from libraedge import mapeo

    return mapeo.traducir_id(conn, operacion.node_id, TABLA_CLIENTES, datos["cliente_id"], exigir=False)


def _vista(conn, operacion_id: str, operacion, recibida_at: str | None, *, bloquear: bool = False):
    """La edición tal como está **ahora** contra el central, o `None` si no se puede mostrar: el payload no se entiende,
    el alta todavía no se aplicó (no hay mapeo) o el cliente ya no existe. Con `bloquear`, deja la fila del cliente con
    `FOR UPDATE`."""
    try:
        datos = clientes_nodo.leer_edicion(operacion)
    except clientes_nodo.EdicionDeClienteInvalida:
        return None
    cliente_id = _id_central(conn, operacion, datos)
    if cliente_id is None:
        return None
    campos = [c for c in CAMPOS_EDITABLES if c in datos["despues"]]
    fila = conn.execute(
        f"SELECT nombre, {', '.join(campos)} FROM clientes WHERE id = ?{' FOR UPDATE' if bloquear else ''}",
        (cliente_id,),
    ).fetchone()
    if fila is None:
        return None
    nombre, *valores = tuple(fila)
    vistos = []
    for campo, actual in zip(campos, valores, strict=True):
        web = clientes_nodo._valor_editado(campo, actual, operacion)  # noqa: SLF001  (mismo normalizado que el aplicador)
        antes, pc = datos["antes"][campo], datos["despues"][campo]
        vistos.append(CampoEnRevision(
            campo=campo, etiqueta=ETIQUETAS_DE_CAMPO[campo], estado=clientes_nodo.clasificar_campo(antes, pc, web),
            antes=antes, web=web, pc=pc,
        ))
    return EdicionEnRevision(
        operacion_id=operacion_id, cliente_id=cliente_id, cliente_nombre=nombre, recibida_at=recibida_at, campos=vistos
    )


def listar(sesion) -> list[EdicionEnRevision]:
    """Las ediciones de clientes por revisar, de la más vieja a la más nueva: las que chocan y las que ya no chocan
    (`EdicionEnRevision.ya_no_choca`). Sólo lee."""
    from libraedge.sync import revision

    conn = reservas_nodo.conexion_de_la_sesion(sesion)
    if not _hay_inbox(conn):
        return []
    lista = []
    for en_revision in revision.listar_en_revision(conn):
        if en_revision.operation_type != TIPO_CLIENTE_EDICION:
            continue
        leida = _operacion(conn, en_revision.operation_id)
        if leida is None or leida[1] is None:
            continue
        vista = _vista(conn, en_revision.operation_id, leida[1], leida[2])
        if vista is not None:
            lista.append(vista)
    return lista


def _en_revision(conn, operacion_id: str):
    """`(operación, recibida_at)` de una edición que espera, o la excepción que corresponde."""
    leida = _operacion(conn, operacion_id) if _hay_inbox(conn) else None
    if leida is None:
        raise EdicionNoEncontrada(f"No hay ninguna edición {operacion_id!r} para revisar.")
    estado, operacion, recibida = leida
    if estado in ("applied", "discarded"):
        raise EdicionYaResuelta("Esta edición ya se resolvió.")
    if operacion is None or operacion.operation_type != TIPO_CLIENTE_EDICION:
        raise EdicionNoEncontrada(f"No hay ninguna edición {operacion_id!r} para revisar.")
    return operacion, recibida


def detalle(sesion, operacion_id: str) -> EdicionEnRevision:
    """Una edición con sus campos: lo que se muestra para elegir."""
    conn = reservas_nodo.conexion_de_la_sesion(sesion)
    operacion, recibida = _en_revision(conn, operacion_id)
    vista = _vista(conn, operacion_id, operacion, recibida)
    if vista is None:
        raise EdicionNoEncontrada(
            "Esta edición todavía no se puede revisar: el cliente no recibió su número definitivo."
        )
    return vista


# ── Resolver ─────────────────────────────────────────────────────────────────


def _auditar(conn, vista: EdicionEnRevision, elecciones: dict[str, str], cambios: dict[str, Any], usuario: str) -> None:
    """Anota en `actividad_log`, en la transacción de `conn`, quién resolvió y qué eligió en cada campo.

    El formato de la fila es el de `libraauth.auditoria.fila_de_auditoria` (la única definición); el INSERT es el de
    `registrador_dbapi`. `cambios` es `{campo: [lo que había en la web, lo que quedó]}` sólo de lo que de verdad cambió;
    lo elegido en cada campo que chocaba va en el texto de la fila."""
    from libraauth.auditoria import valor_legible

    web = {c.campo: c.web for c in vista.campos}
    diff = {c: [valor_legible(web[c]), valor_legible(nuevo)] for c, nuevo in cambios.items()}
    elegido = "; ".join(
        f"{ETIQUETAS_DE_CAMPO[c.campo]}: {_TEXTO_DE_ELECCION[elecciones[c.campo]]}" for c in vista.en_conflicto
    )
    if vista.ya_no_choca:
        etiqueta = f"{vista.cliente_nombre} · se aplicó a mano lo que se cargó en la PC del club (ya no chocaba)"
    else:
        etiqueta = f"{vista.cliente_nombre} · se resolvió a mano lo que se cargó en la PC del club ({elegido})"
    _anotar_actividad(conn, vista, etiqueta, diff or None, usuario)


def _anotar_actividad(conn, vista: EdicionEnRevision, etiqueta: str, cambios: dict | None, usuario: str) -> None:
    """La fila `editar` / `cliente` de `actividad_log` (resolver y descartar la anotan igual)."""
    from libraauth.auditoria import fila_de_auditoria

    fila = fila_de_auditoria(
        entidad="cliente", accion="editar", entidad_id=vista.cliente_id, etiqueta=etiqueta, cambios=cambios,
        usuario=usuario,
    )
    columnas = ("ts", "usuario", "accion", "entidad", "entidad_id", "descripcion", "cambios")
    fila["ts"] = fila["ts"].strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        f"INSERT INTO actividad_log ({', '.join(columnas)}) VALUES ({', '.join('?' * len(columnas))})",
        tuple(fila[c] for c in columnas),
    )


def _validar_elecciones(vista: EdicionEnRevision, elecciones: dict[str, str]) -> None:
    en_conflicto = {c.campo for c in vista.en_conflicto}
    desconocidos = sorted(set(elecciones) - en_conflicto)
    if desconocidos:
        raise EleccionInvalida(
            "No hace falta elegir en: " + ", ".join(ETIQUETAS_DE_CAMPO.get(c, c) for c in desconocidos) + "."
        )
    faltan = [c.etiqueta for c in vista.en_conflicto if c.campo not in elecciones]
    if faltan:
        raise EleccionInvalida("Falta elegir en: " + ", ".join(faltan) + ".")
    for campo, eleccion in elecciones.items():
        if eleccion not in ELECCIONES:
            raise EleccionInvalida(f"En {ETIQUETAS_DE_CAMPO[campo]} hay que elegir «la web» o «la PC».")


def _validar_vistos(vista: EdicionEnRevision, vistos: dict[str, Any]) -> None:
    """Control optimista: el valor de la web que mostró la pantalla tiene que ser el de ahora, en **todos** los campos
    de la edición (uno que no chocaba puede haber pasado a chocar)."""
    faltan = [c.campo for c in vista.campos if c.campo not in vistos]
    if faltan:
        raise EleccionInvalida("La pantalla tiene que mandar lo que mostró de la web en cada campo.")
    cambiados = [c.etiqueta for c in vista.campos if vistos[c.campo] != c.web]
    if cambiados:
        raise CambioEnLaWeb(
            "Mientras tanto se cambió este cliente en la web (" + ", ".join(cambiados) + "). "
            "Te mostramos cómo está ahora: volvé a elegir."
        )


def _vista_con_candado(conn, operacion_id: str, vistos: dict[str, Any]) -> EdicionEnRevision:
    """Lo común de `resolver` y `descartar`: la edición tal como está ahora, con la fila del cliente bloqueada, el
    estado vuelto a mirar ya con el candado y el control optimista de lo que mostró la pantalla."""
    operacion, recibida = _en_revision(conn, operacion_id)
    vista = _vista(conn, operacion_id, operacion, recibida, bloquear=True)
    if vista is None:
        raise EdicionNoEncontrada(
            "Esta edición todavía no se puede revisar: el cliente no recibió su número definitivo."
        )
    # Con el candado puesto, se mira de nuevo el estado: quien llegó segundo esperó acá a que el primero confirme y
    # ahora la ve `applied` o `discarded`.
    _en_revision(conn, operacion_id)
    _validar_vistos(vista, vistos)
    return vista


def resolver(
    sesion,
    operacion_id: str,
    elecciones: dict[str, str],
    vistos: dict[str, Any],
    *,
    usuario: str,
    usuario_id: int | None,
) -> list[str]:
    """Aplica lo elegido y da la operación por resuelta. Devuelve los campos que se cambiaron en el cliente. Una edición
    que ya no choca se resuelve igual, con `elecciones` vacías.

    No commitea de más: el receptor de LibraEdge confirma la transacción de la sesión cuando deja la operación
    `applied`. Ante cualquier error deshace todo. Ver el docstring del módulo."""
    from libraedge.sync import revision

    conn = reservas_nodo.conexion_de_la_sesion(sesion)
    try:
        vista = _vista_con_candado(conn, operacion_id, vistos)
        _validar_elecciones(vista, elecciones)

        cambios: dict[str, Any] = {}
        for c in vista.campos:
            if c.estado == CAMPO_SE_APLICA or (c.estado == CAMPO_EN_CONFLICTO and elecciones[c.campo] == ELEGIR_PC):
                cambios[c.campo] = c.pc

        def aplicar(conn_, _operacion) -> None:
            if cambios:
                asignaciones = ", ".join(f"{campo} = ?" for campo in cambios)  # los nombres salen de CAMPOS_EDITABLES
                conn_.execute(
                    f"UPDATE clientes SET {asignaciones}, updated_at = now(), updated_by = ? WHERE id = ?",
                    (*cambios.values(), usuario_id, vista.cliente_id),
                )
            _auditar(conn_, vista, elecciones, cambios, usuario)

        resultado = revision.reintentar(conn, operacion_id, aplicar, usuario)
    except BaseException:
        conn.rollback()
        raise
    if resultado.result == "duplicate":
        raise EdicionYaResuelta("Esta edición ya se resolvió.")
    if resultado.result != "accepted":
        raise EdicionNoAplicable(resultado.error or "No se pudo aplicar.")
    return list(cambios)


def descartar(sesion, operacion_id: str, vistos: dict[str, Any], *, usuario: str) -> None:
    """Cierra la edición sin aplicarla (`discarded`): el cliente queda como está en la web. **No tiene vuelta atrás.**

    Mismas garantías que `resolver` (`_vista_con_candado`). `revision.descartar` de la librería commitea: la fila de
    `actividad_log` se escribe antes, en la misma transacción, y confirman juntas. Ante cualquier error deshace todo."""
    from libraedge.sync import revision

    conn = reservas_nodo.conexion_de_la_sesion(sesion)
    try:
        vista = _vista_con_candado(conn, operacion_id, vistos)
        _anotar_actividad(
            conn, vista, f"{vista.cliente_nombre} · se descartó lo que se cargó en la PC del club", None, usuario
        )
        revision.descartar(conn, operacion_id, MOTIVO_DE_DESCARTE, usuario)
    except BaseException:
        conn.rollback()
        raise
