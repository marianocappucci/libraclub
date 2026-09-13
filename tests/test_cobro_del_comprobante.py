"""El cobro de UN comprobante, desde su propio detalle.

Distinto de `test_cobro_del_turno.py`: ahí se cobra `/api/reservas/{id}/cobros`,
sin pasar por ningún comprobante hasta que `factura_id` ya existe. Acá se cobra
`POST /api/facturas/{id}/cobrar` — la ruta que arma
`libracore.facturas_router.build_comprobantes_router` — sobre una factura que
puede no venir de ninguna reserva (la manual, `POST /api/facturas`).

🔑 **Lo que se prueba es el hook `_cobrar_del_turno` de `app/routers/facturas.py`,
no el motor.** El motor (`libracore.cobros.registrar_cobro_factura`) tiene sus
38 tests propios; acá lo que importa es que la plata entre por la caja del
TURNO abierto —con su `turno_id`— y no por el default del motor, que la dejaría
fuera de todo arqueo.
"""

from __future__ import annotations

import os
from datetime import date

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


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(
        crear_app(Config(
            database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
            directorio_de_datos="/tmp/libraclub-test-datos",
            libracore_database_url=base_de_libracore,
        )),
        base_url="https://testserver",
    )
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


HOY = date.today().isoformat()


def _factura_manual(**extra) -> dict:
    """Una factura que no sale de ninguna reserva — el caso que
    `POST /api/facturas` cubre y que un turno de cancha no.

    Mismo helper que `test_facturacion.py`, copiado y no importado: cada
    archivo de esta suite arma sus propios helpers chicos (ver
    `test_cobro_del_turno.py`), y un `import` cruzado entre archivos de test
    ata su evolución sin necesidad.
    """
    cuerpo = {
        "tipo": 11, "punto_venta": 1, "fecha": HOY,
        "condicion_venta": "Contado", "client_name": "Marcela Gutierrez",
        "items": [{"description": "Clase particular", "qty": 1, "unit_price": 9000.0}],
    }
    cuerpo.update(extra)
    return cuerpo


def _cobrar(api, factura_id: int, pagos: list[dict]):
    return api.post(f"/api/facturas/{factura_id}/cobrar", json={"pagos": pagos})


# ── El camino feliz: la plata entra por la caja del turno ──────────────────


def test_cobrar_con_turno_abierto_ata_el_movimiento_al_turno_y_a_la_factura(
    api, sucursal, abrir_caja,
):
    """🔑 Lo que este cambio vino a arreglar: el default del motor escribe el
    movimiento SIN `turno_id`, fuera de todo arqueo. Acá tiene que llevarlo."""
    turno = abrir_caja(api, sucursal).json()
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    r = _cobrar(api, factura["id"], [{"medio_id": "efectivo", "monto": 9000.0}])
    assert r.status_code == 200, r.text

    detalle = r.json()
    assert detalle["pendiente"] == 0.0
    assert len(detalle["cobros"]) == 1
    cobro = detalle["cobros"][0]
    # Los cuatro datos que tienen que quedar atados, y a lo que abrió el turno.
    assert cobro["factura_id"] == factura["id"]
    assert cobro["turno_id"] == turno["id"], (
        "sin esto la plata entró fuera del arqueo del turno — el defecto que "
        "este cambio vino a cerrar"
    )
    assert cobro["caja_id"] == turno["caja_id"]
    assert cobro["usuario_id"] == turno["usuario_id"]

    # Y el arqueo del turno lo cuenta: no sólo el detalle de la factura.
    resumen = api.get("/api/caja/turnos/actual").json()["resumen"]
    assert resumen["pagos_por_medio"]["efectivo"] == 9000.0


def test_cobrar_en_dos_medios_deja_dos_movimientos_en_el_mismo_turno(
    api, sucursal, abrir_caja,
):
    turno = abrir_caja(api, sucursal).json()
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    r = _cobrar(api, factura["id"], [
        {"medio_id": "efectivo", "monto": 4000.0},
        {"medio_id": "transferencia", "monto": 5000.0},
    ])
    assert r.status_code == 200, r.text

    detalle = r.json()
    assert detalle["pendiente"] == 0.0
    assert len(detalle["cobros"]) == 2
    assert {c["turno_id"] for c in detalle["cobros"]} == {turno["id"]}
    assert {c["medio_pago"] for c in detalle["cobros"]} == {"efectivo", "transferencia"}


# ── Las guardas, y que no dejen escrito un cobro parcial ────────────────────


def test_sin_turno_abierto_da_409_y_no_escribe_nada(api):
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    r = _cobrar(api, factura["id"], [{"medio_id": "efectivo", "monto": 9000.0}])
    assert r.status_code == 409, r.text
    assert "caja abierta" in r.text.lower()

    detalle = api.get(f"/api/facturas/{factura['id']}").json()
    assert detalle["cobros"] == [], "no debería haber quedado ningún movimiento"
    assert detalle["pendiente"] == 9000.0


def test_un_medio_invalido_en_el_SEGUNDO_pago_no_deja_escrito_el_primero(
    api, sucursal, abrir_caja,
):
    """🔴 El caso que la prevalidación existe para evitar: sin ella, el primer
    pago (válido) ya habría escrito su movimiento cuando el segundo revienta."""
    abrir_caja(api, sucursal)
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    r = _cobrar(api, factura["id"], [
        {"medio_id": "efectivo", "monto": 4000.0},
        {"medio_id": "cheque", "monto": 5000.0},
    ])
    assert r.status_code == 400, r.text

    detalle = api.get(f"/api/facturas/{factura['id']}").json()
    assert detalle["cobros"] == [], (
        "el pago en efectivo (el primero, válido) no debería haber quedado "
        "escrito: se valida TODO antes de escribir nada"
    )
    assert detalle["pendiente"] == 9000.0


def test_cuenta_corriente_como_medio_de_pago_la_rechaza_el_motor(
    api, sucursal, abrir_caja,
):
    """La cuenta corriente NO es un medio de cobro — es la marca de que el
    comprobante se emitió a crédito. Sigue siendo el motor el que la rechaza
    (`MedioNoEsDeCobro`); este producto no la agrega a su propia lista."""
    abrir_caja(api, sucursal)
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    r = _cobrar(api, factura["id"], [{"medio_id": "cuenta_corriente", "monto": 9000.0}])
    assert r.status_code == 400, r.text
    assert "cuenta corriente" in r.text.lower()

    detalle = api.get(f"/api/facturas/{factura['id']}").json()
    assert detalle["cobros"] == []
    assert detalle["pendiente"] == 9000.0


def test_una_factura_a_cuenta_corriente_no_se_cobra_desde_aca(
    api, sucursal, abrir_caja,
):
    """🔴 La cuenta corriente de este producto es un sistema propio del dominio
    (`servicios/cuenta_corriente.py`), sin forma de imputar un pago a UNA
    factura puntual. El camino de este diálogo se corta con 409 antes de
    tocar la caja del turno."""
    abrir_caja(api, sucursal)
    factura = api.post(
        "/api/facturas", json=_factura_manual(condicion_venta="Cuenta Corriente")
    ).json()

    r = _cobrar(api, factura["id"], [{"medio_id": "efectivo", "monto": 9000.0}])
    assert r.status_code == 409, r.text
    assert "cuenta corriente" in r.text.lower()

    detalle = api.get(f"/api/facturas/{factura['id']}").json()
    assert detalle["cobros"] == [], "nada de lo que este diálogo pida se escribe"
    assert detalle["pendiente"] == 9000.0
