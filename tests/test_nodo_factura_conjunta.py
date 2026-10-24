# ruff: noqa: F811  -- las fixtures importadas se piden por nombre en cada test
"""La factura conjunta (reserva más consumos) en un nodo: sin conexión va a la cola y al volver se emite una vez
(ADR-023). 
La factura conjunta numeraba con `get_next_numero_with_arca`, que sin ARCA cae a la numeración **local**, y un número
local choca con el de ARCA y con el del central (libracore ADR-074). En un nodo ya no: `POST
/api/reservas/{id}/facturar` deja el pedido en la cola de comprobantes del motor (`libracore.cola_arca`, ADR-079) y el
emisor `documento` de LibraClub lo emite con el ticket que presta el central.

Se fija acá lo que decide este producto: que **nunca se numere local** en un nodo, que se emita **una sola vez**, que
la factura **suba** al central y quede atada a la reserva y a sus cobros, y que **en el central** se facture como
antes.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from libraauth.models import Base as AuthBase
from libracore import arca_facturacion, arca_wsfe
from libracore.cola_arca import procesar_cola, reintentar
from libracore.nodo_offline import RechazoDelCentral
from libraedge.mapeo import anotar_mapeo

from app import offline
from app.models.reservas import Reserva
from app.servicios import factura_del_nodo
from app.servicios import facturacion as servicio_facturacion
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

ARCA = {"id": 1, "cuit": "20111111112", "ambiente": "homologacion", "punto_venta": 1}
TA = {"token": "t", "sign": "s", "servicio": "wsfe", "ambiente": "homologacion"}


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    yield cliente_logueado(armar_app(engine, monkeypatch, base_de_libracore))
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def arca(api, base_de_libracore):
    """La `arca_config` que el nodo espeja del central. El ticket lo presta el central (acá, `obtener_ta` falso)."""
    servicio_facturacion.guardar_config_arca("20111111112", 1, "/no/existe.key", "/no/existe.crt", "homologacion")


@pytest.fixture
def arca_que_responde(monkeypatch, arca):
    """ARCA y el central de mentira: el número, el ticket y el CAE salen de acá. Cuenta cada llamada."""
    llamadas = SimpleNamespace(numerar=0, cae=0, ticket=0, falla_el_cae=False, rechaza_el_central=False)

    async def numerar(punto_venta, tipo):
        if llamadas.rechaza_el_central:
            await obtener_ta(ARCA)  # el ticket que el central no presta: levanta `RechazoDelCentral`
        llamadas.numerar += 1
        return 7 + llamadas.numerar - 1, TA, ARCA

    async def obtener_ta(arca_, servicio="wsfe"):
        llamadas.ticket += 1
        if llamadas.rechaza_el_central:
            raise RechazoDelCentral("El central no tiene el certificado y la clave de ARCA cargados.")
        return TA

    async def solicitar_cae(factura, cuit, token, sign, ambiente):
        llamadas.cae += 1
        if llamadas.falla_el_cae:
            raise RuntimeError("ARCA rechazó el comprobante")
        return {"cae": "70000000000001", "cae_vto": "20261231"}

    original = offline.cola
    monkeypatch.setattr(
        offline, "cola", lambda: replace(original(), numerar_comprobante=numerar, obtener_ta=obtener_ta))
    monkeypatch.setattr(arca_wsfe, "solicitar_cae", solicitar_cae)
    return llamadas


@pytest.fixture
def sin_numeracion_local(monkeypatch):
    """🔴 La regla de ADR-074: en un nodo, `get_next_numero_with_arca` (que cae a la numeración local) no se llama."""
    async def prohibida(*args, **kwargs):
        raise AssertionError("un nodo no numera local: get_next_numero_with_arca no se puede llamar")

    monkeypatch.setattr(arca_facturacion, "get_next_numero_with_arca", prohibida)


@pytest.fixture
def mostrador(api, sucursal):
    """La caja de la sucursal, creada **antes** de prender el nodo: las cajas las manda el central."""
    return api.post("/api/cajas", json={"nombre": "Mostrador", "sucursal_id": sucursal.id}).json()


@pytest.fixture
def reserva(api, sucursal, cancha, cliente, tarifa_base):
    """Una reserva de 10.000 con un consumo de buffet de 2.400 (un total a facturar de 12.400)."""
    r = api.post(f"/api/buffet/productos?sucursal_id={sucursal.id}", json={
        "nombre": "Gaseosa", "precio": "1200.00", "costo": "700.00", "stock_minimo": "0"})
    item_id = r.json()["item_id"]
    api.post(f"/api/buffet/ajustes?sucursal_id={sucursal.id}", json={
        "item_id": item_id, "cantidad": "24", "motivo": "x"})
    reserva = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": cliente.id, "comienza_at": "2026-09-01T20:00:00-03:00",
        "duracion_min": 90}).json()
    api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": item_id, "cantidad": "2"}], "reserva_id": reserva["id"]})
    return reserva


def _cobrar(api, reserva, mostrador, monto="5000"):
    """Abre el turno y cobra la seña, en el nodo (el cobro y el turno suben: son del nodo)."""
    api.post("/api/caja/turnos", json={"monto_inicial": "0", "notas": "", "caja_id": mostrador["id"]})
    r = api.post(f"/api/reservas/{reserva['id']}/cobros", json={"monto": monto, "medio_pago": "efectivo"})
    assert r.status_code == 201, r.text


def _facturar(api, reserva):
    return api.post(f"/api/reservas/{reserva['id']}/facturar")


def _facturas():
    return filas("SELECT numero, cae, observaciones, total, ambiente, tipo FROM facturas ORDER BY id")


# ── Sin conexión: a la cola ─────────────────────────────────────────────────────────────────────────────────────────


def test_sin_conexion_la_factura_conjunta_va_a_la_cola_y_no_numera_local(
    api, reserva, nodo, arca_que_responde, sin_numeracion_local
):
    """🔴 Sin la cola, `facturar_reserva` caería a la numeración local: el número chocaría con el de ARCA y con el del
    central. Acá no se numera, no se llama a ARCA y no queda ninguna factura: queda el pedido, esperando."""
    r = _facturar(api, reserva)

    assert r.status_code == 202, r.text
    cuerpo = r.json()
    assert cuerpo["en_cola"] is True and cuerpo["estado"] == "esperando"
    assert "conexión" in cuerpo["mensaje"]
    assert _facturas() == []
    assert (arca_que_responde.numerar, arca_que_responde.cae) == (0, 0)
    assert filas("SELECT origen_tipo, origen_id, estado, fecha_ref FROM cola_arca") == [
        ("documento", str(reserva["id"]), "esperando", filas("SELECT fecha_ref FROM cola_arca")[0][0])]
    # La cola se ve desde la pantalla (`GET /api/nodo/cola`) y sube al central (`cola.pedido`).
    cola = api.get("/api/nodo/cola").json()
    assert (cola["es_nodo"], cola["en_linea"], cola["cuentas"]["esperando"]) == (True, False, 1)
    assert tipos_encolados()[-1] == "cola.pedido"


def test_al_volver_la_conexion_se_emite_una_sola_vez(
    api, reserva, mostrador, nodo, arca_que_responde, sin_numeracion_local
):
    _cobrar(api, reserva, mostrador)
    _facturar(api, reserva)

    nodo.en_linea(True)
    primera = asyncio.run(procesar_cola(offline.cola()))
    segunda = asyncio.run(procesar_cola(offline.cola()))

    assert len(primera["emitidos"]) == 1 and segunda["emitidos"] == []
    # Una sola factura, con el número y el CAE que dio ARCA y la marca de su reserva.
    assert _facturas() == [(7, "70000000000001", f"Reserva {reserva['id']}", 12400.0, "homologacion", 11)]
    assert (arca_que_responde.numerar, arca_que_responde.cae) == (1, 1)
    assert filas("SELECT estado FROM cola_arca") == [("emitido",)]
    # La plata que ya estaba cobrada quedó atada a la factura.
    assert filas("SELECT factura_id FROM caja_movimientos WHERE referencia LIKE 'reserva-%%'") == [
        (filas("SELECT id FROM facturas")[0][0],)]


def test_la_factura_lleva_la_cancha_y_el_buffet_y_el_total_de_los_dos(api, reserva, nodo, arca_que_responde):
    nodo.en_linea(True)
    assert _facturar(api, reserva).status_code == 201

    (factura,) = filas("SELECT items, total FROM facturas")
    descripciones = [linea["description"] for linea in json.loads(factura[0])]
    assert len(descripciones) == 2 and descripciones[1] == "Gaseosa"
    assert descripciones[0].startswith("Alquiler de Cancha 1")
    assert factura[1] == 12400.0


def test_con_conexion_sale_en_el_momento_y_contesta_como_el_central(
    api, reserva, mostrador, nodo, arca_que_responde
):
    nodo.en_linea(True)
    marca = filas("SELECT xmin::text FROM reservas WHERE id = %s", (reserva["id"],))
    _cobrar(api, reserva, mostrador)

    r = _facturar(api, reserva)

    assert r.status_code == 201, r.text
    assert (r.json()["numero"], r.json()["cae"], r.json()["total"]) == (7, "70000000000001", 12400.0)
    assert len(_facturas()) == 1
    # El pedido salió: la reserva ya figura facturada en el nodo, y no se emite otra.
    assert api.get(f"/api/reservas/{reserva['id']}/factura").json()["numero"] == 7
    assert _facturar(api, reserva).status_code == 409
    assert len(_facturas()) == 1
    # 🔴 La guarda del espejo: en un nodo, `reservas` es del central y un UPDATE sobre una reserva con id positivo
    # muere con LE001. Ni el cobro ni la factura escriben la fila (el vínculo con la factura del nodo es su marca, no
    # `factura_id`).
    assert filas("SELECT xmin::text FROM reservas WHERE id = %s", (reserva["id"],)) == marca
    assert filas("SELECT factura_id FROM reservas WHERE id = %s", (reserva["id"],)) == [(None,)]


def test_si_el_central_no_presta_el_ticket_el_pedido_espera_con_el_motivo(api, reserva, nodo, arca_que_responde):
    """Un rechazo del central (nodo revocado, sin certificado) no es un corte: no se arregla solo, y la pantalla lo
    dice."""
    nodo.en_linea(True)
    arca_que_responde.rechaza_el_central = True

    r = _facturar(api, reserva)

    assert r.status_code == 202
    assert "certificado" in r.json()["mensaje"] and r.json()["estado"] == "esperando"
    assert _facturas() == []


def test_si_arca_no_da_el_cae_la_factura_queda_a_revisar_y_el_reintento_no_la_duplica(
    api, reserva, nodo, arca_que_responde
):
    nodo.en_linea(True)
    arca_que_responde.falla_el_cae = True

    r = _facturar(api, reserva)

    assert r.status_code == 202 and r.json()["estado"] == "a_revisar"
    (sin_cae,) = _facturas()
    assert sin_cae[0] == 7 and not sin_cae[1]
    pedido_id = r.json()["pedido_id"]

    arca_que_responde.falla_el_cae = False
    reintentar(offline.cola(), pedido_id)
    asyncio.run(procesar_cola(offline.cola()))

    # La misma factura (no otro número) con el CAE que ahora sí dio ARCA.
    assert [(f[0], f[1]) for f in _facturas()] == [(7, "70000000000001")]
    assert arca_que_responde.numerar == 1


def test_el_emisor_no_emite_otra_si_la_factura_de_la_reserva_ya_esta(api, reserva, nodo, arca_que_responde):
    """Idempotente (ADR-079): si el proceso murió entre «ARCA emitió» y «el nodo anotó», la factura ya está creada y el
    emisor la encuentra por su marca en vez de numerar otra."""
    nodo.en_linea(True)
    _facturar(api, reserva)
    ctx = SimpleNamespace(numerar=None, ticket=None)  # si lo tocara, fallaría

    resultado = asyncio.run(factura_del_nodo.emitir_documento({"origen_id": str(reserva["id"])}, ctx))

    assert resultado["cae"] == "70000000000001"
    assert len(_facturas()) == 1


def test_un_pedido_hecho_dos_veces_es_un_solo_pedido(api, reserva, nodo, arca_que_responde):
    _facturar(api, reserva)
    _facturar(api, reserva)

    assert filas("SELECT count(*) FROM cola_arca") == [(1,)]


# ── Arrancar la cola ────────────────────────────────────────────────────────────────────────────────────────────────


def test_el_hilo_de_la_cola_solo_arranca_en_un_nodo(api, nodo_apagado):
    assert offline.arrancar_cola() is None
    nodo_apagado.prender()
    parar = offline.arrancar_cola()
    try:
        assert parar is not None
    finally:
        parar.set()


# ── En el central: lo que sube ──────────────────────────────────────────────────────────────────────────────────────


def _emitir_en_el_nodo(api, reserva, mostrador, nodo):
    _cobrar(api, reserva, mostrador)
    nodo.en_linea(True)
    assert _facturar(api, reserva).status_code == 201
    return operaciones()


def test_el_central_recibe_la_factura_y_la_ata_a_la_reserva_y_a_sus_cobros(
    api, reserva, mostrador, nodo, arca_que_responde
):
    capturadas = _emitir_en_el_nodo(api, reserva, mostrador, nodo)
    assert [op.operation_type for op in capturadas][-2:] == ["cola.pedido", "club.factura_conjunta"]
    vaciar_lo_del_nodo()
    nodo.apagar()

    resultados = aplicar_en_el_central(capturadas)

    assert set(resultados) == {"accepted"}
    # La misma factura, con el mismo número y CAE: el nodo la emitió, el central la tiene.
    assert _facturas() == [(7, "70000000000001", f"Reserva {reserva['id']}", 12400.0, "homologacion", 11)]
    (factura_id,) = filas("SELECT id FROM facturas")[0]
    assert filas("SELECT factura_id FROM reservas WHERE id = %s", (reserva["id"],)) == [(factura_id,)]
    assert filas("SELECT factura_id FROM caja_movimientos WHERE referencia LIKE 'reserva-%%'") == [(factura_id,)]
    # Y la copia de consulta de la cola: la web ve que salió.
    assert filas("SELECT origen_instancia, origen_tipo, estado FROM cola_arca") == [(NODO, "documento", "emitido")]


def test_aplicar_dos_veces_la_factura_del_nodo_no_la_duplica(api, reserva, mostrador, nodo, arca_que_responde):
    capturadas = _emitir_en_el_nodo(api, reserva, mostrador, nodo)
    vaciar_lo_del_nodo()
    nodo.apagar()
    aplicar_en_el_central(capturadas)
    (op,) = [op for op in capturadas if op.operation_type == offline.TIPO_FACTURA_CONJUNTA]

    from libracore.db import core as libracore_core

    with libracore_core.get_connection() as conn:
        factura_del_nodo.aplicar_factura_conjunta(conn, op)
        conn.commit()

    assert len(_facturas()) == 1


def test_una_reserva_que_ya_tiene_otra_factura_en_el_central_va_a_revision(
    api, reserva, mostrador, nodo, arca_que_responde, sesion
):
    """Dos comprobantes por la misma reserva no se escriben en silencio: revisión manual."""
    capturadas = _emitir_en_el_nodo(api, reserva, mostrador, nodo)
    vaciar_lo_del_nodo()
    nodo.apagar()
    from libracore.db import facturas as db_facturas

    otra = db_facturas.create_factura(
        11, 1, 99, "2026-09-01", "", "Otro", 5, [], 1.0, 0.0, 1.0, ambiente="homologacion")
    sesion.execute(Reserva.__table__.update().where(Reserva.id == reserva["id"]).values(factura_id=otra))
    sesion.commit()

    resultados = aplicar_en_el_central(capturadas)

    assert resultados[-1].startswith("rejected") and "dos comprobantes" in resultados[-1]


def test_la_factura_de_una_reserva_provisoria_se_ata_a_la_definitiva(
    api, sesion, reserva, nodo, arca_que_responde
):
    """La reserva se dio en el nodo con el id `-1`; el central la conoce como `N`. La factura sube con `-1` y se ata
    a `N` (mapeo de `reserva.creada`), y su marca dice `Reserva N`, no `Reserva -1`."""
    sesion.execute(Reserva.__table__.update().where(Reserva.id == reserva["id"]).values(id=-1))
    sesion.commit()
    nodo.en_linea(True)
    assert api.post("/api/reservas/-1/facturar").status_code == 201
    capturadas = operaciones()
    assert filas("SELECT observaciones FROM facturas") == [("Reserva -1",)]
    vaciar_lo_del_nodo()
    nodo.apagar()
    sesion.execute(Reserva.__table__.update().where(Reserva.id == -1).values(id=reserva["id"]))
    sesion.commit()
    from libracore.db import core as libracore_core

    with libracore_core.get_connection() as conn:
        anotar_mapeo(conn, NODO, "reservas", -1, reserva["id"])
        conn.commit()

    assert set(aplicar_en_el_central(capturadas)) == {"accepted"}

    assert filas("SELECT observaciones FROM facturas") == [(f"Reserva {reserva['id']}",)]
    assert filas("SELECT factura_id IS NOT NULL FROM reservas WHERE id = %s", (reserva["id"],)) == [(True,)]


# ── En el central: se factura como antes ────────────────────────────────────────────────────────────────────────────


def test_en_el_central_la_factura_sale_como_antes(api, reserva, nodo_apagado, arca_que_responde):
    """🔑 «Fuera de un nodo nada cambia»: `facturar_reserva` numera como siempre (acá, el contador de la instancia:
    sin ARCA configurada para producción, `get_next_numero_with_arca` del motor), contesta 201 y no toca la cola."""
    r = _facturar(api, reserva)

    assert r.status_code == 201, r.text
    assert r.json()["total"] == 12400.0
    assert filas("SELECT count(*) FROM cola_arca") == [(0,)]
    assert operaciones() == []
    assert arca_que_responde.numerar == 0, "el central no numera por la cola"
    cola = api.get("/api/nodo/cola").json()
    assert (cola["es_nodo"], cola["cuentas"]["esperando"]) == (False, 0)


# ── Con las reservas del PR 12: una reserva que se da en el nodo, de punta a punta ──────────────────────────────────


def test_una_reserva_dada_en_el_nodo_se_consume_se_cobra_y_se_factura_en_el_central(
    api, sesion, sucursal, cancha, cliente, tarifa_base, mostrador, nodo_apagado, arca_que_responde
):
    """🔑 La prueba de que las piezas de los dos PR encajan. En el nodo: se da la reserva (id provisorio), se le carga
    un consumo del buffet, se cobra la seña y se factura. Al volver, el central aplica **en el orden en que ocurrió**:
    la reserva (con su id definitivo y el mapeo), el consumo colgado de ella, el cobro con la referencia traducida y la
    factura atada a la reserva y a su cobro."""
    r = api.post(f"/api/buffet/productos?sucursal_id={sucursal.id}", json={
        "nombre": "Gaseosa", "precio": "1200.00", "costo": "700.00", "stock_minimo": "0"})
    item_id = r.json()["item_id"]
    api.post(f"/api/buffet/ajustes?sucursal_id={sucursal.id}", json={
        "item_id": item_id, "cantidad": "24", "motivo": "x"})
    nodo_apagado.prender()

    creada = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": cliente.id, "comienza_at": "2026-09-01T20:00:00-03:00",
        "duracion_min": 90})
    assert creada.status_code == 201, creada.text
    en_el_nodo = creada.json()["id"]
    assert en_el_nodo < 0, "la reserva del nodo nace con un id provisorio"
    api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": item_id, "cantidad": "2"}], "reserva_id": en_el_nodo})
    _cobrar(api, {"id": en_el_nodo}, mostrador)
    nodo_apagado.en_linea(True)
    assert api.post(f"/api/reservas/{en_el_nodo}/facturar").status_code == 201
    capturadas = operaciones()
    assert [op.operation_type for op in capturadas] == [
        "reserva.creada", "venta.registrada", "turno.abierto", "caja.movimiento",
        "cola.pedido", "cola.pedido", "club.factura_conjunta",
    ]

    # El central: otra base que todavía no recibió nada del nodo (ni su reserva, ni su plata, ni su factura).
    vaciar_lo_del_nodo()
    sesion.execute(Reserva.__table__.delete().where(Reserva.id == en_el_nodo))
    sesion.commit()
    nodo_apagado.apagar()

    assert set(aplicar_en_el_central(capturadas)) == {"accepted"}

    ((reserva_id, factura_id),) = filas("SELECT id, factura_id FROM reservas")
    assert reserva_id > 0 and factura_id is not None
    assert filas("SELECT source_type, source_id FROM sales") == [("reserva", reserva_id)]
    assert filas("SELECT referencia, factura_id FROM caja_movimientos")[0][1] == factura_id
    assert filas("SELECT referencia FROM caja_movimientos")[0][0].startswith(f"reserva-{reserva_id}-")
    assert filas("SELECT observaciones, total FROM facturas") == [(f"Reserva {reserva_id}", 12400.0)]
    from app.servicios import caja as servicio_caja

    assert servicio_caja.total_cobrado(reserva_id) == 5000
