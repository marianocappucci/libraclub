"""La cuenta corriente: fiar una reserva, cobrar a cuenta y que el saldo cierre.

El motor —`libracore.db.cuenta_corriente`— lo prueba LibraCore. Lo que se fija
acá es lo que decide este producto, y que es donde puede salir mal:

- que la deuda entre por `cc_debitos`, el único de los cuatro caminos del saldo
  que este producto alimenta;
- que el cliente quede espejado en `clients` de LibraCore, o la FK corta;
- que fiar dos veces la misma reserva no duplique la deuda;
- que un pago a cuenta entre a la caja del turno **y** baje el saldo.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app
from app.tiempo import hoy

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


def _reserva(api, cancha, cliente, **extra):
    """Una reserva con precio, creada por la API (el precio lo pone la tarifa)."""
    datos = {"cancha_id": cancha.id, "cliente_id": cliente.id,
             "comienza_at": "2026-09-01T20:00:00-03:00", "duracion_min": 90}
    datos.update(extra)
    r = api.post("/api/reservas", json=datos)
    assert r.status_code == 201, r.text
    return r.json()


def test_fiar_una_reserva_deja_la_deuda_en_la_cuenta(api, cancha, cliente, tarifa_base):
    """🔴 El espejo del cliente en `clients` de LibraCore, que es lo que rompe.

    `cc_debitos.cliente_id` tiene FK a `clients` **de LibraCore**, y en este
    producto los clientes viven del lado del dominio. Sin el espejo esto falla
    con violación de clave foránea — la FK se aplica de verdad en PostgreSQL.
    """
    reserva = _reserva(api, cancha, cliente)
    r = api.post(f"/api/cuenta-corriente/reservas/{reserva['id']}/cargar")
    assert r.status_code == 200, r.text
    assert r.json()["saldo"] == float(reserva["precio"])
    assert r.json()["cliente"] == cliente.nombre


def test_fiar_dos_veces_la_misma_reserva_no_duplica_la_deuda(api, cancha, cliente, tarifa_base):
    """🔑 Un doble click en «Cargar a la cuenta» no le fía dos veces lo mismo.

    La idempotencia la da la `referencia` (`reserva-<id>`) y la resuelve el
    motor. Sin ella, la deuda duplicada se descubre cuando el cliente reclama.
    """
    reserva = _reserva(api, cancha, cliente)
    primera = api.post(f"/api/cuenta-corriente/reservas/{reserva['id']}/cargar").json()
    segunda = api.post(f"/api/cuenta-corriente/reservas/{reserva['id']}/cargar").json()
    assert segunda["saldo"] == primera["saldo"] == float(reserva["precio"])


def test_dos_reservas_distintas_si_suman(api, cancha, cliente, tarifa_base):
    """Control del test de arriba: si el saldo no subiera nunca, ese pasaría
    igual con la deuda no registrándose en absoluto."""
    a = _reserva(api, cancha, cliente)
    b = _reserva(api, cancha, cliente, comienza_at="2026-09-02T20:00:00-03:00")
    api.post(f"/api/cuenta-corriente/reservas/{a['id']}/cargar")
    saldo = api.post(f"/api/cuenta-corriente/reservas/{b['id']}/cargar").json()["saldo"]
    assert saldo == float(a["precio"]) + float(b["precio"])
    assert float(a["precio"]) > 0, "sin precio, la suma de arriba no prueba nada"


def test_un_bloqueo_no_se_puede_fiar(api, cancha):
    """No tiene cliente: no hay a quién cobrarle después.

    🔑 **Se asierta el motivo y no sólo el 422.** Un bloqueo tampoco tiene
    precio, así que si la guarda del cliente no estuviera, el pedido caería en
    la guarda siguiente y devolvería 422 igual: el test pasaría con el defecto
    puesto. Verificado mutando la guarda — con el motivo, muere.
    """
    b = api.post("/api/reservas/bloqueos", json={
        "cancha_id": cancha.id, "comienza_at": "2026-09-03T20:00:00-03:00",
        "termina_at": "2026-09-03T21:00:00-03:00", "motivo": "Mantenimiento"})
    assert b.status_code == 201, b.text
    r = api.post(f"/api/cuenta-corriente/reservas/{b.json()['id']}/cargar")
    assert r.status_code == 422, r.text
    assert "cliente" in r.json()["detail"], r.text


def test_un_pago_a_cuenta_baja_el_saldo_y_entra_a_la_caja(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """🔑 Los dos libros: el cajón y la cuenta del cliente.

    `caja_movimientos` es lo que se arquea al cerrar el turno; `cc_pagos` es lo
    que baja el saldo. Que sólo se escriba uno de los dos es el defecto que este
    test existe para encontrar: o la plata no aparece en el arqueo, o el cliente
    sigue figurando como deudor después de pagar.
    """
    reserva = _reserva(api, cancha, cliente)
    deuda = api.post(
        f"/api/cuenta-corriente/reservas/{reserva['id']}/cargar").json()["saldo"]

    abrir_caja(api, sucursal, "0")
    r = api.post(f"/api/cuenta-corriente/clientes/{cliente.id}/pagos",
                 json={"monto": "1000", "medio_pago": "efectivo"})
    assert r.status_code == 200, r.text
    assert r.json()["saldo"] == deuda - 1000.0

    turno = api.get("/api/caja/turnos/actual").json()
    assert turno["resumen"]["efectivo_ventas"] == 1000.0, "el pago tiene que estar en el cajón"


def test_dos_pagos_del_mismo_cliente_el_mismo_dia_entran_los_dos(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """🔴 La trampa de darle `referencia` al movimiento de caja.

    `create_caja_movimiento` es idempotente por referencia. Una referencia
    armada con cliente y fecha haría que el segundo pago del día **no entre a
    la caja**, mientras `cc_pagos` sí registra los dos: el saldo baja 2000 y en
    el cajón hay 1000. Por eso el movimiento va sin referencia.
    """
    reserva = _reserva(api, cancha, cliente)
    api.post(f"/api/cuenta-corriente/reservas/{reserva['id']}/cargar")
    abrir_caja(api, sucursal, "0")

    for _ in range(2):
        assert api.post(f"/api/cuenta-corriente/clientes/{cliente.id}/pagos",
                        json={"monto": "1000", "medio_pago": "efectivo"}).status_code == 200

    turno = api.get("/api/caja/turnos/actual").json()
    assert turno["resumen"]["efectivo_ventas"] == 2000.0, (
        "los dos pagos tienen que estar en el cajón, no uno")
    saldo = api.get(f"/api/cuenta-corriente/clientes/{cliente.id}").json()["saldo"]
    assert saldo == float(reserva["precio"]) - 2000.0


def test_sin_turno_abierto_no_se_cobra_a_cuenta(api, cliente):
    """🔑 Y el saldo tampoco se toca.

    El pago va por `caja.cobrar`, que corta antes de escribir en `cc_pagos`. Si
    el orden estuviera al revés, el cliente quedaría con el saldo bajado por
    plata que ninguna caja registró.
    """
    r = api.post(f"/api/cuenta-corriente/clientes/{cliente.id}/pagos",
                 json={"monto": "1000", "medio_pago": "efectivo"})
    assert r.status_code == 409, r.text
    assert api.get(f"/api/cuenta-corriente/clientes/{cliente.id}").json()["saldo"] == 0.0


def test_pagar_de_mas_deja_saldo_a_favor(api, cliente, abrir_caja, sucursal):
    """Una seña o un adelanto del mes que viene es un caso real, no un error."""
    abrir_caja(api, sucursal, "0")
    r = api.post(f"/api/cuenta-corriente/clientes/{cliente.id}/pagos",
                 json={"monto": "5000", "medio_pago": "efectivo"})
    assert r.status_code == 200, r.text
    assert r.json()["saldo"] == -5000.0


def test_el_extracto_trae_la_deuda_y_el_pago(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    reserva = _reserva(api, cancha, cliente)
    api.post(f"/api/cuenta-corriente/reservas/{reserva['id']}/cargar")
    abrir_caja(api, sucursal, "0")
    api.post(f"/api/cuenta-corriente/clientes/{cliente.id}/pagos",
             json={"monto": "1000", "medio_pago": "efectivo"})

    movs = api.get(f"/api/cuenta-corriente/clientes/{cliente.id}").json()["movimientos"]
    tipos = sorted(m["tipo"] for m in movs)
    assert tipos == ["credito", "debito"], movs
    # El monto va siempre positivo: el signo lo pone el tipo, no el número.
    assert all(m["monto"] > 0 for m in movs)


def test_la_lista_de_deudores_la_ve_el_mostrador(api, cancha, cliente, tarifa_base):
    """🔑 De staff y no de admin, a propósito.

    El encargado es el que fía y el que cobra. El cliente llega y dice "vengo a
    pagar lo que debo": sin ver el saldo no puede atenderlo. Lo que sí se corta
    es el acceso sin sesión.
    """
    reserva = _reserva(api, cancha, cliente)
    api.post(f"/api/cuenta-corriente/reservas/{reserva['id']}/cargar")

    api.post("/api/usuarios", json={
        "username": "mostrador-cc", "name": "Mostrador", "password": "clave-most",
        "role": "staff"})
    staff = TestClient(crear_app(_config(_url_core())), base_url="https://testserver")
    staff.post("/auth/login", json={"username": "mostrador-cc", "password": "clave-most"})
    assert staff.get("/api/cuenta-corriente/deudores").status_code == 200

    anonimo = TestClient(crear_app(_config(_url_core())), base_url="https://testserver")
    assert anonimo.get("/api/cuenta-corriente/deudores").status_code == 401

    deudores = api.get("/api/cuenta-corriente/deudores")
    assert deudores.status_code == 200, deudores.text
    assert [(d["cliente"], d["saldo"]) for d in deudores.json()["deudores"]] == [
        (cliente.nombre, float(reserva["precio"]))]


def test_sin_base_de_libracore_lo_dice_en_vez_de_romperse(engine, sesion, monkeypatch, cliente):
    """Una instancia sin `LIBRACLUB_LIBRACORE_DATABASE_URL` no tiene cuenta
    corriente, y tiene que decirlo con el nombre de la variable que falta."""
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    sin_core = TestClient(crear_app(_config(None)), base_url="https://testserver")
    sin_core.post("/auth/login", json={"username": USUARIO, "password": CLAVE})
    try:
        r = sin_core.get(f"/api/cuenta-corriente/clientes/{cliente.id}")
        assert r.status_code == 503, r.text
        assert "LIBRACLUB_LIBRACORE_DATABASE_URL" in r.json()["detail"]
    finally:
        AuthBase.metadata.drop_all(engine)
def test_el_total_por_cobrar_no_lo_baja_el_que_pago_de_mas(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """🔑 Los saldos a favor **no** se restan del total.

    Son cuentas distintas: lo que uno adelantó no es plata que se le deje de
    reclamar a otro. Sumando todos los saldos, este total daría más chico que lo
    que efectivamente hay que salir a cobrar, y nadie sabría por qué no cierra
    contra la columna de la pantalla.
    """
    reserva = _reserva(api, cancha, cliente)
    deuda = api.post(
        f"/api/cuenta-corriente/reservas/{reserva['id']}/cargar").json()["saldo"]

    # Un segundo cliente que paga sin deber nada: queda con saldo a favor.
    otro = api.post("/api/clientes", json={"nombre": "Adelantados FC"})
    assert otro.status_code == 201, otro.text
    abrir_caja(api, sucursal, "0")
    a_favor = api.post(f"/api/cuenta-corriente/clientes/{otro.json()['id']}/pagos",
                       json={"monto": "2500", "medio_pago": "efectivo"})
    assert a_favor.status_code == 200, a_favor.text
    assert a_favor.json()["saldo"] == -2500.0

    listado = api.get("/api/cuenta-corriente/deudores").json()
    assert listado["total_deuda"] == deuda
    # El control: los dos están en el listado, así que el total no da eso por
    # haberse quedado corto de filas.
    assert len(listado["deudores"]) == 2, listado
    assert deuda > 2500, "sin esto, restar el saldo a favor daría el mismo número"


def test_el_pago_guarda_la_fecha_el_concepto_y_la_referencia(api, cliente, abrir_caja, sucursal):
    """Lo que se teclea en el diálogo de cobro tiene que llegar al extracto.

    Sin esto, los tres campos se pueden agregar a la pantalla y perderse en el
    camino: el pago se registra igual y el saldo baja igual, así que nada se ve
    roto.
    """
    abrir_caja(api, sucursal, "0")
    r = api.post(f"/api/cuenta-corriente/clientes/{cliente.id}/pagos", json={
        "monto": "1000", "medio_pago": "transferencia", "fecha": "2026-09-10",
        "concepto": "Seña del torneo", "referencia": "TRF-4412"})
    assert r.status_code == 200, r.text

    movs = api.get(f"/api/cuenta-corriente/clientes/{cliente.id}").json()["movimientos"]
    assert len(movs) == 1, movs
    assert movs[0]["fecha"] == "2026-09-10"
    assert movs[0]["concepto"] == "Seña del torneo"
    assert movs[0]["referencia"] == "TRF-4412"
    assert movs[0]["medio"] == "transferencia"


def test_sin_fecha_ni_concepto_el_pago_usa_los_defaults(api, cliente, abrir_caja, sucursal):
    """El control del test de arriba: los tres campos son opcionales.

    Si el endpoint los exigiera, aquél pasaría igual y este cortaría.
    """
    abrir_caja(api, sucursal, "0")
    r = api.post(f"/api/cuenta-corriente/clientes/{cliente.id}/pagos",
                 json={"monto": "1000", "medio_pago": "efectivo"})
    assert r.status_code == 200, r.text

    movs = api.get(f"/api/cuenta-corriente/clientes/{cliente.id}").json()["movimientos"]
    assert movs[0]["concepto"] == "Pago a cuenta"
    assert movs[0]["fecha"] == hoy().isoformat()
    assert movs[0]["referencia"] == ""


def test_dos_pagos_con_la_misma_referencia_entran_los_dos_a_la_caja(
    api, cliente, abrir_caja, sucursal,
):
    """🔴 La referencia ahora la teclea el mostrador, y ahí está la trampa.

    `create_caja_movimiento` es idempotente por referencia. Si la referencia del
    pago se le pasara también al movimiento de caja —que es lo que hace
    Contalibra, donde el cobro no pasa por un turno— dos pagos con el mismo
    número de comprobante dejarían **un solo** movimiento en el cajón mientras
    `cc_pagos` registra los dos: el saldo baja 2000 y en la caja hay 1000.

    Y repetir la referencia no es un caso raro: es un dedo pesado sobre
    «Registrar pago», o dos cobros contra el mismo recibo.
    """
    abrir_caja(api, sucursal, "0")
    for _ in range(2):
        r = api.post(f"/api/cuenta-corriente/clientes/{cliente.id}/pagos", json={
            "monto": "1000", "medio_pago": "efectivo", "referencia": "REC-1"})
        assert r.status_code == 200, r.text

    turno = api.get("/api/caja/turnos/actual").json()
    assert turno["resumen"]["efectivo_ventas"] == 2000.0, (
        "los dos pagos tienen que estar en el cajón, no uno")
    assert api.get(
        f"/api/cuenta-corriente/clientes/{cliente.id}").json()["saldo"] == -2000.0
