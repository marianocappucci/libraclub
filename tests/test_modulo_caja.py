"""El módulo de caja: mostradores por sucursal, egresos y anulación.

Lo pidió el humano el 2026-08-28, midiéndolo contra Contalibra: *"que tenga los
turnos de caja adentro y gestionar más de una caja"*. Y decidió que **la caja
pertenece a una sucursal y una sede puede tener más de una**.

🔴 **Lo que este módulo arregla no es cosmético.** Antes de esto el arqueo sólo
podía subir —no había forma de registrar plata que sale— y el turno no sabía en
qué sede estaba, así que ningún reporte por sucursal era posible.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app
from app.models.maestros import Sucursal

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


# ── Los mostradores ───────────────────────────────────────────────────────


def test_una_sede_puede_tener_mas_de_una_caja(api, sucursal):
    """La decisión del humano: el mostrador y el buffet son dos cajones."""
    for nombre in ("Mostrador", "Buffet"):
        r = api.post("/api/cajas", json={"nombre": nombre, "sucursal_id": sucursal.id})
        assert r.status_code == 201, r.text

    listado = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()
    assert {c["nombre"] for c in listado} == {"Mostrador", "Buffet"}


def test_las_cajas_de_una_sede_NO_aparecen_en_la_otra(api, sucursal, sesion):
    """🔴 El aislamiento por sede, que es todo el punto.

    Si el listado no filtrara, el mostrador de una sucursal podría abrir su turno
    sobre el cajón de la otra — y su arqueo saldría contra plata que no tocó.
    """
    otra = Sucursal(nombre="Complejo Norte")
    sesion.add(otra)
    sesion.commit()

    api.post("/api/cajas", json={"nombre": "Mostrador centro", "sucursal_id": sucursal.id})
    api.post("/api/cajas", json={"nombre": "Mostrador norte", "sucursal_id": otra.id})

    del_centro = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()
    assert [c["nombre"] for c in del_centro] == ["Mostrador centro"]
    # El control por el otro lado: la otra sede ve la suya y sólo la suya.
    del_norte = api.get(f"/api/cajas?sucursal_id={otra.id}").json()
    assert [c["nombre"] for c in del_norte] == ["Mostrador norte"]


def test_no_se_da_de_alta_una_caja_en_una_sucursal_que_no_existe(api):
    r = api.post("/api/cajas", json={"nombre": "Fantasma", "sucursal_id": 9999})
    assert r.status_code == 404, r.text


def test_un_medio_que_este_producto_no_cobra_se_rechaza(api, sucursal):
    """🔑 Los medios se validan contra los de ESTE producto, no contra el
    vocabulario del motor: un complejo no cobra con cheque, y ofrecerlo para que
    después el cobro conteste 422 es peor que no ofrecerlo."""
    r = api.post("/api/cajas", json={
        "nombre": "Mostrador", "sucursal_id": sucursal.id, "medios_pago": ["cheque"],
    })
    assert r.status_code == 422, r.text


def test_una_caja_con_movimientos_no_se_borra(api, sucursal, abrir_caja):
    """Borrarla dejaría arqueos apuntando a nada."""
    assert abrir_caja(api, sucursal, "0").status_code == 201
    caja = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()[0]
    api.post("/api/caja/cobros", json={
        "monto": "1000", "concepto": "Turno", "medio_pago": "efectivo",
    })

    r = api.delete(f"/api/cajas/{caja['id']}")
    assert r.status_code == 422, r.text
    assert "movimientos" in r.text


# ── El turno, sobre un mostrador ──────────────────────────────────────────


def test_el_turno_se_abre_sobre_la_caja_elegida(api, sucursal, abrir_caja):
    assert abrir_caja(api, sucursal, "5000").status_code == 201
    caja = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()[0]

    actual = api.get("/api/caja/turnos/actual").json()
    assert actual["turno"]["caja_id"] == caja["id"]
    assert actual["turno"]["caja_nombre"] == caja["nombre"]


def test_no_se_abre_el_turno_sobre_una_caja_que_no_existe(api, sucursal):
    r = api.post("/api/caja/turnos", json={"monto_inicial": "0", "caja_id": 9999})
    assert r.status_code == 404, r.text


def test_no_se_abre_el_turno_sobre_una_caja_dada_de_baja(api, sucursal):
    caja = api.post("/api/cajas", json={
        "nombre": "Vieja", "sucursal_id": sucursal.id,
    }).json()
    api.put(f"/api/cajas/{caja['id']}", json={"nombre": "Vieja", "activo": False})

    r = api.post("/api/caja/turnos", json={"monto_inicial": "0", "caja_id": caja["id"]})
    assert r.status_code == 422, r.text


# ── Los egresos ───────────────────────────────────────────────────────────


def test_un_egreso_BAJA_el_esperado_del_cajon(api, sucursal, abrir_caja):
    """🔴 Antes de esto el arqueo sólo podía subir.

    Sacar plata dejaba el cierre con un faltante sin explicación, indistinguible
    de un error de conteo o de un robo.
    """
    abrir_caja(api, sucursal, "10000")
    api.post("/api/caja/cobros", json={
        "monto": "5000", "concepto": "Turno", "medio_pago": "efectivo",
    })

    r = api.post("/api/caja/egresos", json={
        "monto": "3000", "motivo": "Retiro a banco", "medio_pago": "efectivo",
    })
    assert r.status_code == 200, r.text

    # 5000 que entraron menos 3000 que salieron.
    assert r.json()["efectivo_ventas"] == 2000.0


def test_el_motivo_del_egreso_sale_de_una_lista_cerrada(api, sucursal, abrir_caja):
    """Un motivo libre convierte el arqueo en algo que no se puede sumar por
    categoría, y «varios» termina siendo la mitad de los egresos."""
    abrir_caja(api, sucursal, "0")
    r = api.post("/api/caja/egresos", json={
        "monto": "100", "motivo": "porque sí", "medio_pago": "efectivo",
    })
    assert r.status_code == 422, r.text

    # El control: uno de la lista sí entra.
    motivos = api.get("/api/caja/motivos-de-egreso").json()
    assert motivos, "la lista de motivos llegó vacía"
    ok = api.post("/api/caja/egresos", json={
        "monto": "100", "motivo": motivos[0], "medio_pago": "efectivo",
    })
    assert ok.status_code == 200, ok.text


def test_sin_caja_abierta_no_se_registra_un_egreso(api, sucursal):
    """Igual que el cobro: quedaría fuera de todo arqueo."""
    r = api.post("/api/caja/egresos", json={
        "monto": "100", "motivo": "Retiro a banco", "medio_pago": "efectivo",
    })
    assert r.status_code == 409, r.text


# ── Anular un movimiento ──────────────────────────────────────────────────


def test_se_anula_un_movimiento_del_turno_abierto(api, sucursal, abrir_caja):
    """El caso real: el monto tipeado mal hace treinta segundos.

    ⚠️ **Este test asertaba `movimientos == []`** —o sea, que la fila
    desapareciera— hasta el 2026-08-28. Cambió porque cambió la conducta: ahora
    se **anula** y la fila queda. No es un test que se ablandó para que pase; es
    el que fija la semántica nueva, y por eso pide las dos cosas: que siga en la
    lista **y** que salga del arqueo.
    """
    abrir_caja(api, sucursal, "0")
    api.post("/api/caja/cobros", json={
        "monto": "99999", "concepto": "Mal tipeado", "medio_pago": "efectivo",
    })
    resumen = api.get("/api/caja/turnos/actual").json()["resumen"]
    assert len(resumen["movimientos"]) == 1
    assert resumen["pagos_por_medio"]["efectivo"] == 99999, "el control del total"
    mid = resumen["movimientos"][0]["id"]

    r = api.delete(f"/api/caja/movimientos/{mid}")
    assert r.status_code == 200, r.text
    assert len(r.json()["movimientos"]) == 1, "la fila queda"
    assert r.json()["movimientos"][0]["anulado"] == 1
    assert r.json()["pagos_por_medio"].get("efectivo", 0) == 0, "y sale del arqueo"
    assert r.json()["efectivo_ventas"] == 0.0


def test_no_se_anula_un_movimiento_que_no_es_del_turno_abierto(api, sucursal, abrir_caja):
    """🔴 Un arqueo cerrado es un hecho: esa diferencia la firmó alguien."""
    abrir_caja(api, sucursal, "0")
    api.post("/api/caja/cobros", json={
        "monto": "1000", "concepto": "Turno", "medio_pago": "efectivo",
    })
    mid = api.get("/api/caja/turnos/actual").json()["resumen"]["movimientos"][0]["id"]
    turno = api.get("/api/caja/turnos/actual").json()["turno"]
    api.post(f"/api/caja/turnos/{turno['id']}/cerrar", json={"monto_declarado": "1000"})

    # Turno nuevo: el movimiento de antes ya no es de éste.
    abrir_caja(api, sucursal, "0")
    r = api.delete(f"/api/caja/movimientos/{mid}")
    assert r.status_code == 404, r.text


# -- Anular no borra -------------------------------------------------------
#
# Pedido del humano el 2026-08-28: *"no deberian poder borrarse, tienen que
# quedar registrados"*. Los tests de lo que esto protege del lado de las
# reservas ---el pendiente que vuelve, y que las dos pantallas coincidan---
# estan en `test_cobro_del_turno.py`, donde viven los helpers de reserva.


# -- La caja predeterminada -------------------------------------------------
#
# Ser la predeterminada significa dos cosas REALES, medidas y no supuestas: el
# motor lista las cajas con `ORDER BY es_default DESC, nombre` ---asi que
# encabeza la lista, y la pantalla de Caja ofrece la primera elegida al abrir---
# y el motor se niega a borrarla.


def _crear_caja(api, sucursal, nombre):
    r = api.post("/api/cajas", json={
        "nombre": nombre, "descripcion": "", "medios_pago": ["efectivo"],
        "sucursal_id": sucursal.id})
    assert r.status_code == 201, r.text
    return r.json()


def test_marcar_una_caja_como_predeterminada(api, sucursal):
    """⚠️ **La primera se marca a proposito antes de marcar la segunda.**

    La version anterior de este test solo creaba las dos y marcaba la segunda,
    y despues asertaba que la primera NO fuera predeterminada ---cosa que ya era
    cierta antes de tocar nada---. La mutacion de sacar el `UPDATE ... es_default=0`
    sobrevivia: el assert pasaba por el estado inicial, no por el cambio.

    Marcando la primera primero, el assert de abajo mide el apagado de verdad.
    """
    primera = _crear_caja(api, sucursal, "Barra")
    segunda = _crear_caja(api, sucursal, "Quincho")

    assert api.post(f"/api/cajas/{primera['id']}/predeterminada").status_code == 200
    # Control del punto de partida: la primera SI quedo marcada, o el assert
    # final no distinguiria "se apago" de "nunca estuvo prendida".
    iniciales = {c["id"]: c for c in api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()}
    assert iniciales[primera["id"]]["es_default"] is True

    r = api.post(f"/api/cajas/{segunda['id']}/predeterminada")
    assert r.status_code == 200, r.text
    assert r.json()["es_default"] is True

    # 🔴 Y el control de que el cambio PERSISTIO. Un write sin commit no falla:
    # devuelve la fila que acaba de escribir en su propia transaccion y despues
    # se pierde. Se relee por otra consulta.
    cajas = {c["id"]: c for c in api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()}
    assert cajas[segunda["id"]]["es_default"] is True
    # Hay UNA predeterminada por sede, no varias: la primera se apago.
    assert cajas[primera["id"]]["es_default"] is False, (
        "quedaron dos cajas predeterminadas en la misma sede"
    )


def test_LA_PREDETERMINADA_DE_UNA_SEDE_NO_APAGA_LA_DE_LA_OTRA(api, sucursal, sesion):
    """🔴 El motivo por el que esto NO usa `set_default_caja` del motor.

    Esa funcion hace `UPDATE cajas SET es_default=0` **sin filtrar nada**. En
    Contalibra esta bien porque no tiene sedes; aca marcar la predeterminada de
    una sucursal le borraria la de la otra, y el sintoma seria que el mostrador
    de la otra sede abre el turno sobre el cajon equivocado sin que nadie haya
    tocado nada ahi.
    """
    from app.models.maestros import Sucursal

    otra = Sucursal(nombre="Sede Norte")
    sesion.add(otra)
    sesion.commit()

    de_aca = _crear_caja(api, sucursal, "Barra")
    de_alla = api.post("/api/cajas", json={
        "nombre": "Barra Norte", "descripcion": "", "medios_pago": ["efectivo"],
        "sucursal_id": otra.id}).json()

    api.post(f"/api/cajas/{de_aca['id']}/predeterminada")
    api.post(f"/api/cajas/{de_alla['id']}/predeterminada")

    # La de la otra sede sigue siendo la suya.
    de_aca_ahora = next(
        c for c in api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()
        if c["id"] == de_aca["id"]
    )
    assert de_aca_ahora["es_default"] is True, (
        "marcar la predeterminada de una sede apago la de la otra"
    )
    # Y el control positivo: la segunda TAMBIEN quedo marcada, o sea que el
    # endpoint hizo algo y el assert de arriba no pasa por no haber cambiado nada.
    de_alla_ahora = next(
        c for c in api.get(f"/api/cajas?sucursal_id={otra.id}").json()
        if c["id"] == de_alla["id"]
    )
    assert de_alla_ahora["es_default"] is True


def test_la_predeterminada_ENCABEZA_la_lista_de_su_sede(api, sucursal):
    """Es lo que hace que la pantalla de Caja la ofrezca elegida: preselecciona
    la primera activa, y el motor ordena por `es_default DESC, nombre`."""
    _crear_caja(api, sucursal, "Barra")          # alfabeticamente primera
    quincho = _crear_caja(api, sucursal, "Quincho")

    # Control de la premisa: sin marcar nada, la primera es la alfabetica.
    primeras = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()
    assert primeras[0]["nombre"] == "Barra"

    api.post(f"/api/cajas/{quincho['id']}/predeterminada")
    despues = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()
    assert despues[0]["id"] == quincho["id"], (
        f"la predeterminada no encabeza la lista: {[c['nombre'] for c in despues]}"
    )


def test_marcar_una_caja_que_no_existe_da_404(api):
    assert api.post("/api/cajas/999999/predeterminada").status_code == 404


def test_marcar_la_predeterminada_es_de_admin(api, sucursal):
    """Decide sobre que cajon abre el turno el mostrador: es configuracion."""
    caja = _crear_caja(api, sucursal, "Barra")
    api.post("/api/usuarios", json={
        "username": "encargado-cajas", "name": "Encargado",
        "password": "clave-enc", "role": "staff"})
    staff = TestClient(
        crear_app(Config(
            database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
            directorio_de_datos="/tmp/libraclub-test-datos",
            libracore_database_url=_url_core(),
        )),
        base_url="https://testserver",
    )
    assert staff.post(
        "/auth/login", json={"username": "encargado-cajas", "password": "clave-enc"}
    ).status_code == 200
    assert staff.post(f"/api/cajas/{caja['id']}/predeterminada").status_code == 403
    # El control: el admin si puede.
    assert api.post(f"/api/cajas/{caja['id']}/predeterminada").status_code == 200


# -- El reporte por medio de pago -------------------------------------------
#
# El corte de plata del complejo: lo que el dueno mira a fin de mes. De admin,
# no del mostrador.


def _cobrar(api, monto, medio="efectivo", concepto="Cancha 1"):
    r = api.post("/api/caja/cobros",
                 json={"monto": monto, "concepto": concepto, "medio_pago": medio})
    assert r.status_code == 200, r.text
    return r.json()


def test_el_reporte_separa_por_medio_de_pago(api, sucursal, abrir_caja):
    abrir_caja(api, sucursal)
    _cobrar(api, "4000", "efectivo")
    _cobrar(api, "1500", "efectivo")
    _cobrar(api, "9000", "transferencia")

    r = api.get("/api/caja/reportes/por-medio")
    assert r.status_code == 200, r.text
    datos = r.json()

    assert datos["totales"]["efectivo"]["ingresos"] == 5500.0
    assert datos["totales"]["efectivo"]["ingresos_ops"] == 2
    assert datos["totales"]["transferencia"]["ingresos"] == 9000.0
    assert datos["total_ingresos"] == 14500.0


def test_UN_MOVIMIENTO_ANULADO_NO_CUENTA_EN_EL_REPORTE(api, sucursal, abrir_caja):
    """🔴 El mismo criterio que el arqueo, y por el mismo motivo.

    Si el reporte contara los anulados, el corte de fin de mes diria una cosa y
    el arqueo del turno otra sobre la misma plata ---y el que mira no tiene
    forma de saber cual esta bien---. Lo garantiza la consulta del motor
    (`sql_no_anulado`), no un filtro de este producto.
    """
    abrir_caja(api, sucursal)
    _cobrar(api, "4000", "efectivo")
    resumen = _cobrar(api, "1000", "efectivo", concepto="Mal cargado")
    mal = next(m for m in resumen["movimientos"] if m["concepto"] == "Mal cargado")

    antes = api.get("/api/caja/reportes/por-medio").json()
    assert antes["totales"]["efectivo"]["ingresos"] == 5000.0

    assert api.delete(f"/api/caja/movimientos/{mal['id']}").status_code == 200

    despues = api.get("/api/caja/reportes/por-medio").json()
    assert despues["totales"]["efectivo"]["ingresos"] == 4000.0, (
        "el movimiento anulado sigue contando en el reporte"
    )
    assert despues["totales"]["efectivo"]["ingresos_ops"] == 1


def test_los_egresos_van_de_su_lado_y_bajan_el_saldo(api, sucursal, abrir_caja):
    abrir_caja(api, sucursal)
    _cobrar(api, "10000", "efectivo")
    assert api.post("/api/caja/egresos", json={
        "monto": "2500", "motivo": "Pago a proveedor", "detalle": "",
        "medio_pago": "efectivo"}).status_code == 200

    datos = api.get("/api/caja/reportes/por-medio").json()
    assert datos["totales"]["efectivo"]["ingresos"] == 10000.0
    assert datos["totales"]["efectivo"]["egresos"] == 2500.0
    assert datos["total_ingresos"] == 10000.0
    assert datos["total_egresos"] == 2500.0


def test_el_periodo_por_defecto_es_el_mes_en_curso(api, sucursal, abrir_caja):
    """Traer todo desde 1900 sobre una instancia con anos de movimientos es una
    consulta que nadie pidio."""
    from app.tiempo import hoy

    abrir_caja(api, sucursal)
    _cobrar(api, "1000")
    datos = api.get("/api/caja/reportes/por-medio").json()
    assert datos["desde"] == hoy().replace(day=1).isoformat()
    assert datos["hasta"] == hoy().isoformat()


def test_un_periodo_sin_movimientos_devuelve_vacio_y_no_falla(api, sucursal, abrir_caja):
    """Un periodo vacio y una consulta rota se ven igual si la pantalla queda en
    blanco. El backend tiene que distinguirlos: esto es un 200 con nada."""
    abrir_caja(api, sucursal)
    _cobrar(api, "1000")
    r = api.get("/api/caja/reportes/por-medio?desde=2020-01-01&hasta=2020-01-31")
    assert r.status_code == 200, r.text
    assert r.json()["totales"] == {}
    assert r.json()["total_ingresos"] == 0


def test_EL_TOTAL_SUMA_TODOS_LOS_MOSTRADORES(api, sucursal, abrir_caja):
    """🔴 El hueco que delato una mutacion: todos los demas tests tenian UN solo
    mostrador, asi que sumar todos o quedarse con el primero daba lo mismo.

    Un complejo con dos cajones ---que es el caso que el modulo de caja existe
    para cubrir--- habria visto un total que no incluye la mitad de la plata, y
    sin ningun error: un numero mas chico, nada mas.
    """
    abrir_caja(api, sucursal)
    primer_turno = api.get("/api/caja/turnos/actual").json()["turno"]
    _cobrar(api, "4000", "efectivo")
    api.post(f"/api/caja/turnos/{primer_turno['id']}/cerrar",
             json={"monto_declarado": "4000"})

    otra = api.post("/api/cajas", json={
        "nombre": "Quincho", "descripcion": "", "medios_pago": ["efectivo"],
        "sucursal_id": sucursal.id})
    assert otra.status_code == 201, otra.text
    api.post("/api/caja/turnos", json={"monto_inicial": "0", "caja_id": otra.json()["id"]})
    _cobrar(api, "6000", "efectivo")

    datos = api.get("/api/caja/reportes/por-medio").json()
    # Control de la premisa: hay DOS mostradores en el reporte, o este test
    # estaria midiendo lo mismo que los otros.
    assert len(datos["cajas"]) == 2, [c["nombre"] for c in datos["cajas"]]
    assert datos["total_ingresos"] == 10000.0, (
        f"el total no suma los dos mostradores: {datos['total_ingresos']}"
    )
    # Y el total por medio tambien los junta.
    assert datos["totales"]["efectivo"]["ingresos"] == 10000.0
    assert datos["totales"]["efectivo"]["ingresos_ops"] == 2


def test_filtrar_por_un_mostrador_deja_afuera_al_otro(api, sucursal, abrir_caja):
    """El selector de la pantalla manda `caja_id`; sin este test, un filtro que
    no filtra pasaria porque el total sigue siendo un numero plausible."""
    abrir_caja(api, sucursal)
    primer_turno = api.get("/api/caja/turnos/actual").json()["turno"]
    la_primera = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()[0]
    _cobrar(api, "4000", "efectivo")
    api.post(f"/api/caja/turnos/{primer_turno['id']}/cerrar",
             json={"monto_declarado": "4000"})

    otra = api.post("/api/cajas", json={
        "nombre": "Quincho", "descripcion": "", "medios_pago": ["efectivo"],
        "sucursal_id": sucursal.id}).json()
    api.post("/api/caja/turnos", json={"monto_inicial": "0", "caja_id": otra["id"]})
    _cobrar(api, "6000", "efectivo")

    solo_la_otra = api.get(f"/api/caja/reportes/por-medio?caja_id={otra['id']}").json()
    assert solo_la_otra["total_ingresos"] == 6000.0
    assert [c["nombre"] for c in solo_la_otra["cajas"]] == ["Quincho"]

    # El control: filtrando por la primera sale la otra mitad, o sea que el
    # filtro filtra y no devuelve siempre lo mismo.
    solo_la_primera = api.get(
        f"/api/caja/reportes/por-medio?caja_id={la_primera['id']}"
    ).json()
    assert solo_la_primera["total_ingresos"] == 4000.0


def test_el_reporte_es_de_admin(api, sucursal):
    """Es el corte de plata del complejo, no una herramienta del mostrador."""
    api.post("/api/usuarios", json={
        "username": "encargado-rep", "name": "Encargado",
        "password": "clave-rep", "role": "staff"})
    staff = TestClient(
        crear_app(Config(
            database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
            directorio_de_datos="/tmp/libraclub-test-datos",
            libracore_database_url=_url_core(),
        )),
        base_url="https://testserver",
    )
    assert staff.post(
        "/auth/login", json={"username": "encargado-rep", "password": "clave-rep"}
    ).status_code == 200
    assert staff.get("/api/caja/reportes/por-medio").status_code == 403
    assert staff.get("/api/caja/reportes/por-medio/export").status_code == 403
    # El control: el admin si puede.
    assert api.get("/api/caja/reportes/por-medio").status_code == 200


# -- El export --------------------------------------------------------------


def test_el_csv_sale_de_LA_MISMA_funcion_que_la_pantalla(api, sucursal, abrir_caja):
    """🔑 Un export que rearme los numeros por su cuenta es la forma clasica de
    que el CSV y la pantalla no coincidan.

    Se comparan los dos contra la misma plata: no se lee el codigo, se miden las
    dos salidas.
    """
    abrir_caja(api, sucursal)
    _cobrar(api, "4000", "efectivo")
    _cobrar(api, "9000", "transferencia")

    pantalla = api.get("/api/caja/reportes/por-medio").json()
    r = api.get("/api/caja/reportes/por-medio/export")
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    assert "caja-por-medio" in r.headers["content-disposition"]

    import csv as _csv
    import io as _io

    filas = list(_csv.reader(_io.StringIO(r.text)))
    encabezado = filas[0]
    assert encabezado[0] == "mostrador" and "ingresos" in encabezado

    total = next(f for f in filas if f and f[0] == "TOTAL")
    columna = encabezado.index("ingresos")
    assert float(total[columna]) == pantalla["total_ingresos"], (
        f"el CSV dice {total[columna]} y la pantalla {pantalla['total_ingresos']}"
    )
    # Y trae una fila por medio, no solo el total.
    medios_en_el_csv = {f[1] for f in filas[1:] if f and f[0] != "TOTAL" and len(f) > 1}
    assert medios_en_el_csv == {"efectivo", "transferencia"}, medios_en_el_csv


def test_el_csv_no_se_parte_con_una_coma_en_el_nombre(api, sucursal, abrir_caja):
    """🔴 Un nombre de mostrador con una coma adentro parte la fila si el CSV se
    arma con un `join`. Por eso se usa `csv.writer`."""
    r = api.post("/api/cajas", json={
        "nombre": "Barra, la de atras", "descripcion": "",
        "medios_pago": ["efectivo"], "sucursal_id": sucursal.id})
    assert r.status_code == 201, r.text
    caja_id = r.json()["id"]
    api.post("/api/caja/turnos", json={"monto_inicial": "0", "caja_id": caja_id})
    _cobrar(api, "1000")

    import csv as _csv
    import io as _io

    filas = list(_csv.reader(_io.StringIO(
        api.get("/api/caja/reportes/por-medio/export").text
    )))
    encabezado = filas[0]
    cuerpo = [f for f in filas[1:] if f and f[0] != "TOTAL"]
    assert cuerpo, "el CSV no trajo ninguna fila de datos"
    for fila in cuerpo:
        assert len(fila) == len(encabezado), (
            f"la fila quedo partida: {fila}"
        )
    assert any(f[0] == "Barra, la de atras" for f in cuerpo), cuerpo
