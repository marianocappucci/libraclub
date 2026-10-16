"""El cobro de UN comprobante, desde su propio detalle.

Distinto de `test_cobro_del_turno.py`: ahí se cobra `/api/reservas/{id}/cobros`,
sin pasar por ningún comprobante hasta que `factura_id` ya existe. Acá se cobra
`POST /api/facturas/{id}/cobrar` — la ruta que arma
`libracore.facturas_router.build_comprobantes_router` — sobre una factura que
puede no venir de ninguna reserva (la manual, `POST /api/facturas`).

🔑 **Lo que se prueba es el montaje de `build_comprobantes_router` en
`app/routers/facturas.py` (`exigir_turno=True`, `usuario_del_turno` y
`_validar_cobro`), no el motor.** El motor (`libracore.cobros.registrar_cobro_factura`)
tiene sus tests propios; acá lo que importa es que la plata entre por la caja
del TURNO abierto —con su `turno_id`— y no suelta, que la dejaría fuera de todo
arqueo, y que el tope de lo pendiente (ADR-058) rija por las dos puertas de
este producto: `POST /api/facturas/{id}/cobrar` y `POST /api/caja/cobros` con
`factura_id`.
"""

from __future__ import annotations

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
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


# ── El cobro por el turno es el del motor: fecha y caja no se eligen ────────


def test_la_fecha_y_la_caja_del_pedido_se_ignoran_y_manda_el_turno(
    api, sucursal, abrir_caja,
):
    """`exigir_turno` (ADR-060): la caja y el dueño del movimiento son los del
    turno abierto y el día es hoy. Mandar otra caja o otra fecha no abre una
    segunda puerta para cargar plata donde no es."""
    turno = abrir_caja(api, sucursal).json()
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    r = api.post(f"/api/facturas/{factura['id']}/cobrar", json={
        "pagos": [{"medio_id": "efectivo", "monto": 9000.0}],
        "fecha": "2020-01-01", "caja_id": 999999,
    })
    assert r.status_code == 200, r.text

    cobro = r.json()["cobros"][0]
    assert cobro["turno_id"] == turno["id"]
    assert cobro["caja_id"] == turno["caja_id"]
    assert cobro["usuario_id"] == turno["usuario_id"]
    assert cobro["fecha"] == HOY


# ── El tope: un cobro no puede superar lo que falta (ADR-058) ───────────────


def test_cobrar_de_mas_desde_el_detalle_da_409_y_no_escribe_nada(
    api, sucursal, abrir_caja,
):
    abrir_caja(api, sucursal)
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    r = _cobrar(api, factura["id"], [{"medio_id": "efectivo", "monto": 9001.0}])
    assert r.status_code == 409, r.text
    assert "falta cobrar" in r.text

    detalle = api.get(f"/api/facturas/{factura['id']}").json()
    assert detalle["cobros"] == []
    assert detalle["pendiente"] == 9000.0


def test_la_suma_de_los_medios_es_la_que_no_puede_superar_lo_que_falta(
    api, sucursal, abrir_caja,
):
    abrir_caja(api, sucursal)
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    r = _cobrar(api, factura["id"], [
        {"medio_id": "efectivo", "monto": 5000.0},
        {"medio_id": "transferencia", "monto": 5000.0},
    ])
    assert r.status_code == 409, r.text
    assert api.get(f"/api/facturas/{factura['id']}").json()["cobros"] == [], (
        "ninguno de los dos medios debe quedar escrito"
    )


# ── `POST /api/caja/cobros` con `factura_id`: la otra puerta, con el mismo tope ─


def _cobro_de_caja(api, factura_id: int | None, monto: float, **extra):
    cuerpo = {
        "monto": str(monto), "concepto": "Cobro desde la caja",
        "medio_pago": "efectivo", "factura_id": factura_id,
    }
    cuerpo.update(extra)
    return api.post("/api/caja/cobros", json=cuerpo)


def test_el_cobro_de_la_caja_con_factura_queda_en_el_turno_y_en_la_factura(
    api, sucursal, abrir_caja,
):
    turno = abrir_caja(api, sucursal).json()
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    r = _cobro_de_caja(api, factura["id"], 4000.0)
    assert r.status_code == 200, r.text
    assert r.json()["pagos_por_medio"]["efectivo"] == 4000.0

    detalle = api.get(f"/api/facturas/{factura['id']}").json()
    assert detalle["pendiente"] == 5000.0
    cobro = detalle["cobros"][0]
    assert cobro["turno_id"] == turno["id"]
    assert cobro["usuario_id"] == turno["usuario_id"]


def test_el_cobro_de_la_caja_de_mas_da_409_y_no_escribe_nada(
    api, sucursal, abrir_caja,
):
    """🔴 Antes entraba: 9.999 sobre 9.000 dejaba «Cobrado completo — $ 9.999»
    y un ingreso de 9.999 en el arqueo."""
    abrir_caja(api, sucursal)
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    r = _cobro_de_caja(api, factura["id"], 9999.0)
    assert r.status_code == 409, r.text
    assert "falta cobrar" in r.text

    assert api.get(f"/api/facturas/{factura['id']}").json()["cobros"] == []
    resumen = api.get("/api/caja/turnos/actual").json()["resumen"]
    assert resumen["pagos_por_medio"].get("efectivo", 0) == 0, (
        "el 409 no puede dejar plata en el arqueo del turno"
    )


def test_el_tope_cuenta_lo_cobrado_por_cualquiera_de_las_dos_puertas(
    api, sucursal, abrir_caja,
):
    abrir_caja(api, sucursal)
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    assert _cobro_de_caja(api, factura["id"], 5000.0).status_code == 200
    # Faltan 4.000: 5.000 por el diálogo del comprobante ya no entra...
    assert _cobrar(api, factura["id"], [{"medio_id": "efectivo", "monto": 5000.0}]).status_code == 409
    # ...ni por la caja, y lo justo sí.
    assert _cobro_de_caja(api, factura["id"], 4000.01).status_code == 409
    assert _cobro_de_caja(api, factura["id"], 4000.0).status_code == 200

    detalle = api.get(f"/api/facturas/{factura['id']}").json()
    assert detalle["pendiente"] == 0.0
    assert len(detalle["cobros"]) == 2
    # Cobrada: no entra ni un centavo más.
    assert _cobro_de_caja(api, factura["id"], 1.0).status_code == 409


def test_el_cobro_de_la_caja_con_factura_sin_turno_da_409_y_no_escribe_nada(api):
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    r = _cobro_de_caja(api, factura["id"], 1000.0)
    assert r.status_code == 409, r.text
    assert "caja abierta" in r.text.lower()
    assert api.get(f"/api/facturas/{factura['id']}").json()["cobros"] == []


def test_el_cobro_de_la_caja_con_una_factura_que_no_existe_da_404(
    api, sucursal, abrir_caja,
):
    abrir_caja(api, sucursal)
    r = _cobro_de_caja(api, 987654, 1000.0)
    assert r.status_code == 404, r.text


def test_el_cobro_de_la_caja_sin_factura_no_tiene_tope(api, sucursal, abrir_caja):
    """Sin `factura_id` no hay contra qué topar: una seña, una venta de mostrador."""
    abrir_caja(api, sucursal)

    r = _cobro_de_caja(api, None, 1_000_000.0)
    assert r.status_code == 200, r.text
    assert r.json()["pagos_por_medio"]["efectivo"] == 1_000_000.0
