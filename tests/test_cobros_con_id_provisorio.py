# ruff: noqa: F811  -- las fixtures importadas se piden por nombre en cada test
"""Un cobro hecho con el id provisorio de una reserva se atribuye a ella cuando el central le da el definitivo.

La historia (ADR-022, ADR-023 y el addendum de ADR-027): en la PC del club sin conexión una reserva nace con el id
`-1`, su cobro de mostrador se escribe con la referencia `reserva--1-<azar>` y esa columna es un **texto**, que
LibraEdge no puede reescribir cuando el espejo trae la reserva con su id definitivo (`500`). El vínculo entre los dos
ids es `libraedge_mapeo`, que también baja con el espejo y no se borra al reapuntar.

Todos los que leen "cuánto entró por esta reserva" tienen que dar lo mismo. Cuatro lo hacían bien desde ADR-023 porque
pasan por `_ids_equivalentes` (el saldo de la reserva, el listado del mostrador, la grilla de la agenda, el vínculo con
la factura); el quinto, `cobros_netos_por_reserva` (el panel del dueño), leía el id de la referencia a secas y
atribuía la plata al `-1`, que ya no existe: la reserva figuraba sin ingresos.

Datos ficticios. La base hace de nodo y de espejo a la vez, como en `tests/test_nodo_buffet_y_caja.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from libracore.db import caja as db_caja
from libracore.db import core as libracore_core
from libraedge.mapeo import anotar_mapeo

from app.models.reservas import Reserva
from app.servicios import caja as servicio_caja
from app.servicios import panel_del_dueno
from app.tiempo import TZ
from tests.nodo_apoyo import NODO, nodo_apagado  # noqa: F401  (fixture)
from tests.test_nodo_buffet_y_caja import (
    _abrir_turno,
    _cobrar_turno,
    _reserva_del_nodo,
    api,  # noqa: F401  (fixture)
    mostrador,  # noqa: F401  (fixture)
)

#: El "ahora" de estos tests: el turno (1-09-2026 a las 20:00) ya se jugó, así que su plata es de `reservas`.
AHORA = datetime(2026, 9, 10, 12, 0, tzinfo=TZ)
DESDE, HASTA = date(2026, 8, 31), date(2026, 9, 6)


def _renumerar(sesion, provisorio: int, definitivo: int) -> None:
    """Lo que hace el espejo en la PC del club cuando el central da el id definitivo: la reserva pasa de `provisorio` a
    `definitivo` y baja el mapeo. La referencia del cobro **no** cambia (es un texto)."""
    sesion.execute(Reserva.__table__.update().where(Reserva.id == provisorio).values(id=definitivo))
    sesion.commit()
    with libracore_core.get_connection() as conn:
        anotar_mapeo(conn, NODO, "reservas", provisorio, definitivo)
        conn.commit()


@pytest.fixture
def reserva_renumerada(api, sesion, cancha, cliente, mostrador, nodo_apagado, monkeypatch):
    """Una reserva de la PC del club con `-1`, cobrada con ese id y después renumerada a `500`."""
    monkeypatch.setattr(panel_del_dueno, "ahora", lambda: AHORA)
    _reserva_del_nodo(sesion, cancha, cliente, -1)
    nodo_apagado.prender()
    _abrir_turno(api, mostrador)
    _cobrar_turno(api, -1, "5000")
    _renumerar(sesion, -1, 500)
    return 500


def _ingresos_del_panel(api, sucursal) -> dict:
    r = api.get("/api/admin/panel-del-dueno", params={"desde": DESDE.isoformat(), "hasta": HASTA.isoformat()})
    assert r.status_code == 200, r.text
    (fila,) = [s for s in r.json()["por_sucursal"] if s["sucursal_id"] == sucursal.id]
    return fila["ingresos"]


def test_el_cobro_quedo_escrito_con_el_id_provisorio(reserva_renumerada):
    """El punto de partida: la referencia conserva el `-1` (si no, no habría nada que arreglar)."""
    movimientos = servicio_caja.cobros_de_reserva(reserva_renumerada)

    assert [m["referencia"].startswith("reserva--1-") for m in movimientos] == [True]


def test_el_panel_del_dueno_atribuye_a_la_reserva_el_cobro_hecho_con_su_id_provisorio(
    api, sucursal, reserva_renumerada
):
    """🔴 Sin traducir el id de la referencia, la plata caía en la reserva `-1`, que ya no existe: el panel mostraba el
    turno jugado y cobrado con ingresos en cero."""
    ingresos = _ingresos_del_panel(api, sucursal)

    assert ingresos["reservas"] == 5000.0
    assert ingresos["total"] == 5000.0


def test_cobros_netos_por_reserva_da_la_plata_al_id_definitivo_y_no_deja_rastro_del_provisorio(reserva_renumerada):
    assert servicio_caja.cobros_netos_por_reserva() == {500: Decimal("5000")}


def test_los_cobros_de_antes_y_de_despues_de_renumerar_suman_en_la_misma_reserva(
    api, reserva_renumerada, sucursal
):
    """Seña con el provisorio, saldo con el definitivo (ya bajó): una sola reserva, 8.000."""
    _cobrar_turno(api, 500, "3000")

    assert servicio_caja.cobros_netos_por_reserva() == {500: Decimal("8000")}
    assert servicio_caja.cobrado_de_reservas([500]) == {500: Decimal("8000")}
    assert _ingresos_del_panel(api, sucursal)["reservas"] == 8000.0


def test_una_devolucion_hecha_con_el_id_provisorio_resta_de_la_reserva_renumerada(reserva_renumerada):
    """Por ahora la devolución se escribe en el central (`cancelacion.py`), pero el panel no tiene por qué saberlo: lo
    que se lee con el prefijo `devolucion-` se atribuye igual que el cobro."""
    db_caja.create_caja_movimiento(
        "2026-09-02", "ingreso", "seña por QR", Decimal("4000"), referencia="lc--1-ab12cd")
    db_caja.create_caja_movimiento(
        "2026-09-02", "egreso", "devolución", Decimal("1500"), referencia="devolucion-lc--1-ab12cd")

    assert servicio_caja.cobros_netos_por_reserva() == {500: Decimal("7500")}


def test_una_reserva_que_todavia_es_provisoria_sigue_con_su_plata_en_su_id(
    api, sesion, cancha, cliente, mostrador, nodo_apagado
):
    """Sin renumerar (el espejo todavía no la trajo) no hay a quién trasladar: la plata sigue en el `-1`, que es el id
    con el que la reserva existe en la PC del club."""
    _reserva_del_nodo(sesion, cancha, cliente, -1)
    nodo_apagado.prender()
    _abrir_turno(api, mostrador)
    _cobrar_turno(api, -1, "5000")

    assert servicio_caja.cobros_netos_por_reserva() == {-1: Decimal("5000")}


def test_el_mapeo_de_otro_nodo_no_se_cuela(api, sesion, cancha, cliente, mostrador, nodo_apagado):
    """`libraedge_mapeo` guarda los provisorios de todos los nodos: el `-1` de `club-2` no es el `-1` de este."""
    _reserva_del_nodo(sesion, cancha, cliente, -1)
    nodo_apagado.prender()
    _abrir_turno(api, mostrador)
    _cobrar_turno(api, -1, "5000")
    with libracore_core.get_connection() as conn:
        anotar_mapeo(conn, "club-2", "reservas", -1, 777)
        conn.commit()

    assert servicio_caja.cobros_netos_por_reserva() == {-1: Decimal("5000")}


def test_en_el_central_una_referencia_no_se_traduce(api, sesion, cancha, cliente, mostrador, nodo_apagado):
    """Fuera de un nodo el mapeo no se consulta: el central escribe la referencia ya traducida
    (`aplicar_movimiento_de_club`) y no tiene `-N` que buscar."""
    _reserva_del_nodo(sesion, cancha, cliente, 500)
    db_caja.create_caja_movimiento("2026-09-02", "ingreso", "seña", Decimal("5000"), referencia="reserva-500-ab12")
    with libracore_core.get_connection() as conn:
        anotar_mapeo(conn, NODO, "reservas", -1, 500)
        conn.commit()

    assert servicio_caja.cobros_netos_por_reserva() == {500: Decimal("5000")}


# ── Los otros lectores, que ya andaban: se fijan para que no se separen ─────────────────────────────────────────────


def test_todos_los_lectores_de_la_plata_de_una_reserva_dan_lo_mismo(api, reserva_renumerada):
    """El saldo, el listado del mostrador, los totales y el panel salen del mismo cobro."""
    estado = api.get(f"/api/reservas/{reserva_renumerada}/cobros").json()
    assert estado["cobrado"] == 5000.0

    assert servicio_caja.total_cobrado(reserva_renumerada) == Decimal("5000")
    assert servicio_caja.cobrado_de_reservas([reserva_renumerada]) == {reserva_renumerada: Decimal("5000")}
    assert servicio_caja.cobros_netos_por_reserva()[reserva_renumerada] == Decimal("5000")
    assert [m["monto"] for m in servicio_caja.cobros_de_reserva(reserva_renumerada)] == [5000.0]


def test_la_factura_alcanza_los_cobros_hechos_con_el_id_provisorio(reserva_renumerada):
    """`vincular_cobros_a_factura` usa los mismos ids equivalentes: ata el cobro `reserva--1-…` a la factura de la
    reserva `500`."""
    from libracore.db import facturas as db_facturas

    factura_id = db_facturas.create_factura(
        11, 1, 1, "2026-09-01", "", "Juan", 5, [], 10000.0, 0.0, 10000.0, ambiente="homologacion")

    assert servicio_caja.vincular_cobros_a_factura(reserva_renumerada, factura_id) == 1
