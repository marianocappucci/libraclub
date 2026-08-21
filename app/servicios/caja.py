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

from datetime import date
from decimal import Decimal

from libracore.db import caja as db_caja
from libracore.db import core as libracore_core
from libracore.db import turnos as db_turnos

#: Los medios que ofrece este producto. Es un subconjunto de los del motor: un
#: complejo de canchas cobra en efectivo, por transferencia o con QR — no tiene
#: cheques ni retenciones.
MEDIOS_PAGO = ("efectivo", "transferencia", "mercadopago", "tarjeta")


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


def cobrar(usuario: dict, monto: Decimal, concepto: str, medio_pago: str,
           referencia: str = "", factura_id: int | None = None) -> dict:
    """Registra un ingreso **en el turno abierto de este usuario**.

    Sin turno abierto no se cobra: el movimiento quedaría sin `turno_id` y por
    lo tanto fuera de todo arqueo — plata que entró y que ningún cierre va a
    contar.
    """
    if medio_pago not in MEDIOS_PAGO:
        raise MedioDePagoInvalido(f"Medio de pago desconocido: {medio_pago!r}")
    turno = turno_abierto(usuario)
    if turno is None:
        raise SinTurnoAbierto("No hay una caja abierta. Abrí el turno antes de cobrar.")
    db_caja.create_caja_movimiento(
        date.today().isoformat(), "ingreso", concepto, float(monto),
        referencia=referencia, factura_id=factura_id,
        usuario_id=int(usuario["id"]), medio_pago=medio_pago, turno_id=turno["id"],
    )
    return db_turnos.get_resumen_turno_caja(turno["id"])


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
