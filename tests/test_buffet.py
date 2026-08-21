"""El buffet: catálogo, stock, consumo cargado a la cancha, y UNA sola factura.

El motor —LibraCommerce— tiene sus propios tests. Lo que se fija acá es lo que
decide este producto:

- que el consumo quede **colgado de la reserva** y no suelto;
- que **descuente stock** de la sucursal correcta;
- que el comprobante salga con la cancha y el buffet como **líneas separadas**,
  y que el **total incluya las dos cosas** — que es el gate de F4;
- que la venta de mostrador entre a la caja del turno, y la cargada a la
  reserva **no** (o se cobraría dos veces).
"""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"


def _url_core() -> str:
    url = os.environ["DATABASE_URL"]
    base, _, nombre = url.rpartition("/")
    return f"{base}/{nombre}_core".replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture
def base_de_libracore():
    url = _url_core()
    servidor, _, nombre = url.rpartition("/")
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{nombre}"')
    yield url
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')


def _config(url_core: str | None) -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos", libracore_database_url=url_core,
    )


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(crear_app(_config(base_de_libracore)), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def gaseosa(api, sucursal):
    r = api.post(f"/api/buffet/productos?sucursal_id={sucursal.id}", json={
        "nombre": "Gaseosa 500ml", "precio": "1200.00", "costo": "700.00",
        "stock_minimo": "6"})
    assert r.status_code == 201, r.text
    return r.json()


def _reponer(api, sucursal, item_id, cantidad, motivo="Entrega del proveedor"):
    r = api.post(f"/api/buffet/ajustes?sucursal_id={sucursal.id}", json={
        "item_id": item_id, "cantidad": str(cantidad), "motivo": motivo})
    assert r.status_code == 200, r.text
    return r.json()


def _reserva(api, cancha, cliente, **extra):
    datos = {"cancha_id": cancha.id, "cliente_id": cliente.id,
             "comienza_at": "2026-09-01T20:00:00-03:00", "duracion_min": 90}
    datos.update(extra)
    r = api.post("/api/reservas", json=datos)
    assert r.status_code == 201, r.text
    return r.json()


# ── Catálogo y stock ─────────────────────────────────────────────────────


def test_un_producto_nuevo_arranca_sin_stock(gaseosa):
    assert gaseosa["stock"] == 0.0
    assert gaseosa["precio"] == 1200.0


def test_reponer_suma_y_la_rotura_resta(api, sucursal, gaseosa):
    assert _reponer(api, sucursal, gaseosa["item_id"], 24)["stock"] == 24.0
    rota = _reponer(api, sucursal, gaseosa["item_id"], -1, "Se rompió una botella")
    assert rota["stock"] == 23.0


def test_bajo_minimo_avisa_AL_llegar_al_minimo_y_no_despues(api, sucursal, gaseosa):
    """🔑 `<=` y no `<`: estar justo en el mínimo ya es el momento de reponer.

    Con `<` el aviso llega cuando ya falta, que es tarde: el proveedor tarda.
    """
    assert _reponer(api, sucursal, gaseosa["item_id"], 7)["bajo_minimo"] is False
    assert _reponer(api, sucursal, gaseosa["item_id"], -1)["bajo_minimo"] is True, "6 == mínimo"


def test_un_ajuste_de_cero_no_se_acepta(api, sucursal, gaseosa):
    r = api.post(f"/api/buffet/ajustes?sucursal_id={sucursal.id}", json={
        "item_id": gaseosa["item_id"], "cantidad": "0", "motivo": "nada"})
    assert r.status_code == 422, r.text


def test_el_stock_es_POR_SUCURSAL(api, sesion, sucursal, gaseosa):
    """🔴 Las gaseosas de Centro no las puede vender Norte.

    Con una ubicación única y global, el complejo de dos sedes vería stock donde
    no lo tiene y no lo vería donde sí.
    """
    from app.models.maestros import Sucursal

    otra = Sucursal(nombre="Complejo Norte")
    sesion.add(otra)
    sesion.commit()

    _reponer(api, sucursal, gaseosa["item_id"], 24)

    en_la_otra = api.get(f"/api/buffet/productos?sucursal_id={otra.id}").json()
    fila = next(f for f in en_la_otra if f["item_id"] == gaseosa["item_id"])
    assert fila["stock"] == 0.0, "el stock de una sucursal no aparece en la otra"


# ── Consumo cargado a la reserva ─────────────────────────────────────────


def test_el_consumo_de_una_reserva_descuenta_stock_y_queda_colgado(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa
):
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    reserva = _reserva(api, cancha, cliente)

    r = api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": gaseosa["item_id"], "cantidad": "2"}],
        "reserva_id": reserva["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["total"] == 2400.0

    fila = next(f for f in api.get(f"/api/buffet/productos?sucursal_id={sucursal.id}").json()
                if f["item_id"] == gaseosa["item_id"])
    assert fila["stock"] == 22.0, "la venta tiene que descontar del depósito"

    consumos = api.get(f"/api/buffet/reservas/{reserva['id']}/consumos").json()
    assert consumos["total"] == 2400.0
    assert consumos["lineas"][0]["descripcion"] == "Gaseosa 500ml"
    assert consumos["lineas"][0]["cantidad"] == 2.0


def test_el_consumo_cargado_a_la_reserva_NO_entra_a_la_caja(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa
):
    """🔴 Si entrara acá **y** al cobrar la reserva, se cobraría dos veces.

    El consumo se paga cuando se paga el turno. Este test es lo único que separa
    "cargado a la cuenta del partido" de "cobrado dos veces".
    """
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    reserva = _reserva(api, cancha, cliente)
    api.post("/api/caja/turnos", json={"monto_inicial": "0"})

    api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": gaseosa["item_id"], "cantidad": "2"}],
        "reserva_id": reserva["id"]})

    turno = api.get("/api/caja/turnos/actual").json()
    assert turno["resumen"]["total_ventas"] == 0.0, (
        "el consumo de una reserva no se cobra al cargarlo")


def test_la_venta_de_mostrador_SI_entra_a_la_caja(api, sucursal, gaseosa):
    """Control del test de arriba: si nada entrara nunca a la caja, aquél
    pasaría igual sin probar la distinción."""
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    api.post("/api/caja/turnos", json={"monto_inicial": "0"})

    r = api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": gaseosa["item_id"], "cantidad": "1"}],
        "reserva_id": None, "medio_pago": "efectivo"})
    assert r.status_code == 201, r.text

    turno = api.get("/api/caja/turnos/actual").json()
    assert turno["resumen"]["efectivo_ventas"] == 1200.0


def test_la_venta_de_mostrador_sin_turno_abierto_no_entra(api, sucursal, gaseosa):
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    r = api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": gaseosa["item_id"], "cantidad": "1"}],
        "reserva_id": None, "medio_pago": "efectivo"})
    assert r.status_code == 409, r.text


def test_no_se_carga_consumo_a_una_reserva_YA_facturada(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa
):
    """🔑 No entraría en ese comprobante y quedaría cobrado sin respaldo."""
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    reserva = _reserva(api, cancha, cliente)
    assert api.post(f"/api/reservas/{reserva['id']}/facturar").status_code == 201

    r = api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": gaseosa["item_id"], "cantidad": "1"}],
        "reserva_id": reserva["id"]})
    assert r.status_code == 409, r.text


# ── El gate de F4: una factura con las dos cosas ─────────────────────────


def test_UNA_factura_con_la_cancha_y_el_buffet(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa
):
    """🔴 **El gate de F4.** Una sola factura, con las líneas separadas.

    El grupo juega y toma dos gaseosas: sale un comprobante con el alquiler y el
    consumo detallados, y el total es la suma. Es lo que hace que el buffet no
    necesite su propia numeración fiscal.
    """
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    reserva = _reserva(api, cancha, cliente)
    precio_cancha = float(reserva["precio"])

    api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": gaseosa["item_id"], "cantidad": "2"}],
        "reserva_id": reserva["id"]})

    emitida = api.post(f"/api/reservas/{reserva['id']}/facturar")
    assert emitida.status_code == 201, emitida.text
    factura = emitida.json()

    # 🔑 El total incluye el buffet. Si saliera de `reserva.precio`, el consumo
    # aparecería en el cuerpo del comprobante y ausente del importe: ARCA
    # autorizaría un CAE por menos plata de la que se cobró.
    assert factura["total"] == precio_cancha + 2400.0, factura

    # Y una sola factura: no hay un segundo comprobante por el buffet.
    from libracore.db import facturas as db_facturas

    todas = db_facturas.get_all_facturas()
    assert len(todas) == 1, f"tienen que ser una sola, hay {len(todas)}"

    lineas = todas[0]["items"]
    assert len(lineas) == 2, lineas
    assert "Alquiler de" in lineas[0]["description"]
    assert lineas[1]["description"] == "Gaseosa 500ml"
    assert lineas[1]["qty"] == 2.0
    # 🔑 Las líneas cierran contra el NETO del comprobante, no contra el total.
    # En esta factura (C, monotributista) neto == total, pero se asierta contra
    # `subtotal` igual: escrito contra `total`, el test empezaría a fallar el día
    # que el emisor sea Responsable Inscripto — y por el motivo equivocado.
    assert todas[0]["subtotal"] == pytest.approx(factura["total"]), "es una C: neto == total"
    assert sum(x["subtotal"] for x in lineas) == pytest.approx(todas[0]["subtotal"])


def test_sin_consumo_la_factura_es_la_de_siempre(
    api, cancha, cliente, tarifa_base
):
    """Control: una reserva sin buffet factura sólo la cancha, con su línea."""
    reserva = _reserva(api, cancha, cliente)
    factura = api.post(f"/api/reservas/{reserva['id']}/facturar").json()
    assert factura["total"] == float(reserva["precio"])

    from libracore.db import facturas as db_facturas

    lineas = db_facturas.get_all_facturas()[0]["items"]
    assert len(lineas) == 1
    assert "Alquiler de" in lineas[0]["description"]
    assert cancha.nombre in lineas[0]["description"]


def test_las_lineas_van_en_NETO_cuando_el_emisor_discrimina(
    api, sucursal, cancha, cliente, tarifa_base, gaseosa
):
    """🔴 El PDF le vuelve a sumar el IVA a cada línea cuando el receptor no
    discrimina. Con el precio final acá, saldría duplicado en el papel.

    En una C no se nota —el neto ES el total—, y por eso se prueba con B.
    """
    from libracore import config_manager

    config_manager.save({"empresa_iva_condition": "Responsable Inscripto"})
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    reserva = _reserva(api, cancha, cliente)
    api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": gaseosa["item_id"], "cantidad": "2"}],
        "reserva_id": reserva["id"]})

    factura = api.post(f"/api/reservas/{reserva['id']}/facturar").json()
    from libracore.db import facturas as db_facturas

    guardada = db_facturas.get_all_facturas()[0]
    linea_buffet = guardada["items"][1]
    # 2400 finales con IVA del 21% → 1983.47 de neto, no 2400.
    assert linea_buffet["subtotal"] < 2400.0, linea_buffet
    assert guardada["iva_amount"] > 0, "una B discrimina IVA"
    assert factura["total"] == float(reserva["precio"]) + 2400.0, "el total es el final"


# ── Configuración ────────────────────────────────────────────────────────


def test_sin_base_de_libracore_el_buffet_lo_dice(engine, sesion, monkeypatch, sucursal):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    sin_core = TestClient(crear_app(_config(None)), base_url="https://testserver")
    sin_core.post("/auth/login", json={"username": USUARIO, "password": CLAVE})
    try:
        r = sin_core.get(f"/api/buffet/productos?sucursal_id={sucursal.id}")
        assert r.status_code == 503, r.text
        assert "LIBRACLUB_LIBRACORE_DATABASE_URL" in r.json()["detail"]
    finally:
        AuthBase.metadata.drop_all(engine)


def test_el_alta_de_producto_es_de_admin(api, sucursal):
    api.post("/api/usuarios", json={
        "username": "mostrador-buf", "name": "Mostrador", "password": "clave-most",
        "role": "staff"})
    staff = TestClient(crear_app(_config(_url_core())), base_url="https://testserver")
    staff.post("/auth/login", json={"username": "mostrador-buf", "password": "clave-most"})

    r = staff.post(f"/api/buffet/productos?sucursal_id={sucursal.id}", json={
        "nombre": "Agua", "precio": "900.00"})
    assert r.status_code == 403, r.text
    # Pero vender y reponer sí es de mostrador.
    assert staff.get(f"/api/buffet/productos?sucursal_id={sucursal.id}").status_code == 200
