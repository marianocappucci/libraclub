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
from datetime import timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app
from app.tiempo import a_local, ahora

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


def _reserva(api, cancha, cliente, hora="20:00:00", dia="2026-09-01"):
    r = api.post(
        "/api/reservas",
        json={"cancha_id": cancha.id, "cliente_id": cliente.id,
              "comienza_at": f"{dia}T{hora}-03:00", "duracion_min": 90},
    )
    assert r.status_code == 201, f"{r.status_code} {r.text}"
    return r.json()


def _hoy() -> str:
    """El dia local, que es la ventana del listado del mostrador.

    No `date.today()`: el contenedor puede estar en UTC y a las 22:00 de aca ya
    seria el dia siguiente alla, con lo cual el turno de hoy caeria fuera de la
    ventana y el test fallaria una vez por dia, de noche.
    """
    return a_local(ahora()).date().isoformat()


def _hora(indice: int) -> str:
    """El arranque del turno numero `indice`, de 90 en 90 desde las 08:00.

    Con arranques cada hora se pisarian entre ellos —son turnos de 90— y a las
    07:00 la cancha todavia esta cerrada.
    """
    minutos = 8 * 60 + indice * 90
    return f"{minutos // 60:02d}:{minutos % 60:02d}:00"



# ── Lo que se cobra, y contra qué queda ───────────────────────────────────


def test_cobrar_un_turno_ya_facturado_ata_el_movimiento_al_comprobante(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """El orden fácil: primero la factura, después la plata."""
    reserva = _reserva(api, cancha, cliente)
    factura = api.post(f"/api/reservas/{reserva['id']}/facturar").json()
    abrir_caja(api, sucursal)

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
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """🔴 El orden real de un mostrador, y el que nadie resolvía.

    Se cobra el sábado y se factura el lunes. Pasar `factura_id` en el momento
    del cobro sólo cubre un orden; en el otro el comprobante se vería «sin
    cobrar» sobre plata que ya entró.
    """
    reserva = _reserva(api, cancha, cliente)
    abrir_caja(api, sucursal)

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


def test_una_sena_y_el_saldo_son_DOS_movimientos(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """🔴 El caso que una referencia fija por reserva perdería en silencio.

    `create_caja_movimiento` descarta un movimiento con la misma referencia y la
    misma factura que otro ya registrado. Si la referencia fuera
    `reserva-<id>` a secas, el saldo se descartaría **sin error**: la pantalla
    diría que cobró y el arqueo contaría una sola vez.
    """
    reserva = _reserva(api, cancha, cliente)
    api.post(f"/api/reservas/{reserva['id']}/facturar")
    abrir_caja(api, sucursal)

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


def test_los_cobros_de_OTRA_reserva_no_se_cuentan(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
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
    abrir_caja(api, sucursal)
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
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    reserva = _reserva(api, cancha, cliente)
    abrir_caja(api, sucursal)
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


def test_un_medio_de_pago_inventado_se_rechaza(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    reserva = _reserva(api, cancha, cliente)
    abrir_caja(api, sucursal)

    r = api.post(f"/api/reservas/{reserva['id']}/cobros",
                 json={"monto": "1000", "medio_pago": "criptomonedas"})
    assert r.status_code == 422, r.text


def test_cobrar_una_reserva_que_no_existe_da_404(api, abrir_caja, sucursal):
    abrir_caja(api, sucursal)
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


# -- El listado del mostrador ---------------------------------------------
#
# `GET /api/reservas/agenda/por-cobrar` es el selector de la Caja: que turnos
# hay que cobrar hoy. Lo que se puede romper aca es de dos clases -- que el
# turno **no aparezca** (y el mostrador no tenga como cobrarlo) o que aparezca
# **con el numero equivocado**.


def test_el_turno_de_hoy_con_pendiente_aparece_con_su_cancha_y_su_cliente(
    api, cancha, cliente, tarifa_base, sucursal,
):
    """La fila del selector tiene que alcanzar para elegir sin abrir nada mas."""
    reserva = _reserva(api, cancha, cliente, hora="20:00:00", dia=_hoy())

    r = api.get(f"/api/reservas/agenda/por-cobrar?sucursal_id={sucursal.id}")
    assert r.status_code == 200, r.text
    filas = [f for f in r.json() if f["reserva_id"] == reserva["id"]]
    assert len(filas) == 1, "el turno de hoy sin cobrar tiene que estar en el listado"

    fila = filas[0]
    assert fila["cancha"] == cancha.nombre
    assert fila["cliente"] == cliente.nombre
    assert fila["deporte"] == cancha.deporte.value
    assert fila["total"] > 0
    assert fila["pendiente"] == fila["total"]
    assert fila["cobrado"] == 0.0


def test_el_turno_YA_COBRADO_no_aparece(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """El filtro por pendiente, que es lo que hace util al listado.

    Sin el, el mostrador veria todos los turnos del dia, cobrados y no cobrados,
    y elegir el correcto pasaria a ser trabajo del operador.
    """
    reserva = _reserva(api, cancha, cliente, hora="20:00:00", dia=_hoy())
    abrir_caja(api, sucursal)
    total = api.get(f"/api/reservas/{reserva['id']}/cobros").json()["total"]

    antes = api.get(f"/api/reservas/agenda/por-cobrar?sucursal_id={sucursal.id}").json()
    assert any(f["reserva_id"] == reserva["id"] for f in antes), (
        "control: antes de cobrar tiene que estar, o lo de abajo no mide nada"
    )

    assert api.post(
        f"/api/reservas/{reserva['id']}/cobros",
        json={"monto": str(total), "medio_pago": "efectivo"},
    ).status_code == 201

    despues = api.get(f"/api/reservas/agenda/por-cobrar?sucursal_id={sucursal.id}").json()
    assert not any(f["reserva_id"] == reserva["id"] for f in despues), (
        "cobrado entero, el turno no tiene por que seguir en el listado de pendientes"
    )


def test_el_pendiente_del_listado_incluye_el_buffet(
    api, cancha, cliente, tarifa_base, sucursal,
):
    """El mismo total que el detalle y que el comprobante.

    Es el defecto que mas caro sale: el operador cobra lo que dice la fila, y si
    el buffet no esta adentro el complejo regala las consumiciones.
    """
    producto = api.post(f"/api/buffet/productos?sucursal_id={sucursal.id}", json={
        "nombre": "Gaseosa 500ml", "precio": "1200.00", "costo": "700.00",
        "stock_minimo": "6"}).json()
    assert api.post(f"/api/buffet/ajustes?sucursal_id={sucursal.id}", json={
        "item_id": producto["item_id"], "cantidad": "24",
        "motivo": "Entrega del proveedor"}).status_code == 200

    reserva = _reserva(api, cancha, cliente, hora="20:00:00", dia=_hoy())

    def _fila():
        filas = api.get(
            f"/api/reservas/agenda/por-cobrar?sucursal_id={sucursal.id}"
        ).json()
        return next(f for f in filas if f["reserva_id"] == reserva["id"])

    solo_alquiler = _fila()["total"]
    assert api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": producto["item_id"], "cantidad": "2"}],
        "reserva_id": reserva["id"]}).status_code == 201

    assert _fila()["total"] == solo_alquiler + 2400.0, (
        "las dos gaseosas cargadas a la cancha tienen que estar en lo que el "
        "mostrador va a cobrar"
    )
    # Y el mismo numero que el detalle: si se separan, una pantalla cobra de menos.
    detalle = api.get(f"/api/reservas/{reserva['id']}/cobros").json()
    assert _fila()["total"] == detalle["total"]
    assert _fila()["pendiente"] == detalle["pendiente"]


def test_el_turno_de_MANANA_no_entra_en_la_ventana(
    api, cancha, cliente, tarifa_base, sucursal,
):
    """La cota de arriba, y por que no es cosmetica.

    El filtro por pendiente corre en Python, despues del `LIMIT`. Sin cota
    superior, un complejo con la semana cargada llenaria el listado con turnos
    que todavia no se jugaron —todos impagos— y los de hoy quedarian afuera sin
    que nada avise. Este test mide la cota, no la prolijidad.
    """
    manana = (a_local(ahora()).date() + timedelta(days=1)).isoformat()
    hoy = _reserva(api, cancha, cliente, hora="20:00:00", dia=_hoy())
    futuro = _reserva(api, cancha, cliente, hora="20:00:00", dia=manana)

    ids = {
        f["reserva_id"]
        for f in api.get(
            f"/api/reservas/agenda/por-cobrar?sucursal_id={sucursal.id}"
        ).json()
    }
    assert hoy["id"] in ids, "control: el de hoy tiene que estar"
    assert futuro["id"] not in ids, "el de manana no se cobra hoy en el mostrador"


def test_el_cobro_de_OTRO_turno_no_infla_el_pendiente_de_este(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """La atribucion del lote, que es OTRO codigo que el del detalle.

    `cobrado_de_reservas` no reusa `cobros_de_reserva`: arma su propio `WHERE`
    para las N reservas de una y despues **parsea el id de vuelta** desde la
    referencia, porque `caja_movimientos` no tiene columna de reserva. Un parseo
    flojo —tomar el primer digito— le acredita a la reserva 1 la plata de la 10,
    y el mostrador muestra cobrado un turno que nadie pago.

    🔑 **Lo que sostiene la atribucion es el parseo, no el `LIKE`.** Se midio:
    aflojar los patrones a `reserva-1%` deja este test en **verde**, porque las
    filas de mas que entran igual se le atribuyen a la 10 al parsearlas. El
    `LIKE` acota el volumen de la consulta; el que decide de quien es cada peso
    es `_id_de_referencia`. Mutar el `LIKE` para "verificar" este test mediria
    la defensa que no manda.
    """
    abrir_caja(api, sucursal)
    reservas = [
        _reserva(api, cancha, cliente, hora=_hora(i), dia=_hoy())
        for i in range(10)
    ]
    primera, decima = reservas[0], reservas[9]
    assert str(decima["id"]).startswith(str(primera["id"])), (
        f"este test solo mide algo con un id prefijo del otro; salieron "
        f"{primera['id']} y {decima['id']}"
    )

    assert api.post(f"/api/reservas/{decima['id']}/cobros",
                    json={"monto": "1500", "medio_pago": "efectivo"}).status_code == 201

    filas = {
        f["reserva_id"]: f
        for f in api.get(
            f"/api/reservas/agenda/por-cobrar?sucursal_id={sucursal.id}"
        ).json()
    }
    assert filas[decima["id"]]["cobrado"] == 1500.0, "control: la plata entro en la 10"
    assert filas[primera["id"]]["cobrado"] == 0.0, (
        "la primera reserva no cobro nada; si dice 1500 el LIKE del lote se esta "
        "llevando la plata de la decima"
    )


# -- La cuenta fraccionada -------------------------------------------------
#
# Pedido del humano el 2026-08-28: un turno de cancha se cierra como una mesa de
# restaurante, *"se puede pagar solo la cancha y despues cada uno paga individual
# lo que pidio"*. Son N cobros parciales contra la misma reserva -- que es lo que
# esta ruta ya hacia para la sena. Lo unico nuevo es el `detalle`.


def test_el_detalle_del_cobro_queda_en_el_concepto(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """Sin esto, tres cobros parciales del mismo turno son indistinguibles.

    Quedarian con el mismo texto y montos que nadie puede reconstruir al dia
    siguiente. El concepto lo sigue armando el backend —la pantalla no elige el
    formato—; el `detalle` es el dato que la pantalla tiene y el backend no.
    """
    reserva = _reserva(api, cancha, cliente)
    abrir_caja(api, sucursal)

    r = api.post(
        f"/api/reservas/{reserva['id']}/cobros",
        json={"monto": "10000", "medio_pago": "efectivo",
              "detalle": "Alquiler de la cancha"},
    )
    assert r.status_code == 201, r.text
    concepto = r.json()["cobros"][0]["concepto"]
    assert "Alquiler de la cancha" in concepto, (
        "lo que se pago tiene que poder leerse en el arqueo"
    )
    # Y el concepto del backend sigue estando: el detalle se agrega, no reemplaza.
    assert cancha.nombre in concepto
    assert cliente.nombre in concepto


def test_sin_detalle_el_concepto_queda_como_estaba(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """El control del caso normal.

    Si el detalle se agregara siempre, un cobro entero quedaria con la cuenta
    repetida adentro del concepto. Y sin este control, el test de arriba pasaria
    con un backend que escribe cualquier cosa entre parentesis.
    """
    reserva = _reserva(api, cancha, cliente)
    abrir_caja(api, sucursal)

    r = api.post(
        f"/api/reservas/{reserva['id']}/cobros",
        json={"monto": "10000", "medio_pago": "efectivo"},
    )
    assert r.status_code == 201, r.text
    assert "(" not in r.json()["cobros"][0]["concepto"]


def test_dos_cobros_fraccionados_bajan_el_pendiente_una_vez_cada_uno(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,
):
    """El caso completo: primero la cancha, despues el buffet.

    Es la mecanica que sostiene el pedido. Lo que se puede romper es que el
    segundo cobro no descuente —y el complejo regale el consumo— o que descuente
    dos veces.
    """
    producto = api.post(f"/api/buffet/productos?sucursal_id={sucursal.id}", json={
        "nombre": "Gaseosa 500ml", "precio": "1200.00", "costo": "700.00",
        "stock_minimo": "6"}).json()
    assert api.post(f"/api/buffet/ajustes?sucursal_id={sucursal.id}", json={
        "item_id": producto["item_id"], "cantidad": "24",
        "motivo": "Entrega del proveedor"}).status_code == 200

    reserva = _reserva(api, cancha, cliente)
    abrir_caja(api, sucursal)
    assert api.post(f"/api/buffet/consumos?sucursal_id={sucursal.id}", json={
        "lineas": [{"item_id": producto["item_id"], "cantidad": "2"}],
        "reserva_id": reserva["id"]}).status_code == 201

    estado = api.get(f"/api/reservas/{reserva['id']}/cobros").json()
    total, buffet = estado["total"], 2400.0
    alquiler = total - buffet
    assert alquiler > 0, "el control: la tarifa tiene que dar algo, o esto no mide nada"

    # 1) El dueno de la cancha paga el alquiler.
    primero = api.post(
        f"/api/reservas/{reserva['id']}/cobros",
        json={"monto": str(alquiler), "medio_pago": "efectivo",
              "detalle": "Alquiler de la cancha"},
    )
    assert primero.status_code == 201, primero.text
    assert primero.json()["pendiente"] == buffet, (
        "despues de pagar la cancha tiene que quedar debiendose el buffet, "
        "ni mas ni menos"
    )

    # 2) El jugador paga su consumo.
    segundo = api.post(
        f"/api/reservas/{reserva['id']}/cobros",
        json={"monto": str(buffet), "medio_pago": "efectivo",
              "detalle": "2x Gaseosa 500ml"},
    )
    assert segundo.status_code == 201, segundo.text
    assert segundo.json()["pendiente"] == 0.0
    assert segundo.json()["cobrado"] == total

    # Y son DOS movimientos, con conceptos distintos: si el motor descartara el
    # segundo por referencia repetida, el pendiente diria 0 sobre plata que no
    # entro. Es el modo de falla silencioso de esta tabla.
    conceptos = [c["concepto"] for c in segundo.json()["cobros"]]
    assert len(conceptos) == 2, "el segundo cobro no se registro"
    assert len(set(conceptos)) == 2, "los dos cobros parciales no se distinguen"
