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


def abrir_turno(usuario: dict, monto_inicial: Decimal, notas: str = "") -> dict:
    """Abre la caja de este usuario con el efectivo con el que arranca."""
    usuario_id = espejar_usuario(usuario)
    if db_turnos.get_turno_activo(usuario_id) is not None:
        raise TurnoYaAbierto("Ya tenés una caja abierta.")
    tid = db_turnos.create_turno(usuario_id, float(monto_inicial), notas)
    return db_turnos.get_turno(tid)


def turno_abierto(usuario: dict) -> dict | None:
    return db_turnos.get_turno_activo(int(usuario["id"]))


def resumen(turno_id: int) -> dict:
    return db_turnos.get_resumen_turno_caja(turno_id)


def registrar_ingreso(usuario: dict, monto: Decimal, concepto: str, medio_pago: str,
                      referencia: str = "", factura_id: int | None = None) -> int:
    """El ingreso en el turno abierto de este usuario. Devuelve el id del movimiento.

    Está separado de `cobrar` porque el cobro con QR **necesita ese id**: lo
    guarda en el pago como marca de que esa plata ya entró (ver
    `PagoDeReserva.caja_movimiento_id`). `cobrar` devuelve el arqueo, que es lo
    que la pantalla de Caja quiere mostrar y donde el id no sirve de nada.
    """
    if medio_pago not in MEDIOS_PAGO:
        raise MedioDePagoInvalido(f"Medio de pago desconocido: {medio_pago!r}")
    turno = turno_abierto(usuario)
    if turno is None:
        raise SinTurnoAbierto("No hay una caja abierta. Abrí el turno antes de cobrar.")
    return db_caja.create_caja_movimiento(
        date.today().isoformat(), "ingreso", concepto, float(monto),
        referencia=referencia, factura_id=factura_id,
        usuario_id=int(usuario["id"]), medio_pago=medio_pago, turno_id=turno["id"],
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


def historial(limite: int = 50) -> list[dict]:
    return db_turnos.get_all_turnos(limit=limite)


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
    mostrador, qr = _patrones_de_reserva(reserva_id)
    conexion = libracore_core.get_connection()
    try:
        filas = conexion.execute(
            "SELECT * FROM caja_movimientos"
            " WHERE tipo='ingreso' AND (referencia LIKE ? OR referencia LIKE ?)"
            " ORDER BY id",
            (mostrador, qr),
        ).fetchall()
    finally:
        conexion.close()
    return [dict(f) for f in filas]


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
