"""El recibo no fiscal del turno y los tres puntos de pago de la agenda.

Pedido del humano (lista «Caja», 2026-10): *un comprobante «no válido como
factura» para darle al jugador cuando cobra el turno*, y *el turno cobrado con
otro color en la agenda: distinguir de un vistazo lo pagado, lo señado y lo
pendiente*.

El recibo es un PDF armado en el momento desde la caja (`servicios/recibo.py`);
el punto de pago de cada casillero lo estampa `servicios/disponibilidad.py` con
el mismo lote que el viejo `cobrado`.
"""

from __future__ import annotations

import io
import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from pypdf import PdfReader

from app.config import Config
from app.main import crear_app
from app.servicios import recibo as servicio_recibo

USUARIO, CLAVE = "admin", "clave-de-prueba"

#: El lunes de la semana del 2026-09-01, que es cuando `_reserva` pone el turno.
SEMANA_DE_LA_RESERVA = "2026-08-31"


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    cliente = TestClient(
        crear_app(
            Config(
                database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
                directorio_de_datos="/tmp/libraclub-test-datos",
                libracore_database_url=base_de_libracore,
            )
        ),
        base_url="https://testserver",
    )
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


def _reserva(api, cancha, cliente, hora="20:00:00", dia="2026-09-01"):
    r = api.post(
        "/api/reservas",
        json={"cancha_id": cancha.id, "cliente_id": cliente.id,
              "comienza_at": f"{dia}T{hora}-03:00", "duracion_min": 90},
    )
    assert r.status_code == 201, f"{r.status_code} {r.text}"
    return r.json()


def _cobrar(api, reserva_id, monto, medio="efectivo"):
    r = api.post(
        f"/api/reservas/{reserva_id}/cobros",
        json={"monto": str(monto), "medio_pago": medio},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _casilleros(api, cancha, sucursal, reserva_id):
    r = api.get(
        f"/api/disponibilidad/semana?sucursal_id={sucursal.id}&desde={SEMANA_DE_LA_RESERVA}"
    )
    assert r.status_code == 200, r.text
    dias = r.json()["canchas"][str(cancha.id)]
    return [t for turnos in dias.values() for t in turnos if t["reserva_id"] == reserva_id]


def _texto(respuesta) -> str:
    """El texto de todas las páginas del PDF, con los espacios normalizados."""
    lector = PdfReader(io.BytesIO(respuesta.content))
    return " ".join(" ".join(p.extract_text().split()) for p in lector.pages)


# ── El recibo: lo que dice el papel ────────────────────────────────────────


def test_el_recibo_es_un_PDF_NO_VALIDO_COMO_FACTURA(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente)
    _cobrar(api, reserva["id"], 10000)

    r = api.get(f"/api/reservas/{reserva['id']}/recibo")

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert "inline" in r.headers["content-disposition"]
    texto = _texto(r)
    # 🔑 La leyenda es lo que lo vuelve un recibo y no una factura.
    assert "no válido como factura" in texto.lower()
    # Qué se cobró y de quién.
    assert "Juan Pérez" in texto
    assert "Cancha 1" in texto
    assert "10.000" in texto
    assert "Efectivo" in texto


def test_el_recibo_lista_la_sena_y_el_saldo_con_el_medio_de_cada_uno(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """Seña en efectivo y saldo por transferencia: el papel dice los dos medios y la suma."""
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente)
    _cobrar(api, reserva["id"], 4000, "efectivo")
    _cobrar(api, reserva["id"], 6000, "transferencia")

    texto = _texto(api.get(f"/api/reservas/{reserva['id']}/recibo"))

    assert "Efectivo" in texto
    assert "Transferencia" in texto
    assert "4.000" in texto and "6.000" in texto
    # El total recibido es la suma, y no queda saldo.
    assert "10.000" in texto
    assert "pagado" in texto


def test_un_turno_con_saldo_lo_dice(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """El control de «pagado»: con media plata el papel no puede decir que está saldado."""
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente)
    _cobrar(api, reserva["id"], 4000)

    texto = _texto(api.get(f"/api/reservas/{reserva['id']}/recibo"))

    assert "saldo $6.000" in texto
    assert "pagado" not in texto


def test_sin_plata_cobrada_no_hay_recibo(api, cancha, cliente, tarifa_base):
    """Un recibo afirma que entró plata: contra un turno sin cobros, 409 y no un papel en blanco."""
    reserva = _reserva(api, cancha, cliente)

    r = api.get(f"/api/reservas/{reserva['id']}/recibo")

    assert r.status_code == 409, r.text
    assert "cobro" in r.json()["detail"].lower()


def test_recibo_de_una_reserva_que_no_existe_da_404(api):
    r = api.get("/api/reservas/99999/recibo")
    assert r.status_code == 404
    # El motivo, y no el «Not Found» de una ruta que no existe: sin esto el test pasaba aun sin la ruta.
    assert r.json()["detail"] == "no existe esa reserva"


def test_el_recibo_pide_sesion(api, cancha, cliente, tarifa_base, abrir_caja, sucursal):
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente)
    _cobrar(api, reserva["id"], 5000)
    api.post("/auth/logout")

    assert api.get(f"/api/reservas/{reserva['id']}/recibo").status_code in (401, 403)


def test_el_recibo_no_cuenta_la_plata_de_otra_reserva(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """🔴 `reserva-1-…` no es `reserva-12-…`: el recibo de una no lleva los cobros de la otra."""
    abrir_caja(api, sucursal)
    una = _reserva(api, cancha, cliente, hora="09:30:00")
    otra = _reserva(api, cancha, cliente, hora="11:00:00")
    _cobrar(api, una["id"], 3000)
    # Montos que no se parecen a nada del recibo de la primera (ni a su saldo de 7.000).
    _cobrar(api, otra["id"], 4500)

    texto = _texto(api.get(f"/api/reservas/{una['id']}/recibo"))

    assert "3.000" in texto
    assert "4.500" not in texto and "5.500" not in texto


def test_con_la_sena_devuelta_el_recibo_dice_lo_que_QUEDO(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """La devolución resta: sin ella el papel diría que se recibió una seña que ya se devolvió."""
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente)
    cobro = _cobrar(api, reserva["id"], 5000)["cobros"][0]
    # Lo mismo que escribe `cancelacion._devolver_por_caja`: un egreso `devolucion-<referencia del cobro>`.
    from app.servicios import caja as servicio_caja
    movimiento = next(
        m for m in servicio_caja.cobros_de_reserva(reserva["id"]) if m["id"] == cobro["id"]
    )
    usuario = {"id": movimiento["usuario_id"]}
    servicio_caja.registrar_devolucion(
        usuario, Decimal("5000"), "Turno cancelado", f"devolucion-{movimiento['referencia']}",
    )

    # Toda la plata volvió: no hay recibo.
    assert api.get(f"/api/reservas/{reserva['id']}/recibo").status_code == 409

    # Se cobra de nuevo una parte: el recibo es por 2.000 y no por 7.000.
    _cobrar(api, reserva["id"], 2000)
    r = api.get(f"/api/reservas/{reserva['id']}/recibo")
    assert r.status_code == 200
    texto = _texto(r)
    assert "Total recibido: $ 2.000,00" in texto
    assert "Devoluci" in texto


# ── El armado, sin base ────────────────────────────────────────────────────


def _recibo(**cambios):
    datos = dict(
        reserva_id=12, sucursal_id=3, cancha="Cancha 2",
        comienza_at=datetime(2026, 10, 28, 22, 0, tzinfo=UTC),  # 19:00 en Argentina
        jugador="Ana Gómez", cuit=None, total=Decimal("14000"),
        cobros=[{"id": 40, "fecha": "2026-10-28 18:30:00", "medio_pago": "efectivo", "monto": 14000}],
        devoluciones=[],
    )
    datos.update(cambios)
    return servicio_recibo.armar_recibo(**datos)


def test_el_numero_es_sucursal_y_reserva_y_el_turno_va_en_hora_local():
    recibo = _recibo()

    assert recibo["punto_venta"] == 3
    assert recibo["numero"] == 12
    assert recibo["concepto"] == "Turno 28/10 19:00 - Cancha 2 - pagado"
    assert recibo["cliente_razon"] == "Ana Gómez"
    assert recibo["total"] == 14000.0
    assert recibo["pagos"][0]["referencia"] == "Mov. 40"
    assert recibo["pagos"][0]["fecha"] == "2026-10-28"


def test_sin_jugador_es_consumidor_final_y_una_reserva_provisoria_del_nodo_no_imprime_el_signo():
    recibo = _recibo(jugador=None, reserva_id=-3)

    assert recibo["cliente_razon"] == "Consumidor Final"
    assert recibo["numero"] == 3


def test_el_saldo_va_en_el_concepto_y_la_devolucion_resta():
    recibo = _recibo(
        total=Decimal("14000"),
        cobros=[{"id": 1, "fecha": "2026-10-28", "medio_pago": "efectivo", "monto": 9000}],
        devoluciones=[{"id": 2, "fecha": "2026-10-28", "medio_pago": "efectivo", "monto": 4000}],
    )

    assert recibo["total"] == 5000.0
    assert [p["monto"] for p in recibo["pagos"]] == [9000.0, -4000.0]
    assert recibo["concepto"].endswith("saldo $9.000")


def test_todo_devuelto_o_nada_cobrado_levanta_SinCobros():
    with pytest.raises(servicio_recibo.SinCobros):
        _recibo(cobros=[])
    with pytest.raises(servicio_recibo.SinCobros):
        _recibo(
            cobros=[{"id": 1, "fecha": "2026-10-28", "medio_pago": "efectivo", "monto": 500}],
            devoluciones=[{"id": 2, "fecha": "2026-10-28", "medio_pago": "efectivo", "monto": 500}],
        )


# ── La agenda: pagado, señado, pendiente ───────────────────────────────────


def test_la_agenda_distingue_pendiente_senado_y_cobrado(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    abrir_caja(api, sucursal)
    pendiente = _reserva(api, cancha, cliente, hora="09:30:00")
    senado = _reserva(api, cancha, cliente, hora="11:00:00")
    cobrado = _reserva(api, cancha, cliente, hora="12:30:00")
    _cobrar(api, senado["id"], 4000)
    _cobrar(api, cobrado["id"], 10000)

    (c_pendiente,) = _casilleros(api, cancha, sucursal, pendiente["id"])
    (c_senado,) = _casilleros(api, cancha, sucursal, senado["id"])
    (c_cobrado,) = _casilleros(api, cancha, sucursal, cobrado["id"])

    assert (c_pendiente["cobro"], c_senado["cobro"], c_cobrado["cobro"]) == (
        "pendiente", "senado", "cobrado",
    )
    # Y lo que falta, que es lo que el operador quiere leer sin abrir el turno.
    assert Decimal(str(c_pendiente["saldo"])) == Decimal("10000")
    assert Decimal(str(c_senado["saldo"])) == Decimal("6000")
    assert Decimal(str(c_cobrado["saldo"])) == Decimal("0")
    # `cobrado` queda como siempre: sólo el que no debe nada.
    assert (c_pendiente["cobrado"], c_senado["cobrado"], c_cobrado["cobrado"]) == (False, False, True)


def test_el_dia_suelto_de_la_agenda_tambien_trae_el_punto_de_pago(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """`GET /api/disponibilidad/cancha/{id}` usa `marcar_cobrados`, que es otro camino que la semana."""
    abrir_caja(api, sucursal)
    reserva = _reserva(api, cancha, cliente)
    _cobrar(api, reserva["id"], 3000)

    r = api.get(f"/api/disponibilidad/cancha/{cancha.id}?dia=2026-09-01")

    assert r.status_code == 200, r.text
    (casillero,) = [t for t in r.json() if t["reserva_id"] == reserva["id"]]
    assert casillero["cobro"] == "senado"


def test_un_bloqueo_y_un_casillero_libre_no_tienen_punto_de_pago(
    api, cancha, cliente, tarifa_base, sucursal,
):
    """Sin total no hay qué cobrar: ni «pendiente» ni «cobrado»."""
    bloqueo = api.post("/api/reservas/bloqueos", json={
        "cancha_id": cancha.id,
        "comienza_at": "2026-09-01T20:00:00-03:00",
        "termina_at": "2026-09-01T21:30:00-03:00",
        "motivo": "Mantenimiento"}).json()

    (casillero,) = _casilleros(api, cancha, sucursal, bloqueo["id"])
    assert casillero["cobro"] is None and casillero["saldo"] is None

    semana = api.get(
        f"/api/disponibilidad/semana?sucursal_id={sucursal.id}&desde={SEMANA_DE_LA_RESERVA}"
    ).json()
    libres = [
        t for turnos in semana["canchas"][str(cancha.id)].values()
        for t in turnos if t["libre"]
    ]
    assert libres and all(t["cobro"] is None for t in libres)
