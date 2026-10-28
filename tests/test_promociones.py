"""Promociones y hora valle: el precio rebajado sale del tarifario, no de un segundo cálculo (ADR-029).

Todo se mide con fechas fijas: un test de promociones que use `hoy()` pasa o falla según el día
en que corra el CI. El martes del conftest (`un_martes`) es el 01-09-2026; el lunes, el 31-08.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from sqlalchemy.exc import IntegrityError

from app.config import Config
from app.main import crear_app
from app.models.enums import AlcanceDia, EstadoReserva
from app.models.maestros import Feriado, FranjaDeAtencion
from app.models.reservas import EstadoPago, PagoDeReserva, Reserva, Serie
from app.models.tarifas import Promocion, Tarifa
from app.servicios import disponibilidad, portal, tarifario
from app.servicios import reservas as servicio_reservas
from app.tiempo import TZ, UTC

USUARIO, CLAVE = "admin", "clave-de-prueba"

MARTES = date(2026, 9, 1)
LUNES = date(2026, 8, 31)


def _a_las(dia: date, hora: int, minuto: int = 0) -> datetime:
    return datetime.combine(dia, time(hora, minuto), tzinfo=TZ)


def _promo(sucursal_id: int, **kwargs) -> Promocion:
    base = dict(
        sucursal_id=sucursal_id,
        nombre="Hora valle",
        descuento_porcentaje=20,
        dias_semana=None,
        hora_desde=time(14, 0),
        hora_hasta=time(17, 0),
    )
    base.update(kwargs)
    return Promocion(**base)


@pytest.fixture
def con_promo(sesion, sucursal):
    """Agrega una promoción y la devuelve. La tarifa base es de $10.000 con 50% de seña."""

    def _agregar(**kwargs) -> Promocion:
        item = _promo(sucursal.id, **kwargs)
        sesion.add(item)
        sesion.commit()
        return item

    return _agregar


# ── La cuenta ────────────────────────────────────────────────────────────


def test_sin_promociones_el_precio_es_el_de_siempre(sesion, cancha, tarifa_base):
    """🔴 El control: cargar la tabla no cambia nada para quien no cargó ninguna."""
    cot = tarifario.cotizar(sesion, cancha, _a_las(MARTES, 15))

    assert cot.promocion is None
    assert cot.precio == cot.precio_lista == Decimal("10000.00")
    assert tarifario.precio_y_sena(sesion, cancha, _a_las(MARTES, 15)) == (
        Decimal("10000.00"), Decimal("5000.00"),
    )


def test_la_hora_valle_rebaja_solo_su_franja(sesion, cancha, tarifa_base, con_promo):
    con_promo()

    adentro = tarifario.cotizar(sesion, cancha, _a_las(MARTES, 15))
    afuera = tarifario.cotizar(sesion, cancha, _a_las(MARTES, 18))

    assert adentro.promocion is not None and adentro.promocion.nombre == "Hora valle"
    assert adentro.precio_lista == Decimal("10000.00")
    assert adentro.precio == Decimal("8000.00")
    assert afuera.promocion is None and afuera.precio == Decimal("10000.00")


def test_la_franja_es_semiabierta(sesion, cancha, tarifa_base, con_promo):
    """Las 17:00 ya no son hora valle, igual que dos tarifas contiguas no se pelean el borde."""
    con_promo()

    assert tarifario.cotizar(sesion, cancha, _a_las(MARTES, 14)).precio == Decimal("8000.00")
    assert tarifario.cotizar(sesion, cancha, _a_las(MARTES, 17)).promocion is None


def test_la_franja_se_lee_en_hora_local_no_utc(sesion, cancha, tarifa_base, con_promo):
    """Las 15:00 de Argentina son las 18:00 UTC: leída en UTC caería fuera de la franja de 14 a 17."""
    con_promo()
    en_utc = _a_las(MARTES, 15).astimezone(UTC)

    assert tarifario.cotizar(sesion, cancha, en_utc).promocion is not None


def test_los_dias_de_la_semana(sesion, cancha, tarifa_base, con_promo):
    """Martes a jueves (1, 2, 3): el lunes no y el martes sí."""
    con_promo(dias_semana=[1, 2, 3])

    assert tarifario.cotizar(sesion, cancha, _a_las(MARTES, 15)).promocion is not None
    assert tarifario.cotizar(sesion, cancha, _a_las(LUNES, 15)).promocion is None


def test_la_vigencia_incluye_los_dos_bordes(sesion, cancha, tarifa_base, con_promo):
    con_promo(vigente_desde=date(2026, 9, 1), vigente_hasta=date(2026, 9, 2))

    assert tarifario.cotizar(sesion, cancha, _a_las(date(2026, 8, 31), 15)).promocion is None
    assert tarifario.cotizar(sesion, cancha, _a_las(date(2026, 9, 1), 15)).promocion is not None
    assert tarifario.cotizar(sesion, cancha, _a_las(date(2026, 9, 2), 15)).promocion is not None
    assert tarifario.cotizar(sesion, cancha, _a_las(date(2026, 9, 3), 15)).promocion is None


def test_una_promocion_inactiva_no_aplica(sesion, cancha, tarifa_base, con_promo):
    con_promo(activa=False)

    assert tarifario.cotizar(sesion, cancha, _a_las(MARTES, 15)).promocion is None


def test_en_feriado_no_aplica_salvo_que_lo_pida(sesion, cancha, sucursal, tarifa_base, con_promo):
    """🔴 La hora valle existe porque hay poca demanda, y un feriado no la tiene."""
    sesion.add(Feriado(sucursal_id=sucursal.id, dia=MARTES, nombre="Feriado de prueba"))
    sesion.commit()
    con_promo(nombre="Sólo común")
    con_promo(nombre="También feriados", descuento_porcentaje=10, aplica_en_feriados=True)

    cot = tarifario.cotizar(sesion, cancha, _a_las(MARTES, 15))

    assert cot.promocion.nombre == "También feriados"
    assert cot.precio == Decimal("9000.00")


def test_la_promocion_de_una_cancha_no_toca_a_las_otras(
    sesion, cancha, sucursal, tarifa_base, con_promo
):
    from app.models.enums import Deporte
    from app.models.maestros import Cancha

    otra = Cancha(sucursal_id=sucursal.id, nombre="Cancha 2", deporte=Deporte.PADEL,
                  duracion_turno_min=90)
    sesion.add(otra)
    sesion.commit()
    con_promo(cancha_id=cancha.id)

    assert tarifario.cotizar(sesion, cancha, _a_las(MARTES, 15)).promocion is not None
    assert tarifario.cotizar(sesion, otra, _a_las(MARTES, 15)).promocion is None


def test_gana_la_que_mas_descuenta_y_no_se_suman(sesion, cancha, tarifa_base, con_promo):
    """🔴 Apilar 20% y 30% daría 44%: la cancha regalada sin que nadie lo decida."""
    con_promo(nombre="Chica", descuento_porcentaje=20)
    con_promo(nombre="Grande", descuento_porcentaje=30)

    cot = tarifario.cotizar(sesion, cancha, _a_las(MARTES, 15))

    assert cot.promocion.nombre == "Grande"
    assert cot.precio == Decimal("7000.00")


def test_en_un_empate_gana_la_de_la_cancha(sesion, cancha, tarifa_base, con_promo):
    con_promo(nombre="De toda la sucursal", descuento_porcentaje=20)
    con_promo(nombre="De esta cancha", descuento_porcentaje=20, cancha_id=cancha.id)

    assert tarifario.cotizar(sesion, cancha, _a_las(MARTES, 15)).promocion.nombre == "De esta cancha"


def test_la_sena_sale_del_precio_con_promocion(sesion, cancha, tarifa_base, con_promo):
    """Quien paga menos pone menos de seña: 50% de $8.000, no de $10.000."""
    con_promo()

    precio, sena = tarifario.precio_y_sena(sesion, cancha, _a_las(MARTES, 15))

    assert (precio, sena) == (Decimal("8000.00"), Decimal("4000.00"))


def test_el_descuento_redondea_a_centavos_hacia_arriba(sesion, cancha, sucursal, con_promo):
    """$999,99 con 15% da 849,9915: se cobra 849,99, no 850 ni 849,9."""
    sesion.add(Tarifa(
        sucursal_id=sucursal.id, nombre="Rara", alcance_dia=AlcanceDia.TODOS,
        hora_desde=time(0, 0), hora_hasta=time(23, 59), precio=Decimal("999.99"),
    ))
    sesion.commit()
    con_promo(descuento_porcentaje=15)

    assert tarifario.cotizar(sesion, cancha, _a_las(MARTES, 15)).precio == Decimal("849.99")


def test_la_promocion_gana_sobre_la_tarifa_ganadora_y_no_sobre_otra(
    sesion, cancha, sucursal, tarifa_base, con_promo
):
    """El descuento va sobre la tarifa que **resuelve** (la de mayor prioridad), no sobre la base."""
    sesion.add(Tarifa(
        sucursal_id=sucursal.id, nombre="Nocturna", alcance_dia=AlcanceDia.TODOS,
        hora_desde=time(14, 0), hora_hasta=time(17, 0), precio=Decimal("20000.00"), prioridad=5,
    ))
    sesion.commit()
    con_promo()

    cot = tarifario.cotizar(sesion, cancha, _a_las(MARTES, 15))

    assert cot.precio_lista == Decimal("20000.00")
    assert cot.precio == Decimal("16000.00")


# ── Donde se congela el precio ───────────────────────────────────────────


def test_la_reserva_congela_el_precio_con_promocion(
    sesion, cancha, cliente, tarifa_base, con_promo
):
    """Mostrador, portal y series pasan por `precio_y_sena`: una sola cuenta para todos."""
    con_promo()

    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_a_las(MARTES, 15),
    )

    assert reserva.precio == Decimal("8000.00")
    assert reserva.sena == Decimal("4000.00")


# ── Los turnos fijos no llevan promoción (decisión del humano, 2026-10-28) ─


def test_cotizar_sin_promocion_da_el_precio_de_lista_con_el_mismo_calculo(
    sesion, cancha, tarifa_base, con_promo
):
    """El parámetro apaga sólo el paso de la promoción: la tarifa, el feriado y la seña salen igual."""
    con_promo()
    cuando = _a_las(MARTES, 15)

    con = tarifario.cotizar(sesion, cancha, cuando)
    sin = tarifario.cotizar(sesion, cancha, cuando, con_promocion=False)

    assert con.precio == Decimal("8000.00") and con.promocion is not None
    assert sin.promocion is None
    assert sin.precio == sin.precio_lista == con.precio_lista == Decimal("10000.00")
    assert sin.tarifa.id == con.tarifa.id
    assert sin.sena == Decimal("5000.00"), "la seña sale del precio de lista"
    assert tarifario.precio_y_sena(sesion, cancha, cuando, con_promocion=False) == (
        Decimal("10000.00"), Decimal("5000.00"),
    )


def test_una_serie_cobra_el_precio_de_lista_aunque_haya_hora_valle(
    sesion, cancha, cliente, tarifa_base, con_promo
):
    """🔴 Las ocurrencias de un turno fijo se materializan sin promoción; el mostrador, a la misma hora, sí la lleva."""
    con_promo()  # 20% de 14 a 17
    serie = Serie(
        cancha_id=cancha.id, cliente_id=cliente.id, dia_semana=1, hora=time(15, 0), duracion_min=60,
        desde=MARTES, hasta=MARTES + timedelta(days=14),
    )
    sesion.add(serie)
    sesion.commit()

    creadas, salteadas = servicio_reservas.materializar_serie(sesion, serie)
    sesion.commit()
    suelta = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id,
        comienza_at=_a_las(MARTES + timedelta(days=1), 15),
    )

    assert not salteadas and len(creadas) == 3
    assert [(r.precio, r.sena) for r in creadas] == [(Decimal("10000.00"), Decimal("5000.00"))] * 3
    assert all(r.origen.value == "serie" for r in creadas)
    assert (suelta.precio, suelta.sena) == (Decimal("8000.00"), Decimal("4000.00"))


def test_extender_una_serie_tampoco_lleva_promocion(sesion, cancha, cliente, tarifa_base, con_promo):
    """Extender vuelve a pasar por `materializar_serie`: la regla vale para las ocurrencias de cualquier tanda."""
    con_promo()
    serie = Serie(
        cancha_id=cancha.id, cliente_id=cliente.id, dia_semana=1, hora=time(15, 0), duracion_min=60,
        desde=MARTES, hasta=None,
    )
    sesion.add(serie)
    sesion.commit()

    servicio_reservas.materializar_serie(sesion, serie, hasta=MARTES + timedelta(days=7))
    nuevas, _ = servicio_reservas.materializar_serie(sesion, serie, hasta=MARTES + timedelta(days=21))

    assert nuevas and all(r.precio == Decimal("10000.00") for r in nuevas)


def test_la_api_de_series_materializa_a_precio_de_lista(
    admin, sesion, cancha, cliente, tarifa_base, con_promo, abierto
):
    con_promo()
    r = admin.post("/api/reservas/series", json={
        "cancha_id": cancha.id, "cliente_id": cliente.id, "dia_semana": 1, "hora": "15:00:00",
        "duracion_min": 60, "desde": MARTES.isoformat(), "hasta": (MARTES + timedelta(days=7)).isoformat(),
    })

    assert r.status_code == 201, r.text
    precios = {x.precio for x in sesion.query(Reserva).filter(Reserva.serie_id.is_not(None))}
    assert precios == {Decimal("10000.00")}


def test_el_portal_sigue_reservando_con_la_promocion(sesion, cancha, tarifa_base, con_promo, abierto):
    """El control de lo anterior: sólo las series pierden la promoción; el jugador del portal paga lo que ve."""
    con_promo(hora_desde=time(0, 0), hora_hasta=time(12, 0))
    cuenta = portal.registrar(
        sesion, email="jugador@ejemplo.com", password="una-clave-larga", nombre="Juan Jugador"
    )
    cuando = datetime.combine(_dentro_de(5), time(9, 0), tzinfo=TZ)

    reserva, monto = portal.reservar(sesion, cuenta=cuenta, cancha_id=cancha.id, comienza_at=cuando)

    assert monto == Decimal("8000.00") and reserva.precio == Decimal("8000.00")
    assert portal.turnos_libres(sesion, cancha, _dentro_de(6))[0]["promocion"] is not None


def test_un_precio_manual_no_lleva_promocion(sesion, cancha, cliente, tarifa_base, con_promo):
    """Si el encargado fija el precio a mano, la promoción no se lo toca."""
    con_promo()

    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id,
        comienza_at=_a_las(MARTES, 15), precio=Decimal("12345.00"),
    )

    assert reserva.precio == Decimal("12345.00")


def test_la_grilla_trae_el_precio_de_lista_solo_si_hay_promocion(
    sesion, cancha, tarifa_base, con_promo
):
    con_promo()
    sesion.add(FranjaDeAtencion(
        sucursal_id=cancha.sucursal_id, alcance_dia=AlcanceDia.TODOS,
        abre=time(14, 0), cierra=time(19, 0),
    ))
    sesion.commit()

    turnos = {t.comienza_at.hour: t for t in disponibilidad.grilla_del_dia(sesion, cancha, MARTES)}

    valle, normal = turnos[14], turnos[17]
    assert (valle.precio, valle.precio_lista, valle.promocion) == (
        Decimal("8000.00"), Decimal("10000.00"), "Hora valle",
    )
    assert (normal.precio, normal.precio_lista, normal.promocion) == (
        Decimal("10000.00"), None, None,
    )


# ── La base lo exige también ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "campos",
    [
        {"descuento_porcentaje": 0},
        {"descuento_porcentaje": 100},
        {"dias_semana": []},
        {"dias_semana": [7]},
        {"hora_desde": time(17, 0), "hora_hasta": time(14, 0)},
        {"vigente_desde": date(2026, 9, 10), "vigente_hasta": date(2026, 9, 1)},
    ],
)
def test_la_base_rechaza_una_promocion_imposible(sesion, sucursal, campos):
    sesion.add(_promo(sucursal.id, **campos))

    with pytest.raises(IntegrityError):
        sesion.commit()
    sesion.rollback()


# ── El portal ────────────────────────────────────────────────────────────


def _config() -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos", libracore_database_url=None,
    )


@pytest.fixture
def api(engine, sesion, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    yield TestClient(crear_app(_config()), base_url="https://testserver")
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def admin(api):
    assert api.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    return api


@pytest.fixture
def abierto(sesion, sucursal):
    sesion.add(FranjaDeAtencion(
        sucursal_id=sucursal.id, alcance_dia=AlcanceDia.TODOS, abre=time(0, 0), cierra=time(0, 0),
    ))
    sesion.commit()


def _dentro_de(dias: int) -> date:
    return date.today() + timedelta(days=dias)


def test_el_portal_muestra_el_precio_con_promocion_y_el_de_lista(
    api, sesion, cancha, tarifa_base, abierto, con_promo
):
    """Lo que el jugador ve en `/reservar`: el precio tachado y el rebajado, con el nombre."""
    con_promo(hora_desde=time(0, 0), hora_hasta=time(12, 0), nombre="Mañanas")
    dia = _dentro_de(5)

    r = api.get(f"/api/portal/disponibilidad?cancha_id={cancha.id}&dia={dia.isoformat()}")

    assert r.status_code == 200, r.text
    por_hora = {datetime.fromisoformat(t["comienza_at"]).astimezone(TZ).hour: t for t in r.json()}
    assert por_hora[9]["precio"] == 8000.0
    assert por_hora[9]["precio_lista"] == 10000.0
    assert por_hora[9]["promocion"] == "Mañanas"
    assert por_hora[19]["precio"] == 10000.0
    assert por_hora[19]["precio_lista"] is None and por_hora[19]["promocion"] is None


def test_el_portal_cobra_lo_que_mostro(api, sesion, cancha, tarifa_base, abierto, con_promo):
    """🔴 El precio que se ve tachado es el que se retiene y se cobra: no hay dos cuentas."""
    con_promo(hora_desde=time(0, 0), hora_hasta=time(12, 0))
    r = api.post("/api/portal/registro", json={
        "email": "jugador@ejemplo.com", "password": "una-clave-larga",
        "nombre": "Juan Jugador", "telefono": "111",
    })
    assert r.status_code == 201, r.text
    cuando = datetime.combine(_dentro_de(5), time(9, 0), tzinfo=TZ)

    r = api.post("/api/portal/reservas", json={
        "cancha_id": cancha.id, "comienza_at": cuando.isoformat(),
    })

    assert r.status_code == 201, r.text
    assert r.json()["monto"] == 8000.0
    reserva = sesion.get(Reserva, r.json()["reserva_id"])
    assert reserva.precio == Decimal("8000.00")
    pago = sesion.query(PagoDeReserva).filter_by(reserva_id=reserva.id).one()
    assert pago.monto == Decimal("8000.00") and pago.estado is EstadoPago.PENDIENTE
    assert reserva.estado is EstadoReserva.PROVISORIA


def test_turnos_libres_del_portal_trae_la_promocion(sesion, cancha, tarifa_base, abierto, con_promo):
    con_promo(hora_desde=time(0, 0), hora_hasta=time(12, 0))

    libres = portal.turnos_libres(sesion, cancha, _dentro_de(5))

    con = [t for t in libres if t["promocion"]]
    assert con and all(t["precio"] == Decimal("8000.00") for t in con)


# ── La API de promociones ────────────────────────────────────────────────


def _cuerpo(sucursal_id: int, **kwargs) -> dict:
    base = {
        "sucursal_id": sucursal_id, "nombre": "Hora valle", "descuento_porcentaje": 20,
        "dias_semana": [1, 2, 3], "hora_desde": "14:00", "hora_hasta": "17:00",
    }
    base.update(kwargs)
    return base


def test_el_admin_crea_y_lista_promociones(admin, sucursal):
    r = admin.post("/api/promociones", json=_cuerpo(sucursal.id))

    assert r.status_code == 201, r.text
    creada = r.json()
    assert creada["dias_semana"] == [1, 2, 3] and creada["aplica_en_feriados"] is False
    assert [p["id"] for p in admin.get("/api/promociones").json()] == [creada["id"]]


@pytest.fixture
def mostrador(engine, sesion, monkeypatch):
    """Un cliente logueado como **encargado**: lee, pero no cambia lo que se cobra."""
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    app = crear_app(_config())
    app.state.users.create(username="encargado", name="Encargado", password=CLAVE, role="staff")
    cliente = TestClient(app, base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": "encargado", "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


def test_el_mostrador_lee_pero_no_escribe(mostrador, sucursal):
    """Una promoción cambia lo que se cobra: el alta es de admin, como las tarifas."""
    assert mostrador.get("/api/promociones").status_code == 200
    assert mostrador.post("/api/promociones", json=_cuerpo(sucursal.id)).status_code == 403


@pytest.mark.parametrize(
    "campos",
    [
        {"descuento_porcentaje": 0},
        {"descuento_porcentaje": 100},
        {"dias_semana": []},
        {"dias_semana": [8]},
        {"hora_desde": "17:00", "hora_hasta": "14:00"},
        {"vigente_desde": "2026-09-10", "vigente_hasta": "2026-09-01"},
    ],
)
def test_la_api_rechaza_una_promocion_imposible_con_422(admin, sucursal, campos):
    assert admin.post("/api/promociones", json=_cuerpo(sucursal.id, **campos)).status_code == 422


def test_los_dias_se_guardan_ordenados_y_sin_repetidos(admin, sucursal):
    r = admin.post("/api/promociones", json=_cuerpo(sucursal.id, dias_semana=[3, 1, 1, 2]))

    assert r.status_code == 201, r.text
    assert r.json()["dias_semana"] == [1, 2, 3]


def test_editar_y_borrar(admin, sucursal):
    creada = admin.post("/api/promociones", json=_cuerpo(sucursal.id)).json()

    r = admin.put(
        f"/api/promociones/{creada['id']}",
        json=_cuerpo(sucursal.id, descuento_porcentaje=35, activa=False),
    )
    assert r.status_code == 200 and r.json()["descuento_porcentaje"] == 35
    assert r.json()["activa"] is False
    assert admin.delete(f"/api/promociones/{creada['id']}").status_code == 204
    assert admin.get("/api/promociones").json() == []
