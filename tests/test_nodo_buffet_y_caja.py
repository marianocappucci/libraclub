# ruff: noqa: F811  -- las fixtures importadas se piden por nombre en cada test
"""El buffet, la caja y el pago de una reserva en un nodo sin conexión, y su vuelta en el central (ADR-023).

Decisión del humano (2026-10-22): sin internet, en el club se vende en el buffet, se opera la caja, se cobran las
canchas, se cargan consumos y se dan reservas. Lo que se fija acá es lo que decide este producto; el motor tiene sus
propios tests:

- **en el nodo** cada hecho se **encola** en el outbox, en el orden en que ocurrió (la venta del buffet, el turno, el
  cobro del mostrador, el cobro de una reserva con id provisorio, la reposición de stock);
- **en el central** el aplicador lo **materializa con su vínculo**: el consumo colgado de la reserva (aunque en el
  nodo la reserva tuviera un id provisorio) y el cobro con la referencia traducida, de modo que el pendiente da lo
  mismo en las dos puntas;
- **fuera de un nodo no cambia nada**: ni una operación en el outbox.

Los tests de la fase del nodo ponen `LIBRAEDGE_NODE_ID`; los del central, no (`tests/nodo_apoyo.py`).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from libraauth.models import Base as AuthBase
from libracore.db import core as libracore_core
from libraedge.mapeo import anotar_mapeo

from app.models.enums import EstadoReserva, OrigenReserva
from app.models.reservas import Reserva
from app.servicios import caja as servicio_caja
from app.tiempo import TZ
from tests.nodo_apoyo import (
    NODO,
    aplicar_en_el_central,
    armar_app,
    cliente_logueado,
    filas,
    nodo,  # noqa: F401  (fixture)
    nodo_apagado,  # noqa: F401  (fixture)
    operaciones,
    tipos_encolados,
    vaciar_lo_del_nodo,
)


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    yield cliente_logueado(armar_app(engine, monkeypatch, base_de_libracore))
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def gaseosa(api, sucursal):
    """El producto, cargado **antes** de prender el nodo: el catálogo lo manda el central."""
    r = api.post(f"/api/buffet/productos?sucursal_id={sucursal.id}", json={
        "nombre": "Gaseosa 500ml", "precio": "1200.00", "costo": "700.00", "stock_minimo": "6"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def mostrador(api, sucursal):
    """La caja de la sucursal, creada **antes** de prender el nodo: las cajas las manda el central."""
    r = api.post("/api/cajas", json={"nombre": "Mostrador", "sucursal_id": sucursal.id})
    assert r.status_code == 201, r.text
    return r.json()


def _reponer(api, sucursal, item_id, cantidad):
    r = api.post(f"/api/buffet/ajustes?sucursal_id={sucursal.id}", json={
        "item_id": item_id, "cantidad": str(cantidad), "motivo": "Entrega del proveedor"})
    assert r.status_code == 200, r.text


def _abrir_turno(api, mostrador):
    r = api.post("/api/caja/turnos", json={"monto_inicial": "0", "notas": "", "caja_id": mostrador["id"]})
    assert r.status_code == 201, r.text
    return r.json()


def _consumir(api, sucursal, item_id, cantidad, reserva_id=None, medio="efectivo"):
    cuerpo = {"lineas": [{"item_id": item_id, "cantidad": str(cantidad)}], "reserva_id": reserva_id}
    if reserva_id is None:
        cuerpo["medio_pago"] = medio
    r = api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


def _cobrar_turno(api, reserva_id, monto="5000", medio="efectivo"):
    r = api.post(f"/api/reservas/{reserva_id}/cobros", json={"monto": monto, "medio_pago": medio})
    assert r.status_code == 201, r.text
    return r.json()


def _reserva_del_nodo(sesion, cancha, cliente, id_provisorio=-1) -> Reserva:
    """Una reserva como la deja el nodo sin conexión: id provisorio negativo (PR 12 la crea; acá se escribe a mano)."""
    reserva = Reserva(
        id=id_provisorio, cancha_id=cancha.id, cliente_id=cliente.id, estado=EstadoReserva.CONFIRMADA,
        origen=OrigenReserva.MOSTRADOR, comienza_at=datetime(2026, 9, 1, 20, 0, tzinfo=TZ),
        termina_at=datetime(2026, 9, 1, 21, 30, tzinfo=TZ), precio=Decimal("10000.00"), sena=Decimal("5000.00"),
    )
    sesion.add(reserva)
    sesion.commit()
    return reserva


# ── En el nodo: se encola
# ────────────────────────────────────────────────────────────────────────────────────────────


def test_el_nodo_encola_la_venta_del_buffet_su_caja_y_el_stock(api, sucursal, gaseosa, mostrador, nodo_apagado):
    """🔴 Sin `con_outbox` en los ganchos del consumo, sin los ganchos de caja y sin `offline_stock.configurar`, la
    venta quedaría sólo en la PC del club: el central no sabría ni de la plata ni de las gaseosas."""
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    nodo_apagado.prender()

    _reponer(api, sucursal, gaseosa["item_id"], 6)
    _abrir_turno(api, mostrador)
    venta = _consumir(api, sucursal, gaseosa["item_id"], 2)

    # En el orden en que ocurrió: una sola secuencia por nodo.
    assert tipos_encolados() == ["stock.movimiento", "turno.abierto", "venta.registrada", "caja.movimiento"]
    reposicion, turno, registrada, cobro = (op.payload for op in operaciones())
    assert float(reposicion["cantidad"]) == 6.0
    assert (registrada["numero"], registrada["estado"], float(registrada["total"])) == (
        "S02-BUF-000001", "cobrada", 2400.0)
    assert (registrada["source_type"], registrada["source_id"]) == ("mostrador", None)
    assert [(float(m["cantidad"]), m["producto_id"]) for m in registrada["stock"]] == [(-2.0, gaseosa["item_id"])]
    assert (cobro["tipo"], cobro["monto"], cobro["referencia"], cobro["medio_pago"]) == (
        "ingreso", 2400.0, f"buffet-{venta['id']}", "efectivo")
    assert cobro["turno_id"] == turno["turno_id"]
    assert [op.node_id for op in operaciones()] == [NODO] * 4


def test_el_consumo_de_una_reserva_sube_con_el_vinculo_y_sin_caja(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa, nodo_apagado
):
    """El consumo cargado a la reserva se cobra con el turno, no acá: sube la venta y ninguna plata."""
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    reserva = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": cliente.id, "comienza_at": "2026-09-01T20:00:00-03:00",
        "duracion_min": 90}).json()
    nodo_apagado.prender()

    _consumir(api, sucursal, gaseosa["item_id"], 3, reserva_id=reserva["id"])

    assert tipos_encolados() == ["venta.registrada"]
    (registrada,) = (op.payload for op in operaciones())
    assert (registrada["source_type"], registrada["source_id"]) == ("reserva", reserva["id"])
    assert registrada["numero"] == "S02-BUF-000001"


def test_el_nodo_encola_el_pago_de_una_reserva_con_su_vinculo(
    api, sesion, sucursal, cancha, cliente, mostrador, nodo_apagado
):
    """El pago de una reserva sube como movimiento de caja y el vínculo con la reserva es su referencia.

    Con una reserva que se dio en el nodo (id provisorio `-1`) la referencia lleva ese id: `reserva--1-<azar>`. El
    pendiente tiene que verla (`_id_de_referencia` entiende el signo): sin eso el mostrador cobra y la reserva sigue
    figurando impaga."""
    _reserva_del_nodo(sesion, cancha, cliente)
    nodo_apagado.prender()
    _abrir_turno(api, mostrador)

    _cobrar_turno(api, -1, "5000")

    assert tipos_encolados() == ["turno.abierto", "caja.movimiento"]
    cobro = operaciones()[1].payload
    assert cobro["referencia"].startswith("reserva--1-") and cobro["monto"] == 5000.0
    estado = api.get("/api/reservas/-1/cobros").json()
    assert estado["cobrado"] == 5000.0 and estado["pendiente"] == 5000.0


def test_el_cobro_de_una_reserva_del_central_sube_con_su_id(api, sucursal, cancha, cliente, tarifa_base, mostrador,
                                                           nodo_apagado):
    reserva = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": cliente.id, "comienza_at": "2026-09-01T20:00:00-03:00",
        "duracion_min": 90}).json()
    nodo_apagado.prender()
    _abrir_turno(api, mostrador)

    _cobrar_turno(api, reserva["id"], "5000")

    assert operaciones()[-1].payload["referencia"].startswith(f"reserva-{reserva['id']}-")


def test_la_anulacion_de_un_cobro_y_el_cierre_del_turno_suben(api, sucursal, gaseosa, mostrador, nodo_apagado):
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    nodo_apagado.prender()
    turno = _abrir_turno(api, mostrador)
    _consumir(api, sucursal, gaseosa["item_id"], 1)
    movimiento = api.get("/api/caja/turnos/actual").json()["resumen"]["movimientos"][0]["id"]

    assert api.delete(f"/api/caja/movimientos/{movimiento}").status_code == 200
    r = api.post(f"/api/caja/turnos/{turno['id']}/cerrar", json={"monto_declarado": "0", "notas": ""})
    assert r.status_code == 200, r.text

    assert tipos_encolados() == [
        "turno.abierto", "venta.registrada", "caja.movimiento", "caja.movimiento_anulado", "turno.cerrado"]
    assert operaciones()[-1].payload["arqueo"] == "caja"


def test_fuera_de_un_nodo_no_se_encola_nada(api, sucursal, cancha, cliente, tarifa_base, gaseosa, mostrador,
                                           nodo_apagado):
    """🔑 «Fuera de un nodo nada cambia»: con las tablas de LibraEdge en la base pero sin `LIBRAEDGE_NODE_ID`, el
    buffet, la caja y el cobro de una reserva escriben lo de siempre y el outbox queda vacío."""
    reserva = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": cliente.id, "comienza_at": "2026-09-01T20:00:00-03:00",
        "duracion_min": 90}).json()
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    _abrir_turno(api, mostrador)
    _consumir(api, sucursal, gaseosa["item_id"], 1)
    _consumir(api, sucursal, gaseosa["item_id"], 1, reserva_id=reserva["id"])
    _cobrar_turno(api, reserva["id"])

    assert operaciones() == []
    assert filas("SELECT count(*) FROM sales") == [(2,)]
    assert filas("SELECT count(*) FROM caja_movimientos") == [(2,)]


# ── En el central: se materializa con el vínculo ────────────────────────────────────────────────────────────────────


def test_el_central_materializa_la_venta_la_caja_y_el_pago_con_el_vinculo(
    api, sesion, sucursal, cancha, cliente, tarifa_base, gaseosa, mostrador, nodo_apagado
):
    """La ronda completa: se opera en el nodo, se vacía lo que generó (como si el central fuera otra base que todavía no
    lo recibió) y se aplica por el receptor real. Lo que tiene que quedar en el central es lo mismo que vio el nodo."""
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    reserva = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": cliente.id, "comienza_at": "2026-09-01T20:00:00-03:00",
        "duracion_min": 90}).json()
    nodo_apagado.prender()

    _abrir_turno(api, mostrador)
    _consumir(api, sucursal, gaseosa["item_id"], 2, reserva_id=reserva["id"])
    mostrador_ = _consumir(api, sucursal, gaseosa["item_id"], 1)
    _cobrar_turno(api, reserva["id"], "5000")
    pendiente_en_el_nodo = api.get(f"/api/reservas/{reserva['id']}/cobros").json()
    capturadas = operaciones()
    assert len(capturadas) == 5

    vaciar_lo_del_nodo()
    nodo_apagado.apagar()
    assert aplicar_en_el_central(capturadas) == ["accepted"] * 5

    # El consumo cuelga de la reserva y la venta de mostrador es de mostrador.
    assert filas("SELECT number, source_type, source_id, total FROM sales ORDER BY id") == [
        ("S02-BUF-000001", "reserva", reserva["id"], Decimal("2400.0")),
        ("S02-BUF-000002", "mostrador", None, Decimal("1200.0")),
    ]
    # El stock salió del depósito del buffet de esa sucursal (el mismo que en el nodo).
    (deposito,) = filas("SELECT id FROM locations WHERE name = %s", (f"Buffet #{sucursal.id}",))
    assert filas("SELECT location_id, quantity_delta FROM stock_movements "
                 "WHERE movement_type = 'sale' ORDER BY id") == [
        (deposito[0], Decimal("-2")), (deposito[0], Decimal("-1"))]
    # La caja: un turno del nodo (con su origen) y los dos cobros, cada uno con su referencia.
    assert filas("SELECT origen, estado FROM turnos_caja") == [(NODO, "abierto")]
    referencias = [r for (r,) in filas("SELECT referencia FROM caja_movimientos ORDER BY id")]
    assert referencias[0] == f"buffet-{mostrador_['id']}" or referencias[1] == f"buffet-{mostrador_['id']}"
    assert sum(r.startswith(f"reserva-{reserva['id']}-") for r in referencias) == 1
    # Y el pendiente de la reserva da lo mismo en las dos puntas.
    assert servicio_caja.total_cobrado(reserva["id"]) == Decimal(str(pendiente_en_el_nodo["cobrado"]))


def test_la_reserva_provisoria_del_nodo_se_traduce_al_id_del_central(
    api, sesion, sucursal, cancha, cliente, gaseosa, mostrador, nodo_apagado
):
    """🔴 Lo que une este PR con el 12: una reserva que se dio sin conexión tiene el id `-1` en el nodo y otro (`N`)
    en el central. El consumo (`source_id`) lo traduce `registrar_en(tablas_de_origen={"reserva": "reservas"})` y el
    cobro (el texto de la referencia) lo traduce `aplicar_movimiento_de_club`. Con el mapeo que anota el aplicador de
    `reserva.creada`.

    Sin la traducción de la venta, el consumo quedaría colgado de la reserva `-1`, que en el central no existe; sin la
    del
    cobro, `cobros_de_reserva(N)` no lo encontraría y la reserva seguiría figurando impaga."""
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    _reserva_del_nodo(sesion, cancha, cliente, -1)
    nodo_apagado.prender()
    _abrir_turno(api, mostrador)
    _consumir(api, sucursal, gaseosa["item_id"], 2, reserva_id=-1)
    _cobrar_turno(api, -1, "5000")
    capturadas = operaciones()

    # El central: la reserva con su id definitivo y el mapeo que dejó `reserva.creada` al aplicarse.
    vaciar_lo_del_nodo()
    nodo_apagado.apagar()
    sesion.execute(Reserva.__table__.delete().where(Reserva.id == -1))
    definitiva = _reserva_del_nodo(sesion, cancha, cliente, 500)
    with libracore_core.get_connection() as conn:
        anotar_mapeo(conn, NODO, "reservas", -1, definitiva.id)
        conn.commit()

    assert aplicar_en_el_central(capturadas) == ["accepted"] * 3

    assert filas("SELECT source_type, source_id FROM sales") == [("reserva", 500)]
    assert [r for (r,) in filas("SELECT referencia FROM caja_movimientos")][0].startswith("reserva-500-")
    assert servicio_caja.total_cobrado(500) == Decimal("5000")


def test_sin_el_mapeo_la_venta_y_el_cobro_de_una_reserva_provisoria_van_a_revision(
    api, sesion, sucursal, cancha, cliente, gaseosa, mostrador, nodo_apagado
):
    """Si el `reserva.creada` todavía no se aplicó, el consumo y el cobro no se atan a otra cosa: revisión manual (se
    reintentan detrás de la reserva)."""
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    _reserva_del_nodo(sesion, cancha, cliente, -1)
    nodo_apagado.prender()
    _abrir_turno(api, mostrador)
    _consumir(api, sucursal, gaseosa["item_id"], 1, reserva_id=-1)
    _cobrar_turno(api, -1, "5000")
    capturadas = operaciones()
    vaciar_lo_del_nodo()
    nodo_apagado.apagar()

    resultados = aplicar_en_el_central(capturadas)

    assert [r.split(":")[0] for r in resultados] == ["accepted", "rejected", "rejected"]
    assert filas("SELECT count(*) FROM sales") == [(0,)]


def test_el_cobro_posterior_a_la_factura_queda_atado_a_ella(
    api, sesion, sucursal, cancha, cliente, mostrador, nodo_apagado
):
    """Si la factura de la reserva ya está en el central cuando llega el cobro, el cobro se ata a ella (en el central
    `cobrar_turno` lo hace con `reserva.factura_id`; el nodo no conoce ese id)."""
    reserva = _reserva_del_nodo(sesion, cancha, cliente, 500)
    nodo_apagado.prender()
    _abrir_turno(api, mostrador)
    _cobrar_turno(api, 500, "5000")
    capturadas = operaciones()
    vaciar_lo_del_nodo()
    nodo_apagado.apagar()
    from libracore.db import facturas as db_facturas

    factura_id = db_facturas.create_factura(
        11, 1, 1, "2026-09-01", "", "Juan", 5, [], 10000.0, 0.0, 10000.0, ambiente="homologacion")
    sesion.execute(Reserva.__table__.update().where(Reserva.id == reserva.id).values(factura_id=factura_id))
    sesion.commit()

    assert aplicar_en_el_central(capturadas) == ["accepted"] * 2

    assert filas("SELECT factura_id FROM caja_movimientos") == [(factura_id,)]


# ── El id definitivo de una reserva que se dio en el nodo ───────────────────────────────────────────────────────────


def test_el_pendiente_sigue_viendo_los_cobros_cuando_la_reserva_recibe_su_id_definitivo(
    api, sesion, sucursal, cancha, cliente, mostrador, nodo_apagado
):
    """🔴 La referencia de un cobro es un texto (`reserva--1-ab12`) y LibraEdge no puede reescribirlo cuando reapunta la
    reserva `-1` a la `500`. Sin leer también el id provisorio (por `libraedge_mapeo`), el mostrador cobra la seña y
    en cuanto
    baja el id definitivo la reserva vuelve a figurar impaga."""
    _reserva_del_nodo(sesion, cancha, cliente, -1)
    nodo_apagado.prender()
    _abrir_turno(api, mostrador)
    _cobrar_turno(api, -1, "5000")

    # El espejo trajo la reserva con su id definitivo y el reapuntado borró la provisoria.
    sesion.execute(Reserva.__table__.update().where(Reserva.id == -1).values(id=500))
    sesion.commit()
    with libracore_core.get_connection() as conn:
        anotar_mapeo(conn, NODO, "reservas", -1, 500)
        conn.commit()

    estado = api.get("/api/reservas/500/cobros").json()
    assert (estado["cobrado"], estado["pendiente"]) == (5000.0, 5000.0)
    assert servicio_caja.cobrado_de_reservas([500]) == {500: Decimal("5000")}
    assert [c["monto"] for c in servicio_caja.cobros_de_reserva(500)] == [5000.0]


def test_el_id_de_una_referencia_entiende_el_provisorio():
    assert servicio_caja._id_de_referencia("reserva-12-ab3f") == 12
    assert servicio_caja._id_de_referencia("reserva--3-ab3f") == -3
    assert servicio_caja._id_de_referencia("lc-7-ab3f") == 7
    assert servicio_caja._id_de_referencia("buffet-9") is None
    assert servicio_caja._id_de_referencia("reserva-abc-1") is None


# ── El despachador del central ──────────────────────────────────────────────────────────────────────────────────────


def test_el_central_sabe_aplicar_todo_lo_que_un_nodo_de_libraclub_sube():
    """Lo que no tiene aplicador no se marca aplicado: va a revisión manual. Los trece tipos del motor ERP (venta, caja,
    clientes y stock), la cola de ARCA y la factura conjunta tienen que estar."""
    from app.routers.sincronizacion_offline import despachador

    esperados = {
        "venta.registrada", "venta.pago_acreditado", "venta.anulada", "venta.devolucion", "venta.facturada",
        "turno.abierto", "turno.cerrado", "caja.movimiento", "caja.movimiento_anulado", "dia.cerrado",
        "cliente.alta", "stock.movimiento", "compra.recibida", "cola.pedido", "club.factura_conjunta",
    }
    assert esperados <= set(despachador.tipos())
    assert all(1 in despachador.versiones(tipo) for tipo in esperados)


def test_las_operaciones_de_las_reservas_estan_registradas_en_el_central():
    """El punto de registro del PR 12 (`registrar_reservas` en `app/routers/sincronizacion_offline.py`): sin él, una
    `reserva.creada` iría a revisión manual y la reserva dada sin conexión nunca llegaría al central."""
    from app.routers.sincronizacion_offline import despachador

    assert {"reserva.creada", "reserva.estado"} <= set(despachador.tipos())
