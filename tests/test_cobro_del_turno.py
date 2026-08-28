"""El cobro de un turno, atado a su comprobante.

`facturar_reserva` declaraba este modelo desde el día uno —*"la seña y el saldo
son dos movimientos de caja contra la MISMA factura"*— y **nadie lo
implementaba**: hasta el 2026-08-28 ningún cobro en efectivo llevaba
`factura_id`. La pantalla de Caja carga monto y concepto libre, sin vínculo con
la reserva, así que la pregunta *"¿esta factura está cobrada?"* no tenía forma
de contestarse y la columna de cobrado quedaba apagada en las tres pantallas del
kit.

🔴 **Lo que más se puede romper acá es silencioso.** `create_caja_movimiento`
del motor descarta —sin avisar— un movimiento con la misma referencia y la misma
factura que otro. Una referencia fija por reserva haría que la seña se registre
y el saldo **desaparezca**: plata que entró y que ningún arqueo cuenta. De ahí
que el test de los dos cobros lleve su control.
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


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
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


def _reserva(api, cancha, cliente, hora="20:00:00"):
    r = api.post(
        "/api/reservas",
        json={"cancha_id": cancha.id, "cliente_id": cliente.id,
              "comienza_at": f"2026-09-01T{hora}-03:00", "duracion_min": 90},
    )
    assert r.status_code == 201, f"{r.status_code} {r.text}"
    return r.json()


def _abrir_caja(api):
    assert api.post("/api/caja/turnos", json={"monto_inicial": "0"}).status_code == 201


# ── Lo que se cobra, y contra qué queda ───────────────────────────────────


def test_cobrar_un_turno_ya_facturado_ata_el_movimiento_al_comprobante(
    api, cancha, cliente, tarifa_base
):
    """El orden fácil: primero la factura, después la plata."""
    reserva = _reserva(api, cancha, cliente)
    factura = api.post(f"/api/reservas/{reserva['id']}/facturar").json()
    _abrir_caja(api)

    r = api.post(
        f"/api/reservas/{reserva['id']}/cobros",
        json={"monto": "5000", "medio_pago": "efectivo"},
    )
    assert r.status_code == 201, r.text

    estado = r.json()
    assert estado["cobrado"] == 5000.0
    assert len(estado["cobros"]) == 1
    # 🔑 Lo que importa: el movimiento nació apuntando al comprobante.
    assert estado["cobros"][0]["factura_id"] == factura["id"]


def test_cobrar_ANTES_de_facturar_y_el_vinculo_se_completa_al_emitir(
    api, cancha, cliente, tarifa_base
):
    """🔴 El orden real de un mostrador, y el que nadie resolvía.

    Se cobra el sábado y se factura el lunes. Pasar `factura_id` en el momento
    del cobro sólo cubre un orden; en el otro el comprobante se vería «sin
    cobrar» sobre plata que ya entró.
    """
    reserva = _reserva(api, cancha, cliente)
    _abrir_caja(api)

    cobro = api.post(
        f"/api/reservas/{reserva['id']}/cobros",
        json={"monto": "5000", "medio_pago": "efectivo"},
    )
    assert cobro.status_code == 201, cobro.text
    # Todavía sin comprobante: el movimiento existe y no apunta a nada.
    assert cobro.json()["cobros"][0]["factura_id"] is None

    factura = api.post(f"/api/reservas/{reserva['id']}/facturar").json()

    despues = api.get(f"/api/reservas/{reserva['id']}/cobros").json()
    assert despues["cobros"][0]["factura_id"] == factura["id"], (
        "emitir el comprobante tiene que alcanzar a la plata que ya había entrado"
    )


def test_una_sena_y_el_saldo_son_DOS_movimientos(api, cancha, cliente, tarifa_base):
    """🔴 El caso que una referencia fija por reserva perdería en silencio.

    `create_caja_movimiento` descarta un movimiento con la misma referencia y la
    misma factura que otro ya registrado. Si la referencia fuera
    `reserva-<id>` a secas, el saldo se descartaría **sin error**: la pantalla
    diría que cobró y el arqueo contaría una sola vez.
    """
    reserva = _reserva(api, cancha, cliente)
    api.post(f"/api/reservas/{reserva['id']}/facturar")
    _abrir_caja(api)

    api.post(f"/api/reservas/{reserva['id']}/cobros",
             json={"monto": "2000", "medio_pago": "efectivo"})
    segundo = api.post(f"/api/reservas/{reserva['id']}/cobros",
                       json={"monto": "3000", "medio_pago": "transferencia"})
    assert segundo.status_code == 201, segundo.text

    estado = segundo.json()
    assert len(estado["cobros"]) == 2, "el segundo cobro no se registró"
    assert estado["cobrado"] == 5000.0
    # Y los dos contra el mismo comprobante, que es el modelo declarado.
    assert len({c["factura_id"] for c in estado["cobros"]}) == 1


def test_los_cobros_de_OTRA_reserva_no_se_cuentan(api, cancha, cliente, tarifa_base):
    """🔴 El control del `LIKE`, y hay que elegir bien los ids.

    Las referencias son `reserva-<id>-<azar>` y se buscan con `LIKE
    'reserva-<id>-%'`. Lo que sostiene ese guion es que la reserva **1** no se
    lleve la plata de la **10**, la 12 o la 199.

    ⚠️ **La primera versión de este test comparaba la reserva 1 con la 2**, y con
    ids consecutivos `reserva-1%` y `reserva-1-%` matchean igual: pasaba en verde
    con el guion sacado. Lo delató la mutación, no la lectura. Por eso acá se
    crean **diez** reservas y se comparan la 1 y la 10, que es el único par donde
    un id es prefijo del otro.
    """
    _abrir_caja(api)
    # Diez turnos **encadenados** en la misma cancha: los ids salen 1..10 porque
    # la tabla se trunca con RESTART IDENTITY antes de cada test.
    #
    # De 90 en 90 minutos desde las 08:00, que es cuando la cancha abre: con
    # arranques cada hora se pisarían entre ellos —son turnos de 90— y con uno a
    # las 07:00 la cancha todavía está cerrada. Los diez terminan 23:00.
    reservas = []
    for i in range(10):
        minutos = 8 * 60 + i * 90
        reservas.append(
            _reserva(api, cancha, cliente, hora=f"{minutos // 60:02d}:{minutos % 60:02d}:00")
        )
    primera, decima = reservas[0], reservas[9]
    assert str(decima["id"]).startswith(str(primera["id"])), (
        "este test sólo mide algo si un id es prefijo del otro; "
        f"salieron {primera['id']} y {decima['id']}"
    )

    api.post(f"/api/reservas/{decima['id']}/cobros",
             json={"monto": "1500", "medio_pago": "efectivo"})

    # La 1 NO puede ver la plata de la 10.
    de_la_primera = api.get(f"/api/reservas/{primera['id']}/cobros").json()
    assert de_la_primera["cobrado"] == 0.0, (
        "la reserva 1 se está llevando los cobros de la 10: al `LIKE` le falta "
        "el guion que separa el id"
    )
    assert de_la_primera["cobros"] == []
    # El control positivo: la que sí cobró, la ve.
    assert api.get(f"/api/reservas/{decima['id']}/cobros").json()["cobrado"] == 1500.0


# ── Lo que vale el turno ──────────────────────────────────────────────────


def test_el_pendiente_incluye_el_buffet(api, cancha, cliente, tarifa_base, sucursal):
    """🔑 El total se arma igual que el del comprobante: alquiler + consumo.

    Si saliera de `reserva.precio` a secas, la pantalla diría «pendiente» de más
    abajo del real sobre un turno con dos gaseosas sin cobrar.

    ⚠️ **La primera versión de este test no cargaba ningún consumo**: asertaba
    `total > 0`, que se cumple con el alquiler solo. Pasaba en verde con el
    buffet sacado de la cuenta. Lo delató la mutación.
    """
    producto = api.post(f"/api/buffet/productos?sucursal_id={sucursal.id}", json={
        "nombre": "Gaseosa 500ml", "precio": "1200.00", "costo": "700.00",
        "stock_minimo": "6"}).json()
    assert api.post(f"/api/buffet/ajustes?sucursal_id={sucursal.id}", json={
        "item_id": producto["item_id"], "cantidad": "24",
        "motivo": "Entrega del proveedor"}).status_code == 200

    reserva = _reserva(api, cancha, cliente)
    solo_alquiler = api.get(f"/api/reservas/{reserva['id']}/cobros").json()["total"]

    consumo = api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": producto["item_id"], "cantidad": "2"}],
        "reserva_id": reserva["id"]})
    assert consumo.status_code == 201, consumo.text
    assert consumo.json()["total"] == 2400.0

    con_buffet = api.get(f"/api/reservas/{reserva['id']}/cobros").json()
    assert con_buffet["total"] == solo_alquiler + 2400.0, (
        "las dos gaseosas tienen que entrar en lo que hay que cobrar del turno"
    )
    assert con_buffet["pendiente"] == con_buffet["total"]
    assert con_buffet["cobrado"] == 0.0


def test_cobrar_de_mas_no_deja_el_pendiente_en_negativo(
    api, cancha, cliente, tarifa_base
):
    reserva = _reserva(api, cancha, cliente)
    _abrir_caja(api)
    total = api.get(f"/api/reservas/{reserva['id']}/cobros").json()["total"]

    api.post(f"/api/reservas/{reserva['id']}/cobros",
             json={"monto": str(total + 1000), "medio_pago": "efectivo"})

    estado = api.get(f"/api/reservas/{reserva['id']}/cobros").json()
    assert estado["pendiente"] == 0.0
    assert estado["cobrado"] > estado["total"]


# ── Las guardas ───────────────────────────────────────────────────────────


def test_sin_caja_abierta_no_se_cobra(api, cancha, cliente, tarifa_base):
    """🔴 Un cobro sin turno queda fuera de todo arqueo: plata que entró y que
    ningún cierre cuenta. Es lo que una caja viene a evitar."""
    reserva = _reserva(api, cancha, cliente)

    r = api.post(f"/api/reservas/{reserva['id']}/cobros",
                 json={"monto": "1000", "medio_pago": "efectivo"})
    assert r.status_code == 409, r.text
    assert "caja abierta" in r.text.lower()


def test_un_medio_de_pago_inventado_se_rechaza(api, cancha, cliente, tarifa_base):
    reserva = _reserva(api, cancha, cliente)
    _abrir_caja(api)

    r = api.post(f"/api/reservas/{reserva['id']}/cobros",
                 json={"monto": "1000", "medio_pago": "criptomonedas"})
    assert r.status_code == 422, r.text


def test_cobrar_una_reserva_que_no_existe_da_404(api):
    _abrir_caja(api)
    r = api.post("/api/reservas/999999/cobros",
                 json={"monto": "1000", "medio_pago": "efectivo"})
    assert r.status_code == 404


def test_sin_base_de_libracore_el_cobro_lo_DICE(engine, sesion, monkeypatch, cancha,
                                                cliente, tarifa_base):
    """503 nombrando la variable: la caja vive del lado del motor, y sin eso el
    mostrador recibiría un error de conexión de psycopg."""
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente_api = TestClient(
        crear_app(
            Config(
                database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
                directorio_de_datos="/tmp/libraclub-test-datos",
                libracore_database_url=None,
            )
        ),
        base_url="https://testserver",
    )
    assert cliente_api.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    reserva = _reserva(cliente_api, cancha, cliente)

    r = cliente_api.get(f"/api/reservas/{reserva['id']}/cobros")
    assert r.status_code == 503, r.text
    assert "LIBRACLUB_LIBRACORE_DATABASE_URL" in r.text
    AuthBase.metadata.drop_all(engine)
