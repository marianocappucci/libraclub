"""«Falta uno»: publicar un partido, sumarse y bajarse.

🔴 **La mitad de estos tests son de privacidad.** El listado lo ve cualquiera con
cuenta: si trajera teléfonos, alcanzaría con registrarse para levantar la agenda
de todos los que juegan en el complejo — y quien la levanta sabe además a qué
hora juega cada uno y en qué cancha.

El resto fija que no se pueda publicar sobre lo que no corresponde: una reserva
provisoria (todavía se puede caer por falta de pago), una pasada, o la de otro.
"""

from __future__ import annotations

import os
import secrets
from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app
from app.models.enums import AlcanceDia
from app.models.maestros import FranjaDeAtencion
from app.models.reservas import Reserva
from app.tiempo import TZ, ahora

USUARIO, CLAVE = "admin", "clave-de-prueba"
PASS = "una-clave-larga"


def _config() -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno="dev", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos", libracore_database_url=None,
    )


@pytest.fixture(autouse=True)
def _secreto(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 40)


@pytest.fixture
def api(engine, sesion, monkeypatch):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    yield TestClient(crear_app(_config()), base_url="https://testserver")
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def abierto(sesion, sucursal):
    sesion.add(FranjaDeAtencion(
        sucursal_id=sucursal.id, alcance_dia=AlcanceDia.TODOS,
        abre=time(0, 0), cierra=time(0, 0)))
    sesion.commit()


def _jugador(nombre="Organizador", telefono="2255-111111"):
    """Un cliente nuevo, logueado. Devuelve su `TestClient`."""
    c = TestClient(crear_app(_config()), base_url="https://testserver")
    mail = f"{secrets.token_hex(4)}@ejemplo.com"
    r = c.post("/api/portal/registro", json={
        "email": mail, "password": PASS, "nombre": nombre, "telefono": telefono})
    assert r.status_code == 201, r.text
    return c


def _turno(dias=3, hora_=20):
    return datetime.combine(date.today() + timedelta(days=dias), time(hora_, 0), tzinfo=TZ)


def _reserva_pagada(cliente, cancha, cuando=None):
    """Una reserva del portal, pagada y confirmada."""
    r = cliente.post("/api/portal/reservas", json={
        "cancha_id": cancha.id, "comienza_at": (cuando or _turno()).isoformat()})
    assert r.status_code == 201, r.text
    creada = r.json()
    assert cliente.post(
        f"/api/portal/pagos/{creada['pago_id']}/simular"
    ).json()["reserva"] == "confirmada"
    return creada


def _publicar(cliente, reserva_id, faltan=2, nota=""):
    return cliente.post(
        f"/api/portal/reservas/{reserva_id}/buscar-jugadores",
        json={"faltan": faltan, "nota": nota})


# ── Publicar ─────────────────────────────────────────────────────────────


def test_publicar_un_partido_de_una_reserva_pagada(api, sesion, cancha, tarifa_base, abierto):
    org = _jugador()
    reserva = _reserva_pagada(org, cancha)
    r = _publicar(org, reserva["reserva_id"], faltan=2, nota="Nivel intermedio")
    assert r.status_code == 201, r.text
    assert r.json()["faltan"] == 2
    assert r.json()["nota"] == "Nivel intermedio"
    assert r.json()["soy_organizador"] is True


def test_NO_se_publica_sobre_una_reserva_provisoria(api, sesion, cancha, tarifa_base, abierto):
    """🔴 Todavía se puede caer por falta de pago: ofrecería lugares en un turno
    que en quince minutos vuelve a estar libre."""
    org = _jugador()
    creada = org.post("/api/portal/reservas", json={
        "cancha_id": cancha.id, "comienza_at": _turno().isoformat()}).json()
    # Sin simular el pago: queda provisoria.
    r = _publicar(org, creada["reserva_id"])
    assert r.status_code == 422, r.text
    assert "confirmado" in r.json()["detail"].lower()


def test_NO_se_publica_sobre_la_reserva_de_OTRO(api, sesion, cancha, tarifa_base, abierto):
    """🔴 Publicaría un partido ajeno, al que después nadie podría entrar."""
    org = _jugador()
    reserva = _reserva_pagada(org, cancha)
    ajeno = _jugador(nombre="Ajeno")

    r = _publicar(ajeno, reserva["reserva_id"])
    assert r.status_code == 422, r.text
    # Mismo mensaje que "no existe": distinguirlos diría cuáles ids existen.
    assert "encontramos" in r.json()["detail"].lower()


def test_NO_se_publica_un_partido_que_ya_paso(api, sesion, cancha, tarifa_base, abierto):
    org = _jugador()
    reserva = _reserva_pagada(org, cancha)
    r = sesion.get(Reserva, reserva["reserva_id"])
    r.comienza_at = ahora() - timedelta(hours=2)
    r.termina_at = ahora() - timedelta(hours=1)
    sesion.commit()

    resp = _publicar(org, reserva["reserva_id"])
    assert resp.status_code == 422, resp.text
    assert "pasó" in resp.json()["detail"]


def test_no_se_publica_dos_veces_el_mismo_partido(api, sesion, cancha, tarifa_base, abierto):
    """🔑 Dos publicaciones serían dos listas de anotados que no se ven entre sí,
    y el organizador terminaría con ocho personas para cuatro lugares."""
    org = _jugador()
    reserva = _reserva_pagada(org, cancha)
    assert _publicar(org, reserva["reserva_id"]).status_code == 201
    segunda = _publicar(org, reserva["reserva_id"])
    assert segunda.status_code == 422, segunda.text


# ── 🔴 Privacidad ────────────────────────────────────────────────────────


def test_el_listado_NO_trae_telefonos_de_nadie(api, sesion, cancha, tarifa_base, abierto):
    """🔴 Con teléfonos, alcanzaría con registrarse para levantar la agenda de
    todos los que juegan en el complejo."""
    org = _jugador(telefono="2255-999999")
    reserva = _reserva_pagada(org, cancha)
    _publicar(org, reserva["reserva_id"])

    curioso = _jugador(nombre="Curioso")
    lista = curioso.get("/api/portal/partidos").json()
    assert len(lista) == 1
    crudo = str(lista)
    assert "2255-999999" not in crudo, "el listado publicó un teléfono"
    assert "telefono" not in lista[0], f"campo de contacto en el listado: {lista[0]}"


def test_un_NO_anotado_no_ve_el_contacto_en_el_detalle(
    api, sesion, cancha, tarifa_base, abierto
):
    """🔴 El detalle es la única función que devuelve teléfonos, y sólo a quien
    juega ahí."""
    org = _jugador(telefono="2255-999999")
    reserva = _reserva_pagada(org, cancha)
    partido = _publicar(org, reserva["reserva_id"]).json()

    curioso = _jugador(nombre="Curioso")
    visto = curioso.get(f"/api/portal/partidos/{partido['id']}").json()
    assert visto["organizador"] == "Organizador", "el nombre sí se ve"
    assert visto["organizador_telefono"] is None, "vio el teléfono sin estar anotado"
    assert "2255-999999" not in str(visto)


def test_al_anotarse_SI_ve_el_contacto(api, sesion, cancha, tarifa_base, abierto):
    """Control del test de arriba: si el contacto no se mostrara nunca, aquél
    pasaría igual y la función sería inútil."""
    org = _jugador(telefono="2255-999999")
    reserva = _reserva_pagada(org, cancha)
    partido = _publicar(org, reserva["reserva_id"]).json()

    invitado = _jugador(nombre="Invitado", telefono="2255-888888")
    antes = invitado.get(f"/api/portal/partidos/{partido['id']}").json()
    assert antes["organizador_telefono"] is None

    r = invitado.post(f"/api/portal/partidos/{partido['id']}/sumarme")
    assert r.status_code == 201, r.text
    assert r.json()["organizador_telefono"] == "2255-999999"

    # Y el organizador ve el del invitado.
    visto = org.get(f"/api/portal/partidos/{partido['id']}").json()
    assert visto["anotados"][0]["telefono"] == "2255-888888"


def test_al_bajarse_DEJA_de_ver_el_contacto(api, sesion, cancha, tarifa_base, abierto):
    """🔑 El permiso se evalúa en cada consulta, no se guarda al anotarse."""
    org = _jugador(telefono="2255-999999")
    reserva = _reserva_pagada(org, cancha)
    partido = _publicar(org, reserva["reserva_id"]).json()

    invitado = _jugador(nombre="Invitado")
    invitado.post(f"/api/portal/partidos/{partido['id']}/sumarme")
    invitado.post(f"/api/portal/partidos/{partido['id']}/bajarme")

    visto = invitado.get(f"/api/portal/partidos/{partido['id']}").json()
    assert visto["organizador_telefono"] is None, "sigue viendo el teléfono tras bajarse"


def test_los_partidos_piden_sesion(api, sesion, cancha, tarifa_base, abierto):
    """Publicar en internet abierto a qué hora juega cada uno y en qué cancha es
    más de lo que hace falta."""
    anonimo = TestClient(crear_app(_config()), base_url="https://testserver")
    assert anonimo.get("/api/portal/partidos").status_code == 401


# ── Sumarse y bajarse ────────────────────────────────────────────────────


def test_sumarse_baja_los_cupos(api, sesion, cancha, tarifa_base, abierto):
    org = _jugador()
    reserva = _reserva_pagada(org, cancha)
    partido = _publicar(org, reserva["reserva_id"], faltan=2).json()

    uno = _jugador(nombre="Uno")
    assert uno.post(f"/api/portal/partidos/{partido['id']}/sumarme").json()["faltan"] == 1
    dos = _jugador(nombre="Dos")
    assert dos.post(f"/api/portal/partidos/{partido['id']}/sumarme").json()["faltan"] == 0


def test_completo_deja_de_ofrecerse_y_no_acepta_mas(api, sesion, cancha, tarifa_base, abierto):
    org = _jugador()
    reserva = _reserva_pagada(org, cancha)
    partido = _publicar(org, reserva["reserva_id"], faltan=1).json()

    uno = _jugador(nombre="Uno")
    uno.post(f"/api/portal/partidos/{partido['id']}/sumarme")

    tarde = _jugador(nombre="Tarde")
    r = tarde.post(f"/api/portal/partidos/{partido['id']}/sumarme")
    assert r.status_code == 409, r.text
    assert tarde.get("/api/portal/partidos").json() == [], "sigue en el listado"


def test_bajarse_libera_el_lugar(api, sesion, cancha, tarifa_base, abierto):
    org = _jugador()
    reserva = _reserva_pagada(org, cancha)
    partido = _publicar(org, reserva["reserva_id"], faltan=1).json()

    uno = _jugador(nombre="Uno")
    uno.post(f"/api/portal/partidos/{partido['id']}/sumarme")
    assert uno.get("/api/portal/partidos").json() == []

    assert uno.post(f"/api/portal/partidos/{partido['id']}/bajarme").json()["faltan"] == 1
    assert len(uno.get("/api/portal/partidos").json()) == 1, "no volvió al listado"


def test_nadie_se_anota_dos_veces(api, sesion, cancha, tarifa_base, abierto):
    """🔑 Dos clicks ocupan dos lugares con la misma persona, y el partido queda
    «completo» con gente que no existe."""
    org = _jugador()
    reserva = _reserva_pagada(org, cancha)
    partido = _publicar(org, reserva["reserva_id"], faltan=3).json()

    uno = _jugador(nombre="Uno")
    assert uno.post(f"/api/portal/partidos/{partido['id']}/sumarme").status_code == 201
    segunda = uno.post(f"/api/portal/partidos/{partido['id']}/sumarme")
    assert segunda.status_code == 409, segunda.text
    assert org.get(f"/api/portal/partidos/{partido['id']}").json()["faltan"] == 2


def test_el_organizador_no_se_anota_a_su_propio_partido(
    api, sesion, cancha, tarifa_base, abierto
):
    org = _jugador()
    reserva = _reserva_pagada(org, cancha)
    partido = _publicar(org, reserva["reserva_id"]).json()
    r = org.post(f"/api/portal/partidos/{partido['id']}/sumarme")
    assert r.status_code == 409, r.text


def test_no_se_suma_a_un_partido_cuya_reserva_se_CANCELO(
    api, sesion, cancha, tarifa_base, abierto
):
    """🔴 Entre que se publica y que alguien se suma pueden pasar días.

    Sumarse a un partido cancelado deja a alguien yendo a una cancha que no está
    reservada.
    """
    org = _jugador()
    reserva = _reserva_pagada(org, cancha)
    partido = _publicar(org, reserva["reserva_id"]).json()
    org.post(f"/api/portal/reservas/{reserva['reserva_id']}/cancelar")

    tarde = _jugador(nombre="Tarde")
    r = tarde.post(f"/api/portal/partidos/{partido['id']}/sumarme")
    assert r.status_code == 409, r.text
    assert tarde.get("/api/portal/partidos").json() == [], "sigue listado tras cancelar"


# ── Cerrar ───────────────────────────────────────────────────────────────


def test_solo_el_organizador_cierra(api, sesion, cancha, tarifa_base, abierto):
    org = _jugador()
    reserva = _reserva_pagada(org, cancha)
    partido = _publicar(org, reserva["reserva_id"]).json()

    ajeno = _jugador(nombre="Ajeno")
    assert ajeno.post(f"/api/portal/partidos/{partido['id']}/cerrar").status_code == 403

    r = org.post(f"/api/portal/partidos/{partido['id']}/cerrar")
    assert r.status_code == 200, r.text
    assert r.json()["abierta"] is False
    assert ajeno.get("/api/portal/partidos").json() == []


def test_cerrado_no_acepta_mas_gente(api, sesion, cancha, tarifa_base, abierto):
    org = _jugador()
    reserva = _reserva_pagada(org, cancha)
    partido = _publicar(org, reserva["reserva_id"]).json()
    org.post(f"/api/portal/partidos/{partido['id']}/cerrar")

    tarde = _jugador(nombre="Tarde")
    assert tarde.post(f"/api/portal/partidos/{partido['id']}/sumarme").status_code == 409


# ── Mis partidos ─────────────────────────────────────────────────────────


def test_mis_partidos_trae_los_mios_con_contacto(api, sesion, cancha, tarifa_base, abierto):
    org = _jugador(telefono="2255-999999")
    reserva = _reserva_pagada(org, cancha)
    partido = _publicar(org, reserva["reserva_id"]).json()

    invitado = _jugador(nombre="Invitado")
    assert invitado.get("/api/portal/partidos/mios").json() == []

    invitado.post(f"/api/portal/partidos/{partido['id']}/sumarme")
    mios = invitado.get("/api/portal/partidos/mios").json()
    assert len(mios) == 1
    assert mios[0]["organizador_telefono"] == "2255-999999", "juega ahí: ve el contacto"
    assert mios[0]["estoy_anotado"] is True


def test_mios_no_lo_agarra_la_ruta_con_parametro(api, sesion, cancha, tarifa_base, abierto):
    """⚠️ `/partidos/mios` va declarada antes que `/partidos/{id}`: al revés,
    `mios` llegaría como id y daría un 422 confuso."""
    jugador = _jugador()
    r = jugador.get("/api/portal/partidos/mios")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)
