"""`GET /api/resumen`: lo que esta sucursal le contesta al panel del dueño.

El endpoint lo arma la factory de LibraCore y el bloque de comercio lo trae
LibraCommerce; los dos motores tienen sus tests. Lo que se fija acá:

- la **puerta**: entra con `LIBRA_PANEL_TOKEN`, no con sesión de usuario ni con
  el token de servicio del producto;
- el bloque **agenda**, que nace en este producto: reservas, ocupación,
  canceladas y ausentes;
- que la **ocupación** salga del horario de atención real y no de un supuesto;
- que una instancia sin base de LibraCore **no monte el endpoint**, en vez de
  contestar ceros.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app
from app.models.enums import AlcanceDia, EstadoReserva
from app.models.maestros import FranjaDeAtencion
from app.tiempo import TZ

USUARIO, CLAVE = "admin", "clave-de-prueba"
TOKEN = "token-de-panel-de-prueba"

#: Un martes, dentro del horario que siembran los tests.
DIA = date(2026, 9, 8)


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
    monkeypatch.setenv("LIBRA_PANEL_TOKEN", TOKEN)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(crear_app(_config(base_de_libracore)), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


def _resumen(api, **params):
    p = {"desde": DIA.isoformat(), "hasta": DIA.isoformat(), **params}
    return api.get("/api/resumen", params=p, headers={"X-Panel-Auth": TOKEN})


def _franja(sesion, sucursal, abre, cierra, cancha=None):
    f = FranjaDeAtencion(
        sucursal_id=sucursal.id,
        cancha_id=cancha.id if cancha else None,
        alcance_dia=AlcanceDia.TODOS,
        abre=abre,
        cierra=cierra,
    )
    sesion.add(f)
    sesion.commit()
    return f


def _reservar(api, cancha, cliente, hora, minutos=90, precio="8000.00"):
    inicio = datetime.combine(DIA, hora, tzinfo=TZ)
    r = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": cliente.id,
        "comienza_at": inicio.isoformat(), "duracion_min": minutos, "precio": precio})
    assert r.status_code == 201, r.text
    return r.json()


# ── La puerta ────────────────────────────────────────────────────────────


def _anonimo() -> TestClient:
    """Un cliente SIN sesión.

    🔴 El fixture `api` está logueado como admin, y el guard es
    `require_panel_o_admin`: con esa sesión entra por la otra puerta. Probar la
    credencial del panel con ese cliente daría verde con el guard entero sacado.
    """
    return TestClient(crear_app(_config(_url_core())), base_url="https://testserver")


def test_sin_credencial_no_se_lee_el_resumen(api, sucursal):
    """🔴 Con control positivo: un 401 solo no dice de qué ruta vino.

    En los tests **no hay `frontend/dist`**, así que el catch-all de la SPA no
    se monta y una ruta inexistente da 404. En producción esa misma ruta daría
    200 con HTML — por eso el control va acá y no se da por sabido.
    """
    sin_token = _anonimo().get("/api/resumen")
    assert sin_token.status_code == 401, sin_token.text
    assert "json" in sin_token.headers["content-type"]

    inventada = _anonimo().get("/api/no-existe-esta-ruta")
    assert inventada.status_code == 404, "control: la ruta que no existe da 404, no 401"


def test_el_token_equivocado_tampoco_entra(api, sucursal):
    r = _anonimo().get("/api/resumen", headers={"X-Panel-Auth": "otro-token"})
    assert r.status_code == 401, r.text


def test_la_sesion_de_admin_TAMBIEN_entra(api, sucursal):
    """El guard es `panel_o_admin`: el superadmin lo puede mirar sin el token.
    Es lo que permitió verificar el endpoint antes de que la credencial
    existiera — y también lo que escondió, en Contalibra, que la variable no
    estaba puesta en ninguna instancia."""
    assert api.get("/api/resumen").status_code == 200


def test_con_la_credencial_del_panel_contesta(api, sucursal):
    r = _resumen(api)
    assert r.status_code == 200, r.text
    assert set(r.json()) >= {"instancia", "periodo", "nucleo", "comercio", "agenda"}


def test_el_punto_de_venta_sale_de_la_SUCURSAL(api, sucursal):
    """🔑 En este producto el PV es una columna de `sucursales`, no de la config
    de ARCA: la numeración de ARCA es por `(tipo, punto_venta)` y no lleva CUIT,
    así que dos sucursales del mismo CUIT necesitan PV distintos."""
    assert _resumen(api).json()["instancia"]["punto_venta"] == sucursal.punto_venta_arca


# ── El bloque agenda ─────────────────────────────────────────────────────


def test_las_reservas_del_periodo_se_cuentan_con_su_monto(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    _franja(sesion, sucursal, time(9, 0), time(23, 0))
    _reservar(api, cancha, cliente, time(20, 0))
    _reservar(api, cancha, cliente, time(10, 0))

    agenda = _resumen(api).json()["agenda"]
    assert agenda["reservas"]["cantidad"] == 2
    assert agenda["reservas"]["monto"] == 16000.0
    assert agenda["horas_vendidas"] == 3.0


def test_la_ocupacion_sale_del_HORARIO_REAL_y_no_de_un_supuesto(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """🔴 El número por el que un dueño mira este panel, y el que hasta ayer no
    se podía calcular.

    Con el horario hardcodeado en 8:00–00:00, un complejo que abre 4 horas
    habría informado una ocupación **ocho veces menor** que la real. Acá: abre
    de 20 a 24 (4 h × 1 cancha) y vende 1,5 h → 37,5%.
    """
    _franja(sesion, sucursal, time(20, 0), time(0, 0))
    _reservar(api, cancha, cliente, time(20, 0))

    agenda = _resumen(api).json()["agenda"]
    assert agenda["horas_disponibles"] == 4.0, "de 20 a 24, una cancha"
    assert agenda["horas_vendidas"] == 1.5
    assert agenda["ocupacion_pct"] == 37.5


def test_achicar_el_horario_SUBE_la_ocupacion(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """Control del test de arriba: si el denominador fuera fijo, la ocupación no
    se movería al cambiar el horario, y aquél pasaría igual con el bug."""
    franja = _franja(sesion, sucursal, time(8, 0), time(0, 0))
    _reservar(api, cancha, cliente, time(20, 0))
    antes = _resumen(api).json()["agenda"]

    franja.abre = time(20, 0)
    sesion.commit()
    despues = _resumen(api).json()["agenda"]

    assert despues["horas_disponibles"] < antes["horas_disponibles"]
    assert despues["ocupacion_pct"] > antes["ocupacion_pct"], (
        f"{antes['ocupacion_pct']} -> {despues['ocupacion_pct']}"
    )


def test_una_cancha_dada_de_baja_no_infla_el_denominador(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """Meterla bajaría la ocupación de todas las demás sin que nadie entienda
    por qué: no está disponible para vender."""
    from app.models.maestros import Cancha

    _franja(sesion, sucursal, time(20, 0), time(0, 0))
    baja = Cancha(sucursal_id=sucursal.id, nombre="Cancha 9", activa=False)
    sesion.add(baja)
    sesion.commit()

    assert _resumen(api).json()["agenda"]["horas_disponibles"] == 4.0, "una sola cancha"


def test_un_dia_cerrado_deja_la_ocupacion_en_NULL_y_no_en_cero(
    api, sesion, sucursal, cancha, feriado_cerrado
):
    """🔑 `null` y no `0`. Dividir por cero rompería, y mandar 0 diría "no
    vendieron nada" cuando lo cierto es "no hubo nada que vender"."""
    r = api.get(
        "/api/resumen",
        params={"desde": feriado_cerrado.dia.isoformat(),
                "hasta": feriado_cerrado.dia.isoformat()},
        headers={"X-Panel-Auth": TOKEN},
    )
    agenda = r.json()["agenda"]
    assert agenda["horas_disponibles"] == 0.0
    assert agenda["ocupacion_pct"] is None


def test_canceladas_y_ausentes_se_cuentan_APARTE(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """🔑 Miden cosas distintas: cancelar avisa y libera la cancha a tiempo, no
    venir la quema. El ausente además **entra** en lo vendido, porque se cobra.
    """
    _franja(sesion, sucursal, time(9, 0), time(23, 0))
    cancelada = _reservar(api, cancha, cliente, time(10, 0))
    ausente = _reservar(api, cancha, cliente, time(20, 0))
    api.post(f"/api/reservas/{cancelada['id']}/estado",
             json={"estado": "cancelada", "motivo": "El cliente avisó"})
    api.post(f"/api/reservas/{ausente['id']}/estado", json={"estado": "ausente"})

    agenda = _resumen(api).json()["agenda"]
    assert agenda["canceladas"] == 1
    assert agenda["ausentes"] == 1
    # La cancelada no se vendió; la ausente sí, y por eso el monto es de una sola.
    assert agenda["reservas"]["cantidad"] == 1
    assert agenda["reservas"]["monto"] == 8000.0


def test_un_bloqueo_no_es_una_venta(api, sesion, sucursal, cancha):
    """No es una reserva: es la cancha sacada de circulación."""
    _franja(sesion, sucursal, time(9, 0), time(23, 0))
    inicio = datetime.combine(DIA, time(11, 0), tzinfo=TZ)
    r = api.post("/api/reservas/bloqueos", json={
        "cancha_id": cancha.id, "comienza_at": inicio.isoformat(),
        "termina_at": (inicio + timedelta(hours=2)).isoformat(),
        "motivo": "Mantenimiento"})
    assert r.status_code == 201, r.text

    agenda = _resumen(api).json()["agenda"]
    assert agenda["reservas"]["cantidad"] == 0
    assert agenda["horas_vendidas"] == 0.0


def test_el_rango_es_en_hora_LOCAL_e_inclusivo(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """🔴 La reserva de las 22:00 del día 8 es del día 8, no del 9.

    Tomando el rango como instantes UTC, la frontera se corre tres horas y las
    reservas de las últimas noches del mes se van al mes siguiente. Con
    `desde == hasta` el día tiene que entrar entero.
    """
    _franja(sesion, sucursal, time(9, 0), time(0, 0))
    _reservar(api, cancha, cliente, time(22, 0), minutos=60)

    del_dia = _resumen(api).json()["agenda"]
    assert del_dia["reservas"]["cantidad"] == 1, "las 22:00 del día 8 son del día 8"

    siguiente = (DIA + timedelta(days=1)).isoformat()
    del_otro = api.get("/api/resumen", params={"desde": siguiente, "hasta": siguiente},
                       headers={"X-Panel-Auth": TOKEN}).json()["agenda"]
    assert del_otro["reservas"]["cantidad"] == 0, "y no del 9"


# ── El bloque comercio, y la instancia que no puede informar ─────────────


def test_el_buffet_entra_en_el_bloque_comercio(api, sucursal):
    r = _resumen(api).json()
    assert set(r["comercio"]) == {"ventas", "stock_bajo_minimo"}
    assert r["comercio"]["ventas"]["cantidad"] == 0


def test_sin_base_de_libracore_el_endpoint_NO_se_monta(engine, sesion, monkeypatch):
    """🔑 404 y no ceros.

    Sin esa base no hay núcleo —facturado, cobrado, caja—, que es lo único que
    la factory manda siempre. Contestar el endpoint con ceros le diría al panel
    "esta sucursal no vendió nada"; no montarlo le dice "esta sucursal no
    informa", que es lo cierto y además distinguible.
    """
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    monkeypatch.setenv("LIBRA_PANEL_TOKEN", TOKEN)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    sin_core = TestClient(crear_app(_config(None)), base_url="https://testserver")
    try:
        r = sin_core.get("/api/resumen", headers={"X-Panel-Auth": TOKEN})
        # 404: la ruta no existe. Con el endpoint montado sería 200 y un JSON
        # con `nucleo` en ceros, que es justo lo que no tiene que pasar.
        assert r.status_code == 404, (
            f"el endpoint se montó igual: {r.status_code} {r.text[:120]}"
        )
    finally:
        AuthBase.metadata.drop_all(engine)


@pytest.fixture
def feriado_cerrado(sesion, sucursal):
    from app.models.maestros import Feriado

    item = Feriado(
        sucursal_id=sucursal.id, dia=date(2026, 12, 25), nombre="Navidad", cerrado=True
    )
    sesion.add(item)
    sesion.commit()
    return item


def test_una_fecha_que_no_es_fecha_da_422(api, sucursal):
    r = api.get("/api/resumen", params={"desde": "ayer", "hasta": DIA.isoformat()},
                headers={"X-Panel-Auth": TOKEN})
    assert r.status_code == 422, r.text


def test_desde_posterior_a_hasta_da_422(api, sucursal):
    r = api.get("/api/resumen",
                params={"desde": DIA.isoformat(), "hasta": (DIA - timedelta(days=1)).isoformat()},
                headers={"X-Panel-Auth": TOKEN})
    assert r.status_code == 422, r.text


def test_sin_rango_toma_el_mes_en_curso(api, sucursal):
    r = api.get("/api/resumen", headers={"X-Panel-Auth": TOKEN}).json()
    hoy = date.today()
    assert r["periodo"]["desde"] == hoy.replace(day=1).isoformat()
    assert r["periodo"]["hasta"] == hoy.isoformat()


def test_el_estado_ausente_existe_en_el_enum():
    """Guard del supuesto de `VENDIDAS`: si alguien renombra el estado, el
    bloque agenda dejaría de contar los ausentes en silencio."""
    assert EstadoReserva.AUSENTE.value == "ausente"
