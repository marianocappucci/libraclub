"""El recibo no fiscal de un turno: el papel que se lleva el jugador cuando paga.

Es un comprobante «no válido como factura». No lleva CAE ni pasa por ARCA: dice
cuánto entró, cuándo y por qué medio. La factura sigue siendo otra acción
(`servicios/facturacion.py`); facturar y cobrar no son lo mismo
(`servicios/caja.py`).

## Qué se reusa del motor

El papel lo dibuja `libracore.pdf_generator.generate_pdf_recibo_doc`, el mismo
recibo A4 de ContaLibra (membrete del emisor, «RECIBIDO DE», la suma, el detalle
de pagos y el pie «Documento no válido como factura»). Acá sólo se arma el
`dict` que ese generador espera. Los tickets de 80 mm de la familia
(`generar_ticket_venta`) no sirven para esto: su leyenda «no válido como
factura» está atada a una factura pendiente de salir sin conexión y promete
«La factura se emite al volver la conexión», que acá sería mentira.

## Por qué el recibo no se guarda en `recibos`

`libracore.recibos` emite un recibo **numerado y guardado** contra un origen
(factura, venta, pago a cuenta o asiento del libro de terceros). Un cobro de
reserva no es ninguno de los cuatro: `create_recibo` rechaza cualquier otro
`origen_tipo`, y inventar acá uno que el motor no conoce es hablar un vocabulario
que no es suyo. Por eso este recibo **se arma en el momento** desde la caja, que
es la fuente de verdad, y no queda registrado en ninguna tabla:

- **Pasa a ser un estado de cuenta, no un papel congelado.** Si después se cobra
  el saldo, el recibo de la misma reserva lista las dos entradas. Sirve para
  dárselo al jugador cuando paga; no reemplaza a un registro numerado.
- **El número es el de la reserva.** `0001-00000123` es sucursal 1, reserva 123:
  citable y estable, pero **no correlativo** y sin anulación propia. Lo que el
  motor tendría que dar para que sea un recibo de verdad —un origen `reserva` en
  `recibos`— está anotado en ADR-028 como lo que se propone llevar al motor.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from libracore import pdf_generator

from app.tiempo import a_local, hoy

MENSAJE_SIN_COBROS = (
    "Este turno todavía no tiene plata cobrada: el recibo se da contra lo que "
    "entró a la caja, así que primero hay que registrar el cobro."
)


class SinCobros(ValueError):
    """No hay plata neta cobrada de la cual dar un recibo (nada entró, o todo se devolvió)."""


def _pesos(valor: Decimal) -> str:
    """`14000` -> `$14.000`, y `14000.5` -> `$14.000,50`. Es el formato de la agenda."""
    entero, coma, decimales = f"{valor:,.2f}".partition(".")
    texto = entero.replace(",", ".")
    return f"${texto}" if decimales == "00" else f"${texto},{decimales}"


def _dia(valor: Any) -> str:
    """`2026-10-28` de una fecha o de un `2026-10-28 14:03:00`, que es como la guarda la caja."""
    return str(valor or "")[:10]


def armar_recibo(
    *,
    reserva_id: int,
    sucursal_id: int | None,
    cancha: str,
    comienza_at: datetime,
    jugador: str | None,
    cuit: str | None,
    total: Decimal,
    cobros: list[dict],
    devoluciones: list[dict],
) -> dict:
    """El `dict` de recibo que espera `generate_pdf_recibo_doc`. Función pura: no toca la base.

    `total` es lo que vale el turno (alquiler más buffet, el mismo número que
    factura el turno); `cobros` y `devoluciones` son los movimientos de caja de
    la reserva. El total del recibo es **lo que quedó**: cobrado menos devuelto.

    Levanta `SinCobros` si lo que quedó es cero o menos: un recibo afirma que
    entró plata, y un turno con su seña devuelta no la tiene.
    """
    pagos = [
        {
            "fecha": _dia(c.get("fecha")),
            "medio_pago": c.get("medio_pago") or "",
            # El movimiento de caja: es lo que permite cruzar el papel con el arqueo.
            "referencia": f"Mov. {c['id']}" if c.get("id") is not None else "",
            "monto": float(Decimal(str(c["monto"]))),
            "caja_movimiento_id": c.get("id"),
        }
        for c in cobros
    ] + [
        {
            "fecha": _dia(d.get("fecha")),
            "medio_pago": d.get("medio_pago") or "",
            "referencia": "Devolución",
            # Resta: el detalle del papel suma de arriba abajo hasta el total.
            "monto": -float(Decimal(str(d["monto"]))),
            "caja_movimiento_id": d.get("id"),
        }
        for d in devoluciones
    ]
    neto = sum((Decimal(str(p["monto"])) for p in pagos), Decimal("0"))
    if neto <= 0:
        raise SinCobros(MENSAJE_SIN_COBROS)

    saldo = max(Decimal("0"), Decimal(str(total)) - neto)
    local = a_local(comienza_at)
    # 🔴 El generador pone el mismo texto en el encabezado del papel
    # (`Comprobante:`, una línea que corta a los ~20 caracteres) y en «En concepto
    # de». Por eso lo que identifica el turno va primero —lo que se lee entero
    # arriba— y el resto (cancha y saldo) sólo se ve completo abajo.
    concepto = f"Turno {local:%d/%m %H:%M} - {cancha}"
    if saldo > 0:
        concepto += f" - saldo {_pesos(saldo)}"
    else:
        concepto += " - pagado"

    return {
        # El número es el de la reserva (ver el docstring del módulo). En un nodo
        # una reserva dada sin conexión tiene un id provisorio negativo: se
        # imprime su valor absoluto, que sigue siendo único en ese equipo.
        "punto_venta": sucursal_id or 1,
        "numero": abs(int(reserva_id)),
        "fecha": hoy().isoformat(),
        "cliente_razon": (jugador or "").strip() or "Consumidor Final",
        "cliente_cuit": cuit or "",
        "cliente_domicilio": "",
        "concepto": concepto,
        "pagos": pagos,
        "total": float(neto),
        "anulado": False,
        "anulado_motivo": "",
        "moneda": "ARS",
    }


def pdf_del_recibo(recibo: dict) -> bytes:
    """El PDF A4 del recibo, listo para imprimir o guardar."""
    return pdf_generator.generate_pdf_recibo_doc(recibo)
