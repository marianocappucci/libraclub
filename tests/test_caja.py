"""La caja por turno: abrir, cobrar, cerrar, y que el arqueo diga la verdad.

El motor es `libracore.db.turnos` y lo prueba LibraCore. Lo que se fija acá es lo
que decide este producto: que el mostrador abra **su** caja, que no se pueda
cobrar fuera de turno, que el esperado se calcule sobre `caja_movimientos` —y no
sobre la tabla `ventas`, que en este producto está vacía— y que nadie cierre la
caja de otro.
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


def test_abrir_la_caja_espeja_al_usuario_en_libracore(api, abrir_caja, sucursal):
    """🔴 El arreglo que hace falta porque las dos bases están al revés.

    `turnos_caja.usuario_id` tiene una FK a `usuarios` **de LibraCore**, y en
    este producto los usuarios viven del lado del dominio. Sin el espejo, abrir
    un turno falla con una violación de clave foránea — la FK se aplica de
    verdad en PostgreSQL, está verificado.
    """
    r = abrir_caja(api, sucursal, "5000")
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "abierto"
    assert r.json()["monto_inicial"] == 5000.0


def test_no_se_abren_dos_cajas_a_la_vez(api, abrir_caja, sucursal):
    assert abrir_caja(api, sucursal, "0").status_code == 201
    assert abrir_caja(api, sucursal, "0").status_code == 409


def test_sin_turno_abierto_no_se_puede_cobrar(api):
    """🔑 Un cobro sin turno queda fuera de todo arqueo: plata que entró y que
    ningún cierre va a contar. Se corta con 409, no se acepta en silencio."""
    r = api.post("/api/caja/cobros", json={
        "monto": "1000", "concepto": "Seña", "medio_pago": "efectivo",
    })
    assert r.status_code == 409, r.text


def test_un_medio_de_pago_desconocido_no_entra(api, abrir_caja, sucursal):
    abrir_caja(api, sucursal, "0")
    r = api.post("/api/caja/cobros", json={
        "monto": "1000", "concepto": "Seña", "medio_pago": "cheque",
    })
    assert r.status_code == 422, r.text


def test_el_arqueo_cuenta_el_efectivo_y_NO_lo_demas(api, abrir_caja, sucursal):
    """🔑 El esperado es lo que tiene que haber **en el cajón**.

    Una transferencia entró, pero no en efectivo: contarla en el esperado haría
    que toda caja con transferencias cierre con faltante. Lo que no es efectivo
    queda en el resumen de la terminal o del banco.
    """
    abrir_caja(api, sucursal, "1000")
    api.post("/api/caja/cobros", json={
        "monto": "5000", "concepto": "Cancha 1", "medio_pago": "efectivo"})
    api.post("/api/caja/cobros", json={
        "monto": "9000", "concepto": "Cancha 2", "medio_pago": "transferencia"})

    turno = api.get("/api/caja/turnos/actual").json()["turno"]
    cierre = api.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                      json={"monto_declarado": "6000"})
    assert cierre.status_code == 200, cierre.text
    c = cierre.json()
    # 1000 de inicial + 5000 de efectivo. Los 9000 de transferencia NO entran.
    assert c["monto_esperado_cierre"] == 6000.0
    assert c["diferencia_de_caja"] == 0.0


def test_la_diferencia_se_guarda_y_no_se_corrige(api, abrir_caja, sucursal):
    """Un cierre que no cuadra es un dato: faltó plata, sobró, o alguien no
    cargó un cobro. Ajustarlo al esperado borraría lo que hay que mirar."""
    abrir_caja(api, sucursal, "1000")
    api.post("/api/caja/cobros", json={
        "monto": "5000", "concepto": "Cancha 1", "medio_pago": "efectivo"})
    turno = api.get("/api/caja/turnos/actual").json()["turno"]
    c = api.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                 json={"monto_declarado": "5500"}).json()
    assert c["monto_esperado_cierre"] == 6000.0
    assert c["monto_declarado_cierre"] == 5500.0
    assert c["diferencia_de_caja"] == -500.0, "faltaron 500 y tiene que quedar escrito"


def test_un_turno_cerrado_no_se_cierra_de_nuevo(api, abrir_caja, sucursal):
    abrir_caja(api, sucursal, "0")
    turno = api.get("/api/caja/turnos/actual").json()["turno"]
    assert api.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                    json={"monto_declarado": "0"}).status_code == 200
    assert api.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                    json={"monto_declarado": "0"}).status_code == 409


def test_nadie_cierra_la_caja_de_otro(api, engine, abrir_caja, sucursal):
    """🔴 Un operador cerrándole la caja a otro deja un arqueo con el nombre
    equivocado: el que contó la plata no es el que figura."""
    abrir_caja(api, sucursal, "1000")
    turno = api.get("/api/caja/turnos/actual").json()["turno"]

    api.post("/api/usuarios", json={
        "username": "otro", "name": "Otro", "password": "clave-otro", "role": "staff"})
    otro = TestClient(crear_app(_config(_url_core())), base_url="https://testserver")
    assert otro.post(
        "/auth/login", json={"username": "otro", "password": "clave-otro"}
    ).status_code == 200

    assert otro.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                     json={"monto_declarado": "1000"}).status_code == 403
    # Control: el dueño sí puede.
    assert api.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                    json={"monto_declarado": "1000"}).status_code == 200


def _staff(api, usuario: str, clave: str):
    """Un encargado con sesion propia. Devuelve su cliente."""
    r = api.post("/api/usuarios", json={
        "username": usuario, "name": usuario.title(), "password": clave, "role": "staff"})
    assert r.status_code in (200, 201), r.text
    cliente = TestClient(crear_app(_config(_url_core())), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": usuario, "password": clave}
    ).status_code == 200, "no se pudo iniciar sesion como el encargado"
    return cliente


def test_el_historial_le_muestra_a_cada_uno_LO_SUYO(api, sucursal, abrir_caja):
    """🔴 Este test asertaba `403` para un encargado, y cambio porque cambio la
    conducta ---no porque se ablando---.

    Hasta el 2026-08-29 el historial era `require_admin`, o sea que la pantalla
    **no existia** para el encargado del mostrador, que es justamente quien
    quiere saber cuanto cerro ayer. Ahora la ve, y lo que NO puede ver son los
    cierres ajenos.

    Lo que se pide ahora es mas fuerte que lo de antes: no alcanza con que
    conteste 200, tiene que traer **exactamente** los turnos propios. Un
    endpoint que devolviera lista vacia siempre pasaria un test que solo mire
    que no aparezcan los ajenos.
    """
    # El admin abre y cierra un turno.
    abrir_caja(api, sucursal, "1000")
    del_admin = api.get("/api/caja/turnos/actual").json()["turno"]
    api.post(f"/api/caja/turnos/{del_admin['id']}/cerrar", json={"monto_declarado": "1000"})

    # Y el encargado abre el suyo.
    staff = _staff(api, "mostrador2", "clave-most")
    caja_id = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()[0]["id"]
    r = staff.post("/api/caja/turnos", json={"monto_inicial": "500", "caja_id": caja_id})
    assert r.status_code == 201, r.text
    del_staff = r.json()

    mios = staff.get("/api/caja/turnos")
    assert mios.status_code == 200, mios.text
    ids_del_staff = [t["id"] for t in mios.json()]
    # El positivo: SI ve el suyo. Sin esto, una lista siempre vacia pasaria.
    assert del_staff["id"] in ids_del_staff, "el encargado no ve su propio turno"
    # Y el negativo: NO ve el del admin.
    assert del_admin["id"] not in ids_del_staff, (
        "el encargado esta viendo el cierre de otro"
    )

    # El admin, en cambio, ve los dos.
    ids_del_admin = [t["id"] for t in api.get("/api/caja/turnos").json()]
    assert del_admin["id"] in ids_del_admin and del_staff["id"] in ids_del_admin


def test_el_historial_dice_QUIEN_abrio_cada_turno(api, sucursal, abrir_caja):
    """El motor devuelve `usuario_nombre` en todas sus consultas de turnos y
    esto lo descartaba. Sin el, el historial de un admin es una lista de cierres
    sin dueno --- y la columna que mas importa de esa pantalla es justamente la
    del cajero."""
    abrir_caja(api, sucursal, "1000")
    turnos = api.get("/api/caja/turnos").json()
    assert turnos, "no hay turnos que mirar"
    assert turnos[0]["usuario_nombre"], (
        f"el turno salio sin nombre de cajero: {turnos[0]}"
    )


def test_el_limite_del_historial_esta_acotado(api):
    """Sin cota, un `?limite=100000` es un pedido que el motor atiende."""
    assert api.get("/api/caja/turnos?limite=100000").status_code == 422
    assert api.get("/api/caja/turnos?limite=0").status_code == 422
    # El control: un limite razonable si pasa, o el test de arriba estaria
    # midiendo que el endpoint rechaza todo.
    assert api.get("/api/caja/turnos?limite=10").status_code == 200


# -- El detalle de un turno -------------------------------------------------


def test_el_detalle_trae_el_turno_Y_SU_ARQUEO(api, sucursal, abrir_caja):
    """Es a donde lleva el historial, y la forma es la misma que `/turnos/actual`.

    Dos formas distintas para el mismo par serian dos formateos que mantener, y
    el dia que una cambie la otra queda diciendo otra cosa.
    """
    abrir_caja(api, sucursal, "1000")
    turno = api.get("/api/caja/turnos/actual").json()["turno"]
    api.post("/api/caja/cobros", json={
        "monto": "2500", "concepto": "Cancha 1", "medio_pago": "efectivo"})

    r = api.get(f"/api/caja/turnos/{turno['id']}")
    assert r.status_code == 200, r.text
    datos = r.json()
    assert set(datos) == {"turno", "resumen"}, datos
    assert datos["turno"]["id"] == turno["id"]
    # El arqueo tiene que traer la plata que entro, no venir vacio.
    assert datos["resumen"]["pagos_por_medio"].get("efectivo") == 2500.0, (
        f"el resumen no trae el cobro: {datos['resumen']}"
    )
    assert any(m["concepto"] == "Cancha 1" for m in datos["resumen"]["movimientos"])


def test_NADIE_MIRA_EL_ARQUEO_DE_OTRO(api, sucursal, abrir_caja):
    """🔴 Un arqueo dice cuanta plata conto una persona y cuanto le falto.

    No es un dato que cualquier encargado tenga por que ver del turno de otro.
    Mismo criterio que el cierre, que ya lo hacia.
    """
    abrir_caja(api, sucursal, "1000")
    del_admin = api.get("/api/caja/turnos/actual").json()["turno"]

    staff = _staff(api, "mostrador4", "clave-m4")
    ajeno = staff.get(f"/api/caja/turnos/{del_admin['id']}")
    assert ajeno.status_code == 403, ajeno.text

    # Los dos controles: el dueno si puede...
    assert api.get(f"/api/caja/turnos/{del_admin['id']}").status_code == 200
    # ...y el encargado si puede ver EL SUYO, o sea que el 403 de arriba es por
    # ser ajeno y no porque el endpoint le este cerrado a los encargados.
    caja_id = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()[0]["id"]
    suyo = staff.post(
        "/api/caja/turnos", json={"monto_inicial": "0", "caja_id": caja_id}
    ).json()
    assert staff.get(f"/api/caja/turnos/{suyo['id']}").status_code == 200


def test_un_turno_que_no_existe_da_404(api):
    assert api.get("/api/caja/turnos/999999").status_code == 404


def test_el_detalle_NO_SE_COME_la_ruta_del_turno_abierto(api, sucursal, abrir_caja):
    """🔴 `/turnos/actual` y `/turnos/{id}` tienen la misma forma.

    Lo unico que las separa es que el convertidor de FastAPI no matchea
    `actual` contra un entero. Si alguna vez ese parametro pasa a `str`, la caja
    abierta deja de responder ---y el sintoma seria un 422 en la pantalla del
    mostrador, no en el detalle---.
    """
    abrir_caja(api, sucursal, "1000")
    r = api.get("/api/caja/turnos/actual")
    assert r.status_code == 200, r.text
    assert r.json()["turno"]["estado"] == "abierto"


# ── Con qué se puede cobrar ───────────────────────────────────────────────

def test_los_medios_de_pago_salen_del_backend(api):
    """🔴 El frontend tenía su propia lista, con un comentario que decía que
    *"tiene que coincidir con  del backend — si se agrega uno de un
    lado y no del otro, el cobro da 422"*. O sea que la divergencia estaba
    **prevista y aceptada** en vez de cerrada. Y ya había ocurrido: las dos
    decían , que no existe en el vocabulario de la familia.

    Ahora la pide acá. El resto del vocabulario lo cubre .
    """
    from app.servicios import caja as servicio

    r = api.get("/api/caja/medios-pago")
    assert r.status_code == 200, r.text
    assert [m["valor"] for m in r.json()] == list(servicio.MEDIOS_PAGO)
    assert all(m["etiqueta"] for m in r.json()), (
        "una etiqueta vacía deja una opción en blanco que igual se puede elegir"
    )


def test_los_medios_de_pago_son_de_staff(api):
    """El mostrador los necesita para cobrar; no es información de admin."""
    api.post("/api/usuarios", json={
        "username": "mostrador3", "name": "Mostrador", "password": "clave-m3", "role": "staff"})
    staff = TestClient(crear_app(_config(_url_core())), base_url="https://testserver")
    staff.post("/auth/login", json={"username": "mostrador3", "password": "clave-m3"})
    assert staff.get("/api/caja/medios-pago").status_code == 200
