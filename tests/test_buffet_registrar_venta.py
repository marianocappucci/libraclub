# ruff: noqa: F811  -- las fixtures importadas se piden por nombre en cada test
"""La venta del buffet pasa por `registrar_venta` del motor (ADR-072 de LibraCommerce, ADR-021 de LibraClub).

Hasta acá el buffet guardaba su `Sale` por su cuenta (`save_sale` + `confirm_sale`). Para la versión de
escritorio la venta tiene que nacer por `libracommerce.erp.ventas.registrar_venta`, que es el único camino que
llama a `al_registrar_venta` (el gancho por el que el nodo la encola y la sube al central).

Los tests están en dos grupos, y la diferencia importa:

- **Lo que NO cambia** (totales, vínculo a la reserva, caja, stock, factura conjunta, reportes que leen `sales`).
  Se escribieron primero y corrieron verdes contra el buffet viejo: son la prueba de que el cambio no se ve.
- **Lo que cambia por dentro**: que la venta pase por `registrar_venta`, que el gancho deje el vínculo antes de
  que el outbox la encole, que la numeración aguante el prefijo de un nodo, y que sea todo-o-nada. Éstos son los
  que se ponen en rojo con el buffet viejo.
"""

from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest
from libracommerce.erp import offline, ventas
from libracommerce.erp.offline import NodoLocal, Outbox, con_outbox

from app.servicios import buffet as servicio
from tests.conftest import url_del_core
from tests.test_buffet import _reponer, _reserva, api, gaseosa  # noqa: F401  (fixtures y helpers)


def _filas(sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(url_del_core()) as con:
        return con.execute(sql, params).fetchall()


def _consumir(api, sucursal, item_id, cantidad, reserva_id=None, medio="efectivo"):
    cuerpo = {"lineas": [{"item_id": item_id, "cantidad": str(cantidad)}], "reserva_id": reserva_id}
    if reserva_id is None:
        cuerpo["medio_pago"] = medio
    r = api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


# ── Lo que NO cambia ─────────────────────────────────────────────────────


def test_la_venta_de_una_reserva_queda_colgada_de_ella(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa
):
    """🔑 `source_type='reserva'` y `source_id` son lo que después encuentra la factura conjunta."""
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    reserva = _reserva(api, cancha, cliente)

    venta = _consumir(api, sucursal, gaseosa["item_id"], 2, reserva["id"])

    (fila,) = _filas(
        "SELECT source_type, source_id, status, number, total, subtotal, branch_id, occurred_on "
        "FROM sales WHERE id = %s", (venta["id"],))
    tipo, origen, estado, numero, total, subtotal, sucursal_id, fecha = fila
    assert (tipo, origen, estado, numero) == ("reserva", reserva["id"], "confirmed", "BUF-000001")
    assert float(total) == float(subtotal) == 2400.0
    assert sucursal_id == sucursal.id
    assert fecha is not None
    assert venta["reserva_id"] == reserva["id"]
    assert venta["numero"] == "BUF-000001"

    lineas = _filas("SELECT description_snapshot, quantity, unit_price, item_id FROM sale_items WHERE sale_id = %s",
                    (venta["id"],))
    assert [(d, float(q), float(p), i) for d, q, p, i in lineas] == [
        ("Gaseosa 500ml", 2.0, 1200.0, gaseosa["item_id"])]


def test_la_venta_de_mostrador_queda_como_mostrador_y_entra_a_la_caja(
    api, sucursal, gaseosa, abrir_caja
):
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    abrir_caja(api, sucursal, "0")

    venta = _consumir(api, sucursal, gaseosa["item_id"], 1)

    assert _filas("SELECT source_type, source_id, status FROM sales WHERE id = %s", (venta["id"],)) == [
        ("mostrador", None, "confirmed")]
    ingresos = _filas(
        "SELECT tipo, monto, concepto, referencia, medio_pago FROM caja_movimientos WHERE referencia LIKE 'buffet-%%'")
    assert [(t, float(m), c, r, mp) for t, m, c, r, mp in ingresos] == [
        ("ingreso", 1200.0, "Buffet BUF-000001", f"buffet-{venta['id']}", "efectivo")]


def test_el_buffet_no_ata_la_venta_al_turno_ni_escribe_pagos_del_motor(api, sucursal, gaseosa, abrir_caja):
    """🔑 La caja del buffet sigue siendo la de `servicios/caja.py`, y no la de `registrar_venta`.

    `registrar_venta` escribe un movimiento por cada pago que se le pasa, con otro concepto y sin la
    referencia `buffet-<id>`. El buffet no le pasa pagos: la plata entra una sola vez, como siempre, y el
    arqueo y los reportes por medio ven el mismo movimiento. Tampoco se ata a `venta_links.turno_id`.
    """
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    abrir_caja(api, sucursal, "0")
    _consumir(api, sucursal, gaseosa["item_id"], 1)

    assert _filas("SELECT count(*) FROM ventas_pagos") == [(0,)]
    assert _filas("SELECT count(*) FROM venta_links") == [(0,)]
    assert _filas("SELECT count(*) FROM caja_movimientos WHERE concepto LIKE 'Venta %%'") == [(0,)]
    assert api.get("/api/caja/turnos/actual").json()["resumen"]["efectivo_ventas"] == 1200.0


def test_la_venta_descuenta_stock_en_el_deposito_de_su_sucursal(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa
):
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    reserva = _reserva(api, cancha, cliente)
    venta = _consumir(api, sucursal, gaseosa["item_id"], 2, reserva["id"])

    (deposito,) = _filas("SELECT id FROM locations WHERE name = %s", (f"Buffet #{sucursal.id}",))
    movimientos = _filas(
        "SELECT location_id, quantity_delta, source_id FROM stock_movements "
        "WHERE item_id = %s AND movement_type = 'sale'", (gaseosa["item_id"],))
    assert [(d, float(c), s) for d, c, s in movimientos] == [(deposito[0], -2.0, venta["id"])]
    fila = next(f for f in api.get(f"/api/buffet/productos?sucursal_id={sucursal.id}").json()
                if f["item_id"] == gaseosa["item_id"])
    assert fila["stock"] == 22.0


def test_los_totales_de_la_reserva_suman_solo_sus_consumos(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa
):
    """`total_consumido`, `consumido_de_reservas` y `lineas_para_factura` leen `sales` con SQL directo."""
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    una = _reserva(api, cancha, cliente)
    otra = _reserva(api, cancha, cliente, comienza_at="2026-09-02T20:00:00-03:00")
    _consumir(api, sucursal, gaseosa["item_id"], 2, una["id"])
    _consumir(api, sucursal, gaseosa["item_id"], 1, una["id"])
    _consumir(api, sucursal, gaseosa["item_id"], 4, otra["id"])

    assert servicio.total_consumido(una["id"]) == Decimal("3600")
    assert servicio.total_consumido(otra["id"]) == Decimal("4800")
    assert servicio.consumido_de_reservas([una["id"], otra["id"]]) == {
        una["id"]: Decimal("3600"), otra["id"]: Decimal("4800")}
    assert [(x.description_snapshot, x.quantity) for x in servicio.lineas_para_factura(una["id"])] == [
        ("Gaseosa 500ml", Decimal("2")), ("Gaseosa 500ml", Decimal("1"))]
    assert len(servicio.consumos_de_reserva(una["id"])) == 2


def test_la_factura_conjunta_suma_la_cancha_y_el_consumo_de_esa_reserva(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa, abrir_caja
):
    """El gate de F4, con dos consumos y una venta de mostrador ajena que no tiene que entrar."""
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    abrir_caja(api, sucursal, "0")
    reserva = _reserva(api, cancha, cliente)
    _consumir(api, sucursal, gaseosa["item_id"], 2, reserva["id"])
    _consumir(api, sucursal, gaseosa["item_id"], 1, reserva["id"])
    _consumir(api, sucursal, gaseosa["item_id"], 5)  # mostrador, de otra persona

    factura = api.post(f"/api/reservas/{reserva['id']}/facturar")
    assert factura.status_code == 201, factura.text
    assert factura.json()["total"] == float(reserva["precio"]) + 3600.0

    from libracore.db import facturas as db_facturas

    (guardada,) = db_facturas.get_all_facturas()
    assert [x["description"] for x in guardada["items"]][1:] == ["Gaseosa 500ml", "Gaseosa 500ml"]
    assert [x["qty"] for x in guardada["items"]][1:] == [2.0, 1.0]


def test_el_resumen_comercio_cuenta_las_ventas_del_buffet(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa, abrir_caja
):
    """`resumen_comercio` suma `sales` por `occurred_on`: la venta nueva tiene que caer en el día de hoy."""
    from app.routers.resumen import _comercio
    from app.tiempo import ahora

    _reponer(api, sucursal, gaseosa["item_id"], 24)
    abrir_caja(api, sucursal, "0")
    reserva = _reserva(api, cancha, cliente)
    _consumir(api, sucursal, gaseosa["item_id"], 2, reserva["id"])
    _consumir(api, sucursal, gaseosa["item_id"], 1)

    hoy = ahora().date().isoformat()
    assert _comercio(hoy, hoy)["ventas"] == {"cantidad": 2, "monto": 3600.0}


def test_la_alta_de_la_venta_queda_en_el_log_de_actividad(api, sucursal, gaseosa, abrir_caja):
    """🔑 `/logs` muestra `actividad_log`. El repositorio auditado dejaba ahí la venta; `registrar_venta`
    escribe por SQL y no pasa por el envoltorio, así que el gancho del buffet la anota."""
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    abrir_caja(api, sucursal, "0")
    venta = _consumir(api, sucursal, gaseosa["item_id"], 1)

    filas = _filas("SELECT accion, entidad, entidad_id FROM actividad_log WHERE entidad = 'venta'")
    assert filas == [("crear", "venta", str(venta["id"]))]


# ── La numeración ────────────────────────────────────────────────────────


def test_la_numeracion_es_correlativa_y_la_comparten_el_borrador_y_la_venta(api, sucursal, gaseosa, abrir_caja):
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    abrir_caja(api, sucursal, "0")
    primera = _consumir(api, sucursal, gaseosa["item_id"], 1)
    borrador = servicio.preparar_consumo(
        sucursal_id=sucursal.id, lineas=[(gaseosa["item_id"], Decimal("1"))], usuario_id=None)
    segunda = _consumir(api, sucursal, gaseosa["item_id"], 1)

    assert (primera["numero"], borrador.number, segunda["numero"]) == ("BUF-000001", "BUF-000002", "BUF-000003")


def test_la_numeracion_sigue_a_la_de_una_venta_que_subio_de_un_nodo(api, sucursal, gaseosa, abrir_caja):
    """Una venta de un nodo llega al central con su número (`S02-BUF-000007`). El correlativo propio del central
    no se pisa con él ni vuelve a empezar: sigue de ahí."""
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    abrir_caja(api, sucursal, "0")
    primera = _consumir(api, sucursal, gaseosa["item_id"], 1)
    with psycopg.connect(url_del_core()) as con:
        con.execute("UPDATE sales SET number = 'S02-BUF-000007' WHERE id = %s", (primera["id"],))

    assert _consumir(api, sucursal, gaseosa["item_id"], 1)["numero"] == "BUF-000008"


# ── Lo que cambia por dentro ─────────────────────────────────────────────


def test_el_consumo_pasa_por_registrar_venta(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa, abrir_caja, monkeypatch
):
    """🔴 Sin esto el nodo no ve la venta: el outbox cuelga de `al_registrar_venta`, que sólo llama el motor."""
    llamadas = []
    original = ventas.registrar_venta

    def espia(conn, **kwargs):
        llamadas.append(kwargs)
        return original(conn, **kwargs)

    monkeypatch.setattr(ventas, "registrar_venta", espia)
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    abrir_caja(api, sucursal, "0")
    reserva = _reserva(api, cancha, cliente)

    _consumir(api, sucursal, gaseosa["item_id"], 2, reserva["id"])
    _consumir(api, sucursal, gaseosa["item_id"], 1)

    assert len(llamadas) == 2
    assert [c["estado"] for c in llamadas] == ["cobrada", "cobrada"]
    assert all(c["pagos"] == [] and c["stock_habilitado"] for c in llamadas)


def test_el_gancho_deja_el_vinculo_antes_de_que_el_outbox_encole(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa, abrir_caja, monkeypatch
):
    """🔴 Lo que el PR 11 va a necesitar: con `con_outbox` encima, el payload sale con el vínculo.

    `con_outbox` corre el gancho del producto y recién después encola; si el `UPDATE sales` llegara tarde, la
    venta subiría como `libraedge:<nodo>` y el central no la encontraría para la reserva (ADR-072).
    """
    encoladas = []
    monkeypatch.setattr(offline, "encolar", lambda conn, nodo, tipo, venta_id, payload: encoladas.append(
        (tipo, venta_id, payload)))
    outbox = Outbox(nodo=lambda: NodoLocal(node_id="club-1", prefijo="S02"))
    propios = servicio.ganchos_del_consumo
    monkeypatch.setattr(servicio, "ganchos_del_consumo", lambda reserva_id: con_outbox(propios(reserva_id), outbox))

    _reponer(api, sucursal, gaseosa["item_id"], 24)
    abrir_caja(api, sucursal, "0")
    reserva = _reserva(api, cancha, cliente)
    de_reserva = _consumir(api, sucursal, gaseosa["item_id"], 2, reserva["id"])
    de_mostrador = _consumir(api, sucursal, gaseosa["item_id"], 1)

    assert [t for t, _, _ in encoladas] == [offline.TIPO_VENTA_REGISTRADA] * 2
    (_, id_a, a), (_, id_b, b) = encoladas
    assert (id_a, id_b) == (de_reserva["id"], de_mostrador["id"])
    assert (a["source_type"], a["source_id"]) == ("reserva", reserva["id"])
    assert (b["source_type"], b["source_id"]) == ("mostrador", None)
    assert (a["numero"], b["numero"]) == ("S02-BUF-000001", "S02-BUF-000002")
    assert a["estado"] == "cobrada"
    assert float(a["total"]) == 2400.0
    assert [(float(m["cantidad"]), m["producto_id"]) for m in a["stock"]] == [(-2.0, gaseosa["item_id"])]
    # El número con prefijo de nodo no rompe el correlativo del buffet.
    assert _filas("SELECT number FROM sales ORDER BY id") == [("S02-BUF-000001",), ("S02-BUF-000002",)]


def test_si_el_gancho_falla_no_queda_nada_y_el_numero_no_se_quema(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa, monkeypatch
):
    """Todo-o-nada: la venta, sus líneas, el stock y la anotación del log viajan en una transacción."""
    from dataclasses import replace

    propios = servicio.ganchos_del_consumo

    def roto(conn, venta):
        raise RuntimeError("el outbox se cayó")

    monkeypatch.setattr(servicio, "ganchos_del_consumo", lambda reserva_id: replace(
        propios(reserva_id), al_registrar_venta=roto))
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    reserva = _reserva(api, cancha, cliente)

    with pytest.raises(RuntimeError, match="outbox"):
        _consumir(api, sucursal, gaseosa["item_id"], 2, reserva["id"])

    assert _filas("SELECT count(*) FROM sales") == [(0,)]
    assert _filas("SELECT count(*) FROM sale_items") == [(0,)]
    assert _filas("SELECT count(*) FROM stock_movements WHERE movement_type = 'sale'") == [(0,)]
    monkeypatch.setattr(servicio, "ganchos_del_consumo", propios)
    assert _consumir(api, sucursal, gaseosa["item_id"], 2, reserva["id"])["numero"] == "BUF-000001"


def test_un_producto_inexistente_no_deja_nada_escrito(api, sucursal):
    with pytest.raises(servicio.ProductoInexistente):
        servicio.registrar_consumo(
            sucursal_id=sucursal.id, lineas=[(999, Decimal("1"))], usuario_id=None)
    assert _filas("SELECT count(*) FROM sales") == [(0,)]


def test_configurar_crea_venta_links_que_el_motor_necesita(api):
    """`registrar_venta` lee `venta_links` (por `obtener_venta`) al terminar toda venta cobrada."""
    assert _filas("SELECT to_regclass('public.venta_links')") == [("venta_links",)]
