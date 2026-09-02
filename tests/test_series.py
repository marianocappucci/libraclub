"""Las canchas fijas por la API: listado, extensión y baja.

`materializar_serie` ya tiene sus tests en `test_reservas.py` y
`test_horarios.py`. Lo que se fija acá es lo que la pantalla necesita y que
hasta el 2026-08-21 no existía:

- que el listado diga **hasta cuándo está materializada**, que es lo que evita
  que una cancha fija se apague sola a los 90 días sin que nadie se entere;
- que **extender** genere lo que falta sin duplicar lo que ya está;
- que **dar de baja** cancele las reservas futuras, y **sólo** las futuras.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app
from app.models.enums import AlcanceDia, EstadoReserva
from app.models.maestros import FranjaDeAtencion
from app.models.reservas import Reserva
from app.tiempo import ahora

USUARIO, CLAVE = "admin", "clave-de-prueba"


def _config() -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos", libracore_database_url=None,
    )


@pytest.fixture
def api(engine, sesion, monkeypatch):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(crear_app(_config()), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)



def _abierto(sesion, sucursal):
    """El complejo abre todo el día: acá no se prueba el horario."""
    sesion.add(FranjaDeAtencion(
        sucursal_id=sucursal.id, alcance_dia=AlcanceDia.TODOS,
        abre=time(0, 0), cierra=time(0, 0),
    ))
    sesion.commit()


def _crear_serie(api, cancha, cliente, *, desde=None, hasta=None, hora="20:00:00"):
    """Una cancha fija de los martes, desde el próximo martes."""
    desde = desde or _proximo_martes()
    cuerpo = {
        "cancha_id": cancha.id, "cliente_id": cliente.id, "dia_semana": 1,
        "hora": hora, "duracion_min": 60, "desde": desde.isoformat(),
    }
    if hasta is not None:
        cuerpo["hasta"] = hasta.isoformat()
    r = api.post("/api/reservas/series", json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


def _proximo_martes() -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() != 1:
        d += timedelta(days=1)
    return d


# ── El listado ───────────────────────────────────────────────────────────


def test_el_listado_dice_hasta_cuando_esta_materializada(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """🔴 El campo que evita que una cancha fija se apague sola.

    Una serie sin fin no genera reservas infinitas: se materializa una ventana
    de 90 días. Sin este dato, esa ventana se agota y el grupo de los martes
    llega y encuentra el turno libre para cualquiera — sin que nada haya
    fallado, y sin nada que mirar para darse cuenta.
    """
    _abierto(sesion, sucursal)
    creada = _crear_serie(api, cancha, cliente)
    assert len(creada["creadas"]) >= 10, "la ventana son 90 días de martes"

    fila = api.get("/api/reservas/series/listado").json()[0]
    assert fila["materializada_hasta"] is not None
    # Dentro de la ventana de 90 días, no más allá.
    hasta = date.fromisoformat(fila["materializada_hasta"])
    assert date.today() < hasta <= date.today() + timedelta(days=91), hasta
    assert fila["proximas"] == len(creada["creadas"])


def test_el_listado_trae_los_NOMBRES_y_no_los_ids(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """La tabla guarda ids y el operador busca por nombre."""
    _abierto(sesion, sucursal)
    _crear_serie(api, cancha, cliente)
    fila = api.get("/api/reservas/series/listado").json()[0]
    assert fila["cliente"] == cliente.nombre
    assert fila["cancha"] == cancha.nombre


def test_una_serie_sin_ninguna_reserva_no_miente_con_una_fecha(
    api, sesion, sucursal, cancha, cliente
):
    """Sin tarifa no se crea ninguna ocurrencia: `materializada_hasta` va
    `null`, no la fecha de hoy ni la de `desde`. Es lo que le dice al operador
    que esa serie **no está funcionando**."""
    _abierto(sesion, sucursal)
    creada = _crear_serie(api, cancha, cliente)
    assert creada["creadas"] == [], "sin tarifa no entra ninguna"

    fila = api.get("/api/reservas/series/listado").json()[0]
    assert fila["materializada_hasta"] is None
    assert fila["proximas"] == 0


# ── Extender ─────────────────────────────────────────────────────────────


def test_extender_genera_lo_que_falta(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    _abierto(sesion, sucursal)
    creada = _crear_serie(api, cancha, cliente)
    antes = date.fromisoformat(
        api.get("/api/reservas/series/listado").json()[0]["materializada_hasta"]
    )

    tope = date.today() + timedelta(days=150)
    r = api.post(
        f"/api/reservas/series/{creada['serie']['id']}/extender?hasta={tope.isoformat()}"
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["creadas"]) > 0, "tiene que generar los martes que faltaban"

    despues = date.fromisoformat(
        api.get("/api/reservas/series/listado").json()[0]["materializada_hasta"]
    )
    assert despues > antes, f"{antes} -> {despues}"


def test_extender_dos_veces_no_duplica(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """🔑 Las que ya existen chocan consigo mismas y salen como `ocupada`.

    Sin esto, cada click en «Extender» volvería a intentar las mismas fechas y
    el constraint de exclusión las rechazaría una por una — que es lo correcto,
    pero hay que verificar que **se reporten** y no que se dupliquen.
    """
    _abierto(sesion, sucursal)
    creada = _crear_serie(api, cancha, cliente)
    tope = (date.today() + timedelta(days=150)).isoformat()
    sid = creada["serie"]["id"]

    api.post(f"/api/reservas/series/{sid}/extender?hasta={tope}")
    total_antes = api.get("/api/reservas/series/listado").json()[0]["proximas"]

    segunda = api.post(f"/api/reservas/series/{sid}/extender?hasta={tope}")
    assert segunda.json()["creadas"] == [], "no hay nada nuevo que crear"
    assert {x["motivo"] for x in segunda.json()["salteadas"]} == {"ocupada"}

    total_despues = api.get("/api/reservas/series/listado").json()[0]["proximas"]
    assert total_despues == total_antes, "no se duplicó ninguna"


def test_una_serie_dada_de_baja_no_se_extiende(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    _abierto(sesion, sucursal)
    creada = _crear_serie(api, cancha, cliente)
    sid = creada["serie"]["id"]
    api.post(f"/api/reservas/series/{sid}/baja", json={"cancelar_futuras": False})

    r = api.post(f"/api/reservas/series/{sid}/extender")
    assert r.status_code == 409, r.text


# ── La baja ──────────────────────────────────────────────────────────────


def test_la_baja_cancela_las_futuras(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """🔴 Desactivar la serie NO borra sus reservas, y ése es el punto.

    Las ocurrencias materializadas son filas de `reservas` como cualquier otra:
    sin cancelarlas, el grupo que dejó de venir sigue ocupando la cancha todos
    los martes hasta que se agote la ventana, y esos turnos no se pueden vender.
    """
    _abierto(sesion, sucursal)
    creada = _crear_serie(api, cancha, cliente)
    sid = creada["serie"]["id"]
    cuantas = len(creada["creadas"])
    assert cuantas > 0

    r = api.post(f"/api/reservas/series/{sid}/baja",
                 json={"cancelar_futuras": True, "motivo": "El grupo dejó de venir"})
    assert r.status_code == 200, r.text
    assert r.json()["canceladas"] == cuantas

    fila = api.get("/api/reservas/series/listado").json()[0]
    assert fila["activa"] is False
    assert fila["proximas"] == 0, "no queda ninguna ocupando la cancha"


def test_la_baja_SIN_cancelar_deja_las_reservas(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """Control de la de arriba: si la baja cancelara siempre, aquélla pasaría
    igual con el flag ignorado."""
    _abierto(sesion, sucursal)
    creada = _crear_serie(api, cancha, cliente)
    sid = creada["serie"]["id"]

    r = api.post(f"/api/reservas/series/{sid}/baja", json={"cancelar_futuras": False})
    assert r.json()["canceladas"] == 0

    fila = api.get("/api/reservas/series/listado").json()[0]
    assert fila["activa"] is False
    assert fila["proximas"] == len(creada["creadas"]), "las reservas siguen ahí"


def test_la_baja_NO_toca_las_pasadas(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """🔴 Las pasadas son historia: se jugaron, se cobraron, están en la caja y
    en las facturas. Cancelarlas reescribiría el pasado.

    La serie arranca hace un mes, así que tiene ocurrencias de los dos lados.
    """
    _abierto(sesion, sucursal)
    hace_un_mes = date.today() - timedelta(days=30)
    while hace_un_mes.weekday() != 1:
        hace_un_mes += timedelta(days=1)
    creada = _crear_serie(api, cancha, cliente, desde=hace_un_mes)

    pasadas = [
        r for r in creada["creadas"]
        if date.fromisoformat(r["comienza_at"][:10]) < date.today()
    ]
    assert pasadas, "el escenario necesita ocurrencias pasadas"

    sid = creada["serie"]["id"]
    api.post(f"/api/reservas/series/{sid}/baja", json={"cancelar_futuras": True})

    for r in pasadas:
        reserva = sesion.get(Reserva, r["id"])
        sesion.refresh(reserva)
        assert reserva.estado is not EstadoReserva.CANCELADA, (
            f"se canceló una reserva del {reserva.comienza_at:%d-%m-%Y}, que ya pasó"
        )


def test_dar_de_baja_una_serie_que_no_existe_da_404(api):
    assert api.post("/api/reservas/series/9999/baja", json={}).status_code == 404


def test_la_serie_dada_de_baja_sigue_en_el_listado(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """No se borra: el historial de quién tenía la cancha fija de los martes es
    justamente lo que se consulta cuando el grupo vuelve a pedirla."""
    _abierto(sesion, sucursal)
    creada = _crear_serie(api, cancha, cliente)
    api.post(f"/api/reservas/series/{creada['serie']['id']}/baja", json={})
    assert len(api.get("/api/reservas/series/listado").json()) == 1


def test_el_listado_vacio_no_rompe(api):
    """Sin series, el listado no puede reventar en la consulta de agregados."""
    assert api.get("/api/reservas/series/listado").json() == []


def test_proximas_cuenta_solo_las_FUTURAS(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """🔑 Es lo que se le muestra al operador antes de dar de baja.

    Contando también las pasadas, la pregunta diría "se van a cancelar 17
    turnos" cuando los que se cancelan son 13 — y el operador decidiría sobre un
    número que incluye lo que ya se jugó y se cobró.

    Verificado mutando el filtro: sin él, `proximas` da el total y el resto de
    los tests pasa igual, porque todos usan series que arrancan en el futuro.
    """
    _abierto(sesion, sucursal)
    hace_un_mes = date.today() - timedelta(days=30)
    while hace_un_mes.weekday() != 1:
        hace_un_mes += timedelta(days=1)
    creada = _crear_serie(api, cancha, cliente, desde=hace_un_mes)

    # 🔴 Se compara con la MISMA granularidad que el endpoint. Él cuenta
    # `comienza_at >= ahora()` —un instante— y acá se restaba con
    # `< date.today()`, un día entero.
    #
    # La ocurrencia de HOY a las 20:00, cuando ya pasaron las 20:00, no caía en
    # ninguno de los dos lados: su fecha no es menor que hoy, así que no entraba
    # en `pasadas`, y su instante ya pasó, así que el endpoint no la cuenta en
    # `proximas`. De ahí el off-by-one — y sólo los martes después de las 20:00,
    # que es como se puso rojo el 2026-09-01 por la noche sin que nadie tocara
    # nada.
    corte = ahora()
    pasadas = [
        r for r in creada["creadas"]
        if datetime.fromisoformat(r["comienza_at"]) < corte
    ]
    assert pasadas, "el escenario necesita ocurrencias de los dos lados"

    fila = api.get("/api/reservas/series/listado").json()[0]
    assert fila["proximas"] == len(creada["creadas"]) - len(pasadas)
    assert fila["proximas"] < len(creada["creadas"]), "si contara todas, serían iguales"


def test_la_baja_cancela_exactamente_las_que_el_listado_anuncio(
    api, sesion, sucursal, cancha, cliente, tarifa_base
):
    """El número que la pantalla muestra en la pregunta tiene que ser el que
    después se cancela. Si difirieran, la confirmación mentiría."""
    _abierto(sesion, sucursal)
    hace_un_mes = date.today() - timedelta(days=30)
    while hace_un_mes.weekday() != 1:
        hace_un_mes += timedelta(days=1)
    creada = _crear_serie(api, cancha, cliente, desde=hace_un_mes)

    anunciadas = api.get("/api/reservas/series/listado").json()[0]["proximas"]
    r = api.post(f"/api/reservas/series/{creada['serie']['id']}/baja",
                 json={"cancelar_futuras": True})
    assert r.json()["canceladas"] == anunciadas
