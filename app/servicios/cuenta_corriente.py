"""La cuenta corriente del cliente: qué debe y qué pagó.

El caso real de un complejo: *"el grupo de los martes paga a fin de mes"*. La
cancha se juega, la reserva se carga a la cuenta, y el pago llega después.

🔴 **Se usa `cc_debitos`, el débito explícito, y lo dice el propio motor.** El
saldo de LibraCore se arma con *débitos por venta + débitos por factura +
débitos directos − abonos*, y de esos cuatro:

- **por venta** sale de la tabla `ventas` de LibraCore, que en este producto
  está vacía: las reservas no son ventas de esa tabla.
- **por factura** sale de cruzar `caja_movimientos` con `facturas` **por el CUIT
  del cliente**, y sólo cuando el movimiento se cobró con medio
  `cuenta_corriente` — que no es como cobra este producto.

El docstring de `cuenta_corriente.py` describe exactamente este caso y su
salida: *"para ese caso está `cc_debitos`: el producto registra el débito
explícitamente"*. Es lo que hace VentaLibra.

🔑 **La deuda se registra con `referencia = reserva-<id>`, que es idempotente en
el motor.** Cargar dos veces la misma reserva no fía dos veces lo mismo: la
segunda llamada devuelve el débito que ya estaba. Sin eso, un doble click en
«Cargar a la cuenta» le duplica la deuda a un cliente — y eso se descubre
cuando el cliente reclama.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from libracore.db import core as libracore_core
from libracore.db import cuenta_corriente as db_cc

from app.servicios import caja as servicio_caja


def _espejar_cliente(cliente) -> int:
    """Copia el cliente del dominio a la tabla `clients` de LibraCore.

    Mismo motivo que el espejo de usuarios en `servicios/caja.py`:
    `cc_debitos.cliente_id` y `cc_pagos.cliente_id` tienen FK a `clients` **de
    LibraCore**, y en este producto los clientes viven del lado del dominio.
    Sin el espejo, cargar una deuda falla con violación de clave foránea.

    🔑 **`cuit_dni` se deja vacío a propósito, aunque el cliente tenga CUIT.**
    Es la columna con la que el motor arma el camino *débitos por factura*
    (`clients.cuit_dni = facturas.cliente_cuit`), que suma al saldo los cobros
    con medio `cuenta corriente`. Copiarla abriría ese segundo camino al saldo,
    en paralelo al débito explícito.

    ⚠️ **Hoy ese camino no puede dispararse y por eso no hay test que lo cubra**:
    `MEDIOS_PAGO` de `servicios/caja.py` no incluye `cuenta corriente`, así que
    ningún `caja_movimiento` de este producto matchea. Es un riesgo latente, no
    un bug presente: el día que se agregue ese medio de pago —para marcar una
    factura como fiada— la misma deuda pasaría a contarse dos veces, en silencio.
    Mutación verificada: espejar el `cuit_dni` deja los 11 tests en verde.
    """
    conexion = libracore_core.get_connection()
    try:
        conexion.execute(
            """INSERT INTO clients (id, name) VALUES (?,?)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name""",
            (int(cliente.id), cliente.nombre),
        )
        conexion.commit()
    finally:
        conexion.close()
    return int(cliente.id)


def cargar_reserva(cliente, reserva, usuario: dict) -> float:
    """Fía una reserva: queda como deuda del cliente. Devuelve el saldo nuevo.

    Se espejan **los dos**: `cc_debitos` tiene FK a `clients` por el cliente y
    a `usuarios` por quien lo cargó, las dos tablas de LibraCore. El usuario no
    lo cubre `abrir_turno` porque fiar no abre ningún turno: la plata no entró.
    """
    _espejar_cliente(cliente)
    servicio_caja.espejar_usuario(usuario)
    db_cc.create_cc_debito(
        int(cliente.id), float(reserva.precio), date.today().isoformat(),
        concepto=f"Reserva del {reserva.comienza_at:%d-%m-%Y %H:%M}",
        # Idempotente en el motor: dos clicks no fían dos veces lo mismo.
        referencia=f"reserva-{reserva.id}",
        usuario_id=int(usuario["id"]),
    )
    return saldo(int(cliente.id))


def registrar_pago(cliente, monto: Decimal, medio_pago: str, usuario: dict) -> float:
    """Un pago a cuenta. Entra a la caja **y** baja el saldo del cliente.

    🔑 **Son dos registros y ninguno sobra.** `caja_movimientos` es lo que hay
    en el cajón —y es lo que se arquea al cerrar el turno—; `cc_pagos` es el
    historial de la cuenta del cliente. No es doble conteo: son dos libros que
    responden preguntas distintas, y el saldo se calcula sólo con el segundo.

    Va por `caja.cobrar`, así que **exige turno abierto**: la plata entró
    físicamente, y un pago fuera de turno quedaría fuera del arqueo. Ese orden
    también importa: si no hay turno, `cobrar` corta antes de que el pago se
    escriba en la cuenta, y el cliente no queda con el saldo bajado por plata
    que ninguna caja registró.

    No se valida contra el saldo: pagar de más es un caso real —una seña, un
    adelanto del mes que viene— y queda como saldo a favor.

    🔴 **El movimiento de caja va sin `referencia`, y es a propósito.**
    `create_caja_movimiento` es idempotente por referencia: cualquier cadena
    armada con datos del pago —cliente y fecha, por ejemplo— haría que el
    segundo pago del mismo cliente en el mismo día **no entre a la caja**,
    mientras `cc_pagos` sí registra los dos. El saldo bajaría dos veces y el
    cajón tendría una sola. Un pago no es idempotente: dos pagos son dos pagos,
    y deshacer uno equivocado es otra operación.
    """
    _espejar_cliente(cliente)
    servicio_caja.cobrar(
        usuario, monto, f"Pago a cuenta — {cliente.nombre}", medio_pago,
    )
    db_cc.create_cc_pago(
        int(cliente.id), float(monto), date.today().isoformat(),
        concepto="Pago a cuenta", referencia="", medio_pago=medio_pago,
        caja_id=None, usuario_id=int(usuario["id"]),
    )
    return saldo(int(cliente.id))


def saldo(cliente_id: int) -> float:
    """Lo que el cliente debe. Positivo = debe; negativo = tiene saldo a favor."""
    return db_cc.get_cc_saldo(cliente_id)


def movimientos(cliente_id: int) -> list[dict]:
    """El extracto del cliente.

    Cada movimiento trae `tipo` (`debito` o `credito`) y un `monto` **siempre
    positivo**: el signo lo pone el tipo, no el número.
    """
    return db_cc.get_cc_movimientos(cliente_id)


def deudores() -> list[dict]:
    """Los clientes con movimientos en la cuenta, ordenados por saldo."""
    return db_cc.get_clientes_con_saldo_cc()
