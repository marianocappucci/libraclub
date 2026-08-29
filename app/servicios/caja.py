"""La caja por turno: quién la abrió, qué entró, y si cuadra al cerrar.

Compuesto sobre `libracore.db.turnos` y `libracore.db.caja`, que ya traen la
tabla, el arqueo y los medios de pago. Acá va lo que es de este producto: cómo
llega el usuario, qué se cobra, y las reglas de quién puede hacer qué.

🔑 **Factura y cobro NO son lo mismo, y por eso son dos acciones.** La factura es
el documento fiscal; el cobro es la plata que entra al cajón. Se puede facturar
sin haber cobrado (a cuenta corriente) y cobrar sin facturar (una seña). Meterlos
en el mismo botón obliga a elegir mal en los dos casos.

🔴 **El resumen sale de `caja_movimientos`, no de `ventas`.** Las reservas de este
producto no viven en la tabla `ventas` de LibraCore, así que `get_resumen_turno()`
—que hace JOIN contra ella— devolvería siempre vacío y **el arqueo daría cero sin
fallar**. Es el mismo caso que VentaLibra, y por eso el motor tiene la variante
`get_resumen_turno_caja()`.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from libracore import medios_pago
from libracore.db import caja as db_caja
from libracore.db import core as libracore_core
from libracore.db import turnos as db_turnos

#: Los medios que ofrece este producto. Es un **subconjunto deliberado** de los
#: del motor: un complejo de canchas cobra en efectivo, por transferencia, con
#: QR o con tarjeta — no tiene cheques, ni cuenta corriente, ni Cuenta DNI.
#:
#: 🔴 **El subconjunto se elige, pero las claves no se inventan.** Hasta el
#: 2026-08-24 esto era una tupla escrita a mano que decía `tarjeta`, y esa clave
#: no existe en el vocabulario de la familia: ARCA parte la tarjeta en débito y
#: crédito, que son dos condiciones de venta distintas.
#:
#: Cada elemento se valida contra `medios_pago.ELEGIBLES` **al importar el
#: módulo**, así que un medio inventado revienta el arranque en vez de llegar a
#: la caja y aparecer en el cierre como un bucket con el nombre crudo.
#:
#: Ver `wiki/concepts/medios-de-pago-familia-libra.md`.
MEDIOS_PAGO = tuple(
    medios_pago.validar(m) for m in (
        "efectivo", "transferencia", "mercadopago",
        "tarjeta_debito", "tarjeta_credito",
    )
)


class SinTurnoAbierto(RuntimeError):
    """No hay caja abierta. **Cobrar sin turno deja la plata fuera del arqueo**,
    que es exactamente lo que una caja viene a evitar."""


class TurnoYaAbierto(RuntimeError):
    """Ese usuario ya tiene una caja abierta."""


class MedioDePagoInvalido(ValueError):
    pass


class MotivoInvalido(ValueError):
    """Un egreso sin motivo de la lista. Ver `MOTIVOS_DE_EGRESO`."""


class MovimientoAjeno(ValueError):
    """Se quiso anular un movimiento que no es del turno abierto de quien pide."""


class SinCajaEnLaSucursal(RuntimeError):
    """La sucursal no tiene ninguna caja dada de alta, así que no hay dónde
    abrir el turno. Se resuelve dando de alta una, no inventando la caja."""


def espejar_usuario(usuario: dict) -> int:
    """Copia el usuario de `libraauth` a la tabla `usuarios` de LibraCore.

    🔴 **Hace falta porque las dos bases están al revés que en el resto de la
    familia.** `turnos_caja.usuario_id` tiene una FK a `usuarios` **de LibraCore**
    —y la FK se aplica de verdad en PostgreSQL, está verificado—, pero en este
    producto los usuarios viven del lado del dominio, con `libraauth`. Sin este
    espejo, abrir un turno falla con una violación de clave foránea.

    En Gestiolibra y MedLibra no pasa: ahí `usuarios` vive del lado de LibraCore.

    🔑 **El `password_hash` va con un valor imposible, y es seguro.** La columna
    es `NOT NULL` y hay que poner algo; se pone `"!"` —la convención de cuenta
    bloqueada de Unix—, que no es un hash válido de ningún esquema. Y además
    **nada lo lee**: `password_hash` aparece únicamente en el `schema.py` de
    LibraCore, que no autentica en ningún lado. Quien autentica es `libraauth`,
    contra la otra base. Esta fila es puramente referencial.

    Es pública porque la usa también la cuenta corriente:
    `cc_debitos.usuario_id` tiene la misma FK, y fiar una reserva no abre
    ningún turno — así que no puede apoyarse en que `abrir_turno` ya haya
    espejado al usuario.
    """
    conexion = libracore_core.get_connection()
    try:
        conexion.execute(
            """INSERT INTO usuarios (id, username, nombre, email, password_hash, role, activo)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT (id) DO UPDATE SET username = EXCLUDED.username,
                                              nombre = EXCLUDED.nombre""",
            (
                int(usuario["id"]), usuario["username"], usuario.get("name") or usuario["username"],
                usuario.get("email") or "", "!", usuario.get("role") or "operador", True,
            ),
        )
        conexion.commit()
    finally:
        conexion.close()
    return int(usuario["id"])


def abrir_turno(usuario: dict, monto_inicial: Decimal, notas: str = "",
                caja_id: int | None = None) -> dict:
    """Abre el turno de este usuario **sobre un mostrador**, con su efectivo.

    🔑 `caja_id` dice en qué cajón está parado. El arqueo del cierre es el de
    ESE mostrador: sin la caja, dos personas en dos sedes distintas arquean
    contra el mismo montón y ningún reporte por sede es posible.

    Sigue siendo opcional en el motor —los otros cinco productos abren el turno
    suelto— pero en este producto lo exige el router: acá siempre se está parado
    en una sucursal.
    """
    usuario_id = espejar_usuario(usuario)
    if db_turnos.get_turno_activo(usuario_id) is not None:
        raise TurnoYaAbierto("Ya tenés una caja abierta.")
    tid = db_turnos.create_turno(usuario_id, float(monto_inicial), notas, caja_id=caja_id)
    return db_turnos.get_turno(tid)


def turno_abierto(usuario: dict) -> dict | None:
    return db_turnos.get_turno_activo(int(usuario["id"]))


def resumen(turno_id: int) -> dict:
    return db_turnos.get_resumen_turno_caja(turno_id)


def registrar_movimiento(usuario: dict, tipo: str, monto: Decimal, concepto: str,
                         medio_pago: str, referencia: str = "",
                         factura_id: int | None = None) -> int:
    """Un movimiento en el turno abierto: plata que entra o que sale.

    🔑 **El `caja_id` sale del turno, no del pedido.** La pantalla no lo elige:
    ya eligió el mostrador al abrir. Dejarlo en el payload permitiría cargar un
    movimiento en la caja de otra sede desde la sesión de ésta.

    🔴 **Sin turno abierto no se registra nada**, ni ingreso ni egreso: el
    movimiento quedaría sin `turno_id` y por lo tanto fuera de todo arqueo.
    """
    if tipo not in ("ingreso", "egreso"):
        raise ValueError(f"tipo de movimiento desconocido: {tipo!r}")
    if medio_pago not in MEDIOS_PAGO:
        raise MedioDePagoInvalido(f"Medio de pago desconocido: {medio_pago!r}")
    turno = turno_abierto(usuario)
    if turno is None:
        raise SinTurnoAbierto("No hay una caja abierta. Abrí el turno antes de cobrar.")
    return db_caja.create_caja_movimiento(
        date.today().isoformat(), tipo, concepto, float(monto),
        referencia=referencia, factura_id=factura_id,
        usuario_id=int(usuario["id"]), medio_pago=medio_pago, turno_id=turno["id"],
        caja_id=turno.get("caja_id"),
    )


#: Por qué sale plata del cajón. Lista corta y cerrada: un motivo libre convierte
#: el arqueo en algo que no se puede sumar por categoría, y "varios" termina
#: siendo la mitad de los egresos.
MOTIVOS_DE_EGRESO = (
    "Pago a proveedor",
    "Retiro a banco",
    "Sueldos y honorarios",
    "Gasto del complejo",
    "Vuelto / diferencia",
)


def registrar_egreso(usuario: dict, monto: Decimal, motivo: str, detalle: str,
                     medio_pago: str) -> dict:
    """Plata que **sale** del cajón, con su motivo.

    🔴 **Existe porque sin esto el arqueo sólo podía subir.** El resumen del
    motor ya netea los egresos —`SUM(CASE WHEN tipo='egreso' THEN -monto ELSE
    monto END)`— y este producto no tenía forma de registrar uno: sacar plata
    dejaba el cierre con un faltante sin explicación, indistinguible de un error
    de conteo o de un robo.
    """
    if motivo not in MOTIVOS_DE_EGRESO:
        raise MotivoInvalido(f"Motivo de egreso desconocido: {motivo!r}")
    concepto = f"{motivo}{f' — {detalle}' if detalle.strip() else ''}"
    registrar_movimiento(usuario, "egreso", monto, concepto, medio_pago)
    return db_turnos.get_resumen_turno_caja(turno_abierto(usuario)["id"])


def anular_movimiento(usuario: dict, movimiento_id: int) -> dict:
    """Borra un movimiento **del turno abierto de quien lo pide**.

    🔴 **Sólo del turno abierto, y sólo del propio.** Un arqueo cerrado es un
    hecho: borrarle un movimiento después reescribe una diferencia que alguien
    ya firmó. Y el turno de otra persona no es de quien pide.

    🔴 **Se ANULA, no se borra** —desde el 2026-08-28, por pedido del humano:
    *"no deberían poder borrarse, tienen que quedar registrados"*—. La fila queda
    con `anulado=1`, sale de los totales del arqueo y la lista la sigue
    mostrando.

    Borrar rompía tres cosas y ninguna avisaba: el arqueo quedaba con un agujero
    que nadie puede auditar; un **cobro de turno** borrado hace que la reserva
    vuelva a figurar impaga —el pendiente se suma por referencia—; y un **cobro
    por QR** deja `PagoDeReserva.caja_movimiento_id` colgando, con lo cual el
    poll **no** lo vuelve a registrar y la plata desaparece del cajón para
    siempre.
    """
    turno = turno_abierto(usuario)
    if turno is None:
        raise SinTurnoAbierto("No hay una caja abierta.")
    movimientos = db_turnos.get_resumen_turno_caja(turno["id"])["movimientos"]
    if not any(m["id"] == movimiento_id for m in movimientos):
        raise MovimientoAjeno(
            "Ese movimiento no es de tu turno abierto: sólo se puede anular lo "
            "que se cargó en la caja que está abierta ahora."
        )
    db_caja.anular_caja_movimiento(movimiento_id)
    return db_turnos.get_resumen_turno_caja(turno["id"])


def registrar_ingreso(usuario: dict, monto: Decimal, concepto: str, medio_pago: str,
                      referencia: str = "", factura_id: int | None = None) -> int:
    """El ingreso en el turno abierto de este usuario. Devuelve el id del movimiento.

    Está separado de `cobrar` porque el cobro con QR **necesita ese id**: lo
    guarda en el pago como marca de que esa plata ya entró (ver
    `PagoDeReserva.caja_movimiento_id`). `cobrar` devuelve el arqueo, que es lo
    que la pantalla de Caja quiere mostrar y donde el id no sirve de nada.
    """
    # Delega: la escritura es una sola, y así el ingreso también hereda el
    # `caja_id` del turno. Tener dos INSERT es cómo uno de los dos se queda sin
    # una columna nueva y nadie se entera hasta que falta en un reporte.
    return registrar_movimiento(
        usuario, "ingreso", monto, concepto, medio_pago,
        referencia=referencia, factura_id=factura_id,
    )


def cobrar(usuario: dict, monto: Decimal, concepto: str, medio_pago: str,
           referencia: str = "", factura_id: int | None = None) -> dict:
    """Registra un ingreso **en el turno abierto de este usuario**.

    Sin turno abierto no se cobra: el movimiento quedaría sin `turno_id` y por
    lo tanto fuera de todo arqueo — plata que entró y que ningún cierre va a
    contar.
    """
    registrar_ingreso(
        usuario, monto, concepto, medio_pago,
        referencia=referencia, factura_id=factura_id,
    )
    # `turno_abierto` se vuelve a resolver en vez de reusarse: `registrar_ingreso`
    # ya falló si no había turno, así que acá siempre hay uno.
    return db_turnos.get_resumen_turno_caja(turno_abierto(usuario)["id"])


def cerrar_turno(turno_id: int, monto_declarado: Decimal, notas: str = "") -> dict:
    """Cierra el turno y devuelve el arqueo: esperado, declarado y diferencia.

    🔑 **La diferencia se guarda, no se corrige.** Un cierre que no cuadra es un
    dato —faltó plata, sobró, alguien no cargó un cobro— y ajustarlo al número
    esperado borraría justamente lo que hay que mirar.
    """
    return db_turnos.cerrar_turno_caja(turno_id, float(monto_declarado), notas)


def turno_por_id(turno_id: int) -> dict | None:
    return db_turnos.get_turno(turno_id)


def historial(limite: int = 50, usuario_id: int | None = None) -> list[dict]:
    """Los últimos turnos, todos o los de un usuario.

    ⚠️ **La consulta del motor hace `JOIN usuarios`, no `LEFT JOIN`.** Los
    usuarios de este producto viven del lado del dominio y en LibraCore hay un
    **espejo** (`espejar_usuario`); un turno cuyo dueño no esté espejado
    **desaparece de esta lista sin error**. Hoy no puede pasar —abrir un turno
    espeja primero— pero si alguna vez se borra una fila del espejo, el síntoma
    va a ser un historial al que le faltan turnos, no una excepción.
    """
    return db_turnos.get_all_turnos(limit=limite, usuario_id=usuario_id)


# ── El cobro de un turno ───────────────────────────────────────────────────
#
# 🔑 **`facturar_reserva` ya declaraba este modelo y nadie lo implementaba**: su
# docstring dice que *"si hubo seña, la seña y el saldo son dos movimientos de
# caja contra la MISMA factura"*. Hasta el 2026-08-28 ningún cobro en efectivo
# llevaba `factura_id`: la pantalla de Caja carga monto y concepto libre, sin
# vínculo con la reserva ni con el comprobante. El único cruce que existía lo
# llenaba el cobro por QR.
#
# Sin ese vínculo no se puede contestar "¿esta factura está cobrada?", que es lo
# que mantiene apagada la columna de cobrado en las tres pantallas del kit.

#: Con qué arranca la referencia de un cobro de mostrador de una reserva.
PREFIJO_COBRO_DE_RESERVA = "reserva-"

#: El otro prefijo que identifica plata de una reserva: el del cobro por QR, que
#: reusa la referencia de MercadoPago (`servicios/pagos.nueva_referencia`).
#:
#: 🔴 **Los dos hacen falta.** Contar sólo los de mostrador diría que un turno
#: cobrado por QR está impago, y ofrecería cobrarlo de nuevo.
PREFIJO_COBRO_POR_QR = "lc-"


def referencia_de_cobro(reserva_id: int) -> str:
    """La referencia de un cobro de mostrador: identifica la reserva y es única.

    🔴 **El sufijo aleatorio no es decorativo.** `create_caja_movimiento` del
    motor trae idempotencia por `(referencia, factura_id)`: dos movimientos con
    la misma referencia y la misma factura **no se duplican, se descartan en
    silencio**. Con una referencia fija por reserva, cobrar la seña y después el
    saldo registraría el primero y perdería el segundo sin decir nada — plata
    que entró y que ningún arqueo cuenta.

    Es el mismo criterio, y por el mismo motivo, que `pagos.nueva_referencia`.
    """
    return f"{PREFIJO_COBRO_DE_RESERVA}{reserva_id}-{secrets.token_hex(4)}"


def _patrones_de_reserva(reserva_id: int) -> tuple[str, str]:
    """Los dos `LIKE` que matchean la plata de esta reserva y de ninguna otra.

    El guion después del id es lo que separa la reserva 1 de la 12: sin él,
    `reserva-1%` se llevaría los cobros de la 1, la 10 y la 199.
    """
    return (
        f"{PREFIJO_COBRO_DE_RESERVA}{reserva_id}-%",
        f"{PREFIJO_COBRO_POR_QR}{reserva_id}-%",
    )


def cobros_de_reserva(reserva_id: int) -> list[dict]:
    """Los movimientos de caja que son plata de esta reserva, en orden.

    Consulta directa contra `caja_movimientos` de LibraCore: el motor no expone
    una búsqueda por referencia, y agregarla allá con **un** consumidor sería
    inventar una API compartida antes de tener con quién compartirla. Si un
    segundo producto la necesita, ahí se muda. Mismo criterio que
    `espejar_usuario`, unas líneas más arriba.
    """
    # 🔑 **`anulado=0` va en las DOS consultas** —acá y en
    # `cobrado_de_reservas`—. Filtrar en una sola deja al detalle de la reserva
    # y al listado del mostrador diciendo números distintos sobre el mismo turno,
    # que es peor que no filtrar en ninguna: ahí al menos coinciden.
    mostrador, qr = _patrones_de_reserva(reserva_id)
    conexion = libracore_core.get_connection()
    try:
        filas = conexion.execute(
            "SELECT * FROM caja_movimientos"
            " WHERE tipo='ingreso' AND anulado=0"
            " AND (referencia LIKE ? OR referencia LIKE ?)"
            " ORDER BY id",
            (mostrador, qr),
        ).fetchall()
    finally:
        conexion.close()
    return [dict(f) for f in filas]


def cobrado_de_reservas(reserva_ids: Sequence[int]) -> dict[int, Decimal]:
    """Cuánto entró por cada una de varias reservas, en una sola consulta.

    Misma razón que `buffet.consumido_de_reservas`: `cobros_de_reserva` abre y
    cierra una conexión por reserva, y el listado del mostrador las pide de a
    decenas.

    🔑 **El id vuelve de la referencia, no de una columna.** `caja_movimientos`
    no tiene `reserva_id` —es una tabla del motor, y el motor no sabe qué es una
    reserva—: el vínculo es el texto `reserva-<id>-<azar>`. Por eso se filtra con
    los mismos `LIKE` de `_patrones_de_reserva` y después se parsea; usar otro
    criterio acá y otro allá es cómo se separan dos números que deberían ser el
    mismo.

    ⚠️ **Las dos mitades no pesan igual.** El `LIKE` acota el volumen —trae las
    filas candidatas y no la caja entera—, pero el que decide de quién es cada
    peso es `_id_de_referencia`: con los patrones flojos entran filas de más y el
    parseo igual se las atribuye a su reserva. Si alguna vez hay que aflojar uno
    de los dos, que sea el `LIKE`.
    """
    ids = [int(x) for x in reserva_ids]
    if not ids:
        return {}
    condiciones, parametros = [], []
    for reserva_id in ids:
        mostrador, qr = _patrones_de_reserva(reserva_id)
        condiciones.append("referencia LIKE ? OR referencia LIKE ?")
        parametros.extend([mostrador, qr])
    donde = " OR ".join(f"({c})" for c in condiciones)
    conexion = libracore_core.get_connection()
    try:
        filas = conexion.execute(
            "SELECT referencia, monto FROM caja_movimientos"
            f" WHERE tipo='ingreso' AND anulado=0 AND ({donde})",
            tuple(parametros),
        ).fetchall()
    finally:
        conexion.close()
    totales: dict[int, Decimal] = {}
    for fila in filas:
        reserva_id = _id_de_referencia(fila[0])
        if reserva_id is None:
            continue
        totales[reserva_id] = totales.get(reserva_id, Decimal("0")) + Decimal(str(fila[1]))
    return totales


def _id_de_referencia(referencia: str | None) -> int | None:
    """El id de reserva que hay adentro de `reserva-12-ab3f` o `lc-12-ab3f`."""
    if not referencia:
        return None
    for prefijo in (PREFIJO_COBRO_DE_RESERVA, PREFIJO_COBRO_POR_QR):
        if referencia.startswith(prefijo):
            resto = referencia[len(prefijo):].split("-", 1)[0]
            return int(resto) if resto.isdigit() else None
    return None


def total_cobrado(reserva_id: int) -> Decimal:
    """Cuánta plata entró por esta reserva, sumando mostrador y QR."""
    return sum(
        (Decimal(str(m["monto"])) for m in cobros_de_reserva(reserva_id)),
        Decimal("0"),
    )


def vincular_cobros_a_factura(reserva_id: int, factura_id: int) -> int:
    """Ata a la factura los cobros de esa reserva que todavía no lo estén.

    🔑 **Existe porque en un mostrador se cobra antes de facturar tan seguido
    como después.** Pasar `factura_id` en el momento del cobro sólo resuelve un
    orden; el otro deja el comprobante viéndose «sin cobrar» sobre plata que ya
    entró.

    Sólo toca las filas con `factura_id` en `NULL`: reescribir una que ya apunta
    a otro comprobante movería un ingreso de una factura a otra.

    De paso cierra un caso que `cobro_qr` documenta y no podía resolver: si ARCA
    falla, el cobro por QR se registra igual **sin atar**, y hasta ahora quedaba
    así para siempre. Al emitir la factura en el reintento, este vínculo lo
    alcanza.
    """
    mostrador, qr = _patrones_de_reserva(reserva_id)
    conexion = libracore_core.get_connection()
    try:
        cursor = conexion.execute(
            "UPDATE caja_movimientos SET factura_id=?"
            " WHERE factura_id IS NULL AND tipo='ingreso'"
            " AND (referencia LIKE ? OR referencia LIKE ?)",
            (factura_id, mostrador, qr),
        )
        conexion.commit()
        return cursor.rowcount or 0
    finally:
        conexion.close()


# ── Las cajas, como mostradores de una sucursal ────────────────────────────


def cajas_de(sucursal_id: int) -> list[dict]:
    """Los mostradores de esa sede. Puede haber más de uno."""
    return db_caja.get_all_cajas(sucursal_id=sucursal_id)


def caja_de(caja_id: int) -> dict | None:
    return db_caja.get_caja_config(caja_id)


def crear_caja(nombre: str, descripcion: str, medios: list[str], sucursal_id: int) -> dict:
    """Da de alta un mostrador en una sede.

    Los medios se validan contra los de **este producto** y no contra los del
    motor: un complejo no cobra con cheque ni con Cuenta DNI, y ofrecer un medio
    que después el cobro rechaza con un 422 es peor que no ofrecerlo.
    """
    for m in medios:
        if m not in MEDIOS_PAGO:
            raise MedioDePagoInvalido(f"Medio de pago desconocido: {m!r}")
    cid = db_caja.create_caja_config(nombre, descripcion, list(medios), sucursal_id=sucursal_id)
    return db_caja.get_caja_config(cid)


def actualizar_caja(caja_id: int, nombre: str, descripcion: str,
                    medios: list[str], activo: bool) -> dict:
    for m in medios:
        if m not in MEDIOS_PAGO:
            raise MedioDePagoInvalido(f"Medio de pago desconocido: {m!r}")
    db_caja.update_caja_config(caja_id, nombre, descripcion, list(medios), 1 if activo else 0)
    return db_caja.get_caja_config(caja_id)


def borrar_caja(caja_id: int) -> None:
    db_caja.delete_caja_config(caja_id)


def marcar_predeterminada(caja_id: int) -> dict | None:
    """Deja esta caja como la predeterminada **de su sucursal**.

    🔴 **No se usa `db_caja.set_default_caja` del motor, y no es por gusto.**
    Esa función hace `UPDATE cajas SET es_default=0` **sin filtrar nada**, y en
    [[contalibra]] está bien porque no tiene sedes. Acá las cajas pertenecen a
    una sucursal: marcar la predeterminada de una sede **le borraría la de la
    otra**, y el síntoma sería que el mostrador de la otra sede abre el turno
    sobre el cajón equivocado sin que nadie haya tocado nada ahí.

    🔑 **Qué significa ser la predeterminada, medido y no supuesto.** Dos
    cosas, las dos reales: el motor lista las cajas con
    `ORDER BY es_default DESC, nombre`, así que ésta encabeza la lista —y la
    pantalla de Caja la ofrece elegida al abrir el turno—; y el motor **se niega
    a borrarla**, que es lo que evita quedarse sin ninguna.

    ⚠️ Las cajas viejas sin `sucursal_id` se tratan como su propio grupo. No es
    un caso hipotético: las que nacieron antes del 2026-08-28 quedaron en
    `NULL`, y meterlas en la misma bolsa que las de una sede haría que marcar
    cualquiera de las dos apagara a la otra.
    """
    caja = db_caja.get_caja_config(caja_id)
    if caja is None:
        return None
    sucursal_id = caja.get("sucursal_id")
    with libracore_core.get_connection() as conexion:
        if sucursal_id is None:
            conexion.execute("UPDATE cajas SET es_default=0 WHERE sucursal_id IS NULL")
        else:
            conexion.execute(
                "UPDATE cajas SET es_default=0 WHERE sucursal_id=?", (sucursal_id,)
            )
        conexion.execute("UPDATE cajas SET es_default=1 WHERE id=?", (caja_id,))
    return db_caja.get_caja_config(caja_id)


#: Cómo se llama la caja que se crea sola para una sucursal que no tenía
#: ninguna. Se puede renombrar desde la pantalla; el nombre sólo importa la
#: primera vez.
NOMBRE_DE_LA_PRIMERA_CAJA = "Mostrador"


def asegurar_caja_de(sucursal_id: int, nombre_sucursal: str = "") -> dict:
    """La caja de esa sede, creándola si todavía no tiene ninguna. Idempotente.

    🔑 **Existe porque el turno ahora se abre sobre una caja.** Sin esto, una
    instancia que ya venía andando se queda sin poder abrir el turno el día que
    sube: el mostrador entra, no hay ninguna caja para elegir, y no tiene forma
    de crear una porque el alta es de admin.

    Devuelve la primera de la sede si ya hay — **no** la "correcta": con dos
    mostradores cuál es cuál lo decide el operador al abrir, no esta función.
    """
    existentes = cajas_de(sucursal_id)
    if existentes:
        return existentes[0]
    nombre = (
        f"{NOMBRE_DE_LA_PRIMERA_CAJA} {nombre_sucursal}".strip()
        if nombre_sucursal else NOMBRE_DE_LA_PRIMERA_CAJA
    )
    return crear_caja(nombre, "", list(MEDIOS_PAGO), sucursal_id)


def asegurar_cajas_de_todas(sucursales: list[tuple[int, str]]) -> int:
    """Una caja para cada sucursal que no tenga. Devuelve cuántas creó.

    Corre al arrancar la app. Es la migración de datos de las instancias que ya
    venían andando, y es idempotente: en el segundo arranque no crea nada.
    """
    creadas = 0
    for sid, nombre in sucursales:
        if not cajas_de(sid):
            asegurar_caja_de(sid, nombre)
            creadas += 1
    return creadas
