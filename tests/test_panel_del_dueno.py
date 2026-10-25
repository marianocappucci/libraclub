# ruff: noqa: F811  -- las fixtures importadas se piden por nombre en cada test
"""El panel del dueño (F5, ADR-027): ocupación por franja, ingresos, cancelaciones y ausentes, por sucursal.

Se mide por los dos caminos que lo exponen, que tienen que dar lo mismo:

- `GET /api/admin/panel-del-dueno`, la pantalla de LibraClub (sesión de admin);
- la clave `club` de `GET /api/resumen`, que lee `libra-panel` (credencial del panel).

Datos ficticios. Las reservas se insertan directo en la base —con la fecha, el estado y el origen que cada test
necesita— y no por la API: lo que se mide es el cálculo, no el alta. Los cobros entran por la misma función del
motor que usa la caja (`create_caja_movimiento`), con las referencias reales (`reserva-<id>-…`, `lc-<id>-…`).

El reloj del negocio se fija en `AHORA` (jueves 10 de septiembre de 2026 a mediodía): lo que ya se jugó y lo que
no, que decide si un cobro es de `reservas` o de `senas`, no puede depender del día en que corra el CI.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from libracore.db import caja as db_caja

from app.config import Config
from app.main import crear_app
from app.models.enums import AlcanceDia, EstadoReserva, OrigenReserva
from app.models.maestros import Cancha, Cliente, Feriado, FranjaDeAtencion, Sucursal
from app.models.reservas import Reserva
from app.servicios import facturacion, panel_del_dueno
from app.tiempo import TZ
from tests.conftest import url_del_core
from tests.test_buffet import _reponer, gaseosa  # noqa: F401  (fixtures y helpers)
from tests.test_buffet_registrar_venta import _consumir

USUARIO, CLAVE = "admin", "clave-de-prueba"
TOKEN = "token-de-panel-de-prueba"

#: El "ahora" de los tests: jueves 10-09-2026 al mediodía.
AHORA = datetime(2026, 9, 10, 12, 0, tzinfo=TZ)
#: El período de casi todos los tests: lunes 7 a domingo 13 de septiembre. Siete días justos, así que cada
#: celda (día de la semana, hora) aparece exactamente una vez. El anterior es el 31-08 al 06-09.
DESDE, HASTA = date(2026, 9, 7), date(2026, 9, 13)
LUNES, MARTES = date(2026, 9, 7), date(2026, 9, 8)
#: Un turno ya jugado del período, otro que todavía no, y uno del período anterior.
JUGADO = date(2026, 9, 8)
FUTURO = date(2026, 9, 12)
ANTERIOR = date(2026, 9, 2)


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
    monkeypatch.setattr(panel_del_dueno, "ahora", lambda: AHORA)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    cliente = TestClient(crear_app(_config(base_de_libracore)), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


def _panel(api, desde=DESDE, hasta=HASTA, **filtros):
    r = api.get("/api/admin/panel-del-dueno", params={
        "desde": desde.isoformat(), "hasta": hasta.isoformat(), **filtros})
    assert r.status_code == 200, r.text
    return r.json()


def _sucursal_del(panel, sucursal):
    (fila,) = [s for s in panel["por_sucursal"] if s["sucursal_id"] == sucursal.id]
    return fila


# ── Datos ────────────────────────────────────────────────────────────────


def _abrir(sesion, sucursal, abre, cierra, cancha=None):
    sesion.add(FranjaDeAtencion(
        sucursal_id=sucursal.id, cancha_id=cancha.id if cancha else None,
        alcance_dia=AlcanceDia.TODOS, abre=abre, cierra=cierra))
    sesion.commit()


def _turno(
    sesion, cancha, cliente, dia, hora, *, minutos=90, estado=EstadoReserva.CONFIRMADA,
    origen=OrigenReserva.MOSTRADOR, precio="8000.00",
):
    inicio = datetime.combine(dia, hora, tzinfo=TZ)
    item = Reserva(
        cancha_id=cancha.id, cliente_id=cliente.id if cliente else None, estado=estado, origen=origen,
        comienza_at=inicio, termina_at=inicio + timedelta(minutes=minutos),
        precio=Decimal(precio) if precio is not None else None,
    )
    sesion.add(item)
    sesion.commit()
    return item


def _cobro(referencia, monto, dia=JUGADO, tipo="ingreso"):
    db_caja.create_caja_movimiento(dia.isoformat(), tipo, "cobro de prueba", Decimal(str(monto)), referencia=referencia)


def _cobro_de(reserva, monto, sufijo="a1", dia=JUGADO):
    _cobro(f"reserva-{reserva.id}-{sufijo}", monto, dia)


@pytest.fixture
def norte(sesion):
    """Una segunda sucursal con una cancha, para que las filas no sean una."""
    suc = Sucursal(nombre="Complejo Norte", punto_venta_arca=2)
    sesion.add(suc)
    sesion.commit()
    cancha = Cancha(sucursal_id=suc.id, nombre="Cancha Norte 1")
    sesion.add(cancha)
    sesion.commit()
    return suc, cancha


# ── Ocupación por franja ─────────────────────────────────────────────────


def test_las_franjas_salen_del_horario_real_y_lo_cerrado_no_cuenta(
    api, sesion, sucursal, cancha, cliente
):
    """🔴 El número que el dueño mira. Abre de 18 a 22: las 10 de la mañana no son horas abiertas.

    Una reserva cargada fuera de horario (la puede dejar un admin) no cuenta como vendida en la franja —no hay
    horas abiertas a las que dividir— y, sobre todo, no hace que ninguna celda pase de 100 %.
    """
    _abrir(sesion, sucursal, time(18, 0), time(22, 0))
    _turno(sesion, cancha, cliente, MARTES, time(18, 0))
    _turno(sesion, cancha, cliente, MARTES, time(10, 0))

    fila = _sucursal_del(_panel(api, MARTES, MARTES), sucursal)

    martes = {f["hora"]: f["ocupacion_pct"] for f in fila["franjas"] if f["dia"] == 1}
    assert martes == {18: 100.0, 19: 50.0, 20: 0.0, 21: 0.0}, "sólo las horas abiertas, y la de las 10 no figura"
    assert fila["horas_abiertas"] == 4.0
    assert fila["horas_reservadas"] == 1.5, "las 10 de la mañana quedan afuera del numerador"
    assert fila["ocupacion_pct"] == 37.5


def test_un_dia_sin_horario_abierto_no_tiene_franjas_y_la_ocupacion_es_NULL(
    api, sesion, sucursal, cancha
):
    """`null` y no `0`: «cerrado» no es «no vendió». Mismo criterio que el bloque `agenda`."""
    sesion.add(Feriado(sucursal_id=sucursal.id, dia=MARTES, nombre="Cerrado por obra", cerrado=True))
    sesion.commit()

    fila = _sucursal_del(_panel(api, MARTES, MARTES), sucursal)

    assert fila["franjas"] == []
    assert fila["ocupacion_pct"] is None
    assert fila["horas_abiertas"] == 0.0


def test_una_franja_que_cruza_la_medianoche_cae_en_el_dia_en_que_realmente_transcurre(
    api, sesion, sucursal, cancha, cliente
):
    """Abre a las 20 y cierra a las 02: las 00:30 del miércoles son miércoles aunque el horario sea el del martes."""
    _abrir(sesion, sucursal, time(20, 0), time(2, 0))
    _turno(sesion, cancha, cliente, MARTES, time(23, 30), minutos=60)  # 23:30 a 00:30

    fila = _sucursal_del(_panel(api, MARTES, MARTES + timedelta(days=1)), sucursal)

    celdas = {(f["dia"], f["hora"]): f["ocupacion_pct"] for f in fila["franjas"]}
    assert celdas[(1, 23)] == 50.0, "los primeros 30 minutos, el martes a las 23"
    assert celdas[(2, 0)] == 50.0, "los últimos 30 minutos, el miércoles a las 00"
    # La ventana es [martes 00:00, jueves 00:00): las 2 h del lunes que caen el martes, las 6 h del martes y las
    # 4 h del miércoles que no se pasan de la medianoche del jueves. Las 2 h de la madrugada del jueves, afuera.
    assert fila["horas_abiertas"] == 12.0
    assert fila["horas_reservadas"] == 1.0
    assert (3, 1) not in celdas, "el jueves a la 01 queda afuera del período"
    assert (1, 1) in celdas, "pero la franja que abrió el lunes y sigue el martes a la 01, adentro"


def test_una_cancha_dada_de_baja_no_cuenta_como_horas_abiertas(api, sesion, sucursal, cancha):
    _abrir(sesion, sucursal, time(20, 0), time(0, 0))
    sesion.add(Cancha(sucursal_id=sucursal.id, nombre="Cancha 9", activa=False))
    sesion.commit()

    assert _sucursal_del(_panel(api, MARTES, MARTES), sucursal)["horas_abiertas"] == 4.0, "una sola cancha"


def test_dos_reservas_de_la_misma_hora_no_pasan_del_cien_por_ciento(api, sesion, sucursal, cancha, cliente):
    """Un ausente no ocupa la cancha (ADR-006) y otra reserva puede quedar encima: la hora no se cuenta dos veces."""
    _abrir(sesion, sucursal, time(20, 0), time(22, 0))
    _turno(sesion, cancha, cliente, MARTES, time(20, 0), minutos=60, estado=EstadoReserva.AUSENTE)
    _turno(sesion, cancha, cliente, MARTES, time(20, 0), minutos=60)

    fila = _sucursal_del(_panel(api, MARTES, MARTES), sucursal)

    assert {f["hora"]: f["ocupacion_pct"] for f in fila["franjas"]} == {20: 100.0, 21: 0.0}


def test_la_cancha_filtra_las_franjas_y_la_ocupacion(api, sesion, sucursal, cancha, cliente):
    otra = Cancha(sucursal_id=sucursal.id, nombre="Cancha 2")
    sesion.add(otra)
    sesion.commit()
    _abrir(sesion, sucursal, time(20, 0), time(22, 0))
    _turno(sesion, cancha, cliente, MARTES, time(20, 0), minutos=120)

    todas = _sucursal_del(_panel(api, MARTES, MARTES), sucursal)
    primera = _sucursal_del(_panel(api, MARTES, MARTES, cancha_id=cancha.id), sucursal)
    segunda = _sucursal_del(_panel(api, MARTES, MARTES, cancha_id=otra.id), sucursal)

    assert todas["ocupacion_pct"] == 50.0, "dos canchas abiertas y una llena"
    assert primera["ocupacion_pct"] == 100.0
    assert segunda["ocupacion_pct"] == 0.0
    # Lo que no es de la cancha no se filtra: el buffet ni tiene cancha, y las reservas son del complejo.
    assert primera["reservas"] == segunda["reservas"] == 1


def test_el_total_pondera_las_sucursales_por_sus_horas(api, sesion, sucursal, cancha, cliente, norte):
    """El 100 % de una cancha no pesa como el 0 % de cuatro: el consolidado sale de las horas y no del promedio."""
    suc_norte, cancha_norte = norte
    otras = [Cancha(sucursal_id=suc_norte.id, nombre=f"Cancha Norte {n}") for n in (2, 3, 4)]
    sesion.add_all(otras)
    sesion.commit()
    _abrir(sesion, sucursal, time(20, 0), time(22, 0))
    _abrir(sesion, suc_norte, time(20, 0), time(22, 0))
    _turno(sesion, cancha, cliente, MARTES, time(20, 0), minutos=120)  # centro: 2 de 2 h

    panel = _panel(api, MARTES, MARTES)

    assert _sucursal_del(panel, sucursal)["ocupacion_pct"] == 100.0
    assert _sucursal_del(panel, suc_norte)["ocupacion_pct"] == 0.0
    # 2 h reservadas de 10 abiertas (2 + 4 × 2), y no el 50 % del promedio.
    assert panel["total"]["ocupacion_pct"] == 20.0
    assert {f["hora"]: f["ocupacion_pct"] for f in panel["total"]["franjas"]} == {20: 20.0, 21: 20.0}


# ── Dos sucursales, dos filas ────────────────────────────────────────────


def test_dos_sucursales_dan_dos_filas_y_el_filtro_deja_una(api, sesion, sucursal, cancha, cliente, norte):
    """El gate de la F5: el dueño ve sus sucursales una por una, no aplastadas en una."""
    suc_norte, cancha_norte = norte
    _turno(sesion, cancha, cliente, MARTES, time(20, 0))
    _turno(sesion, cancha_norte, cliente, MARTES, time(20, 0))
    _turno(sesion, cancha_norte, cliente, MARTES, time(22, 0))

    panel = _panel(api, MARTES, MARTES)

    assert [(s["sucursal"], s["reservas"]) for s in panel["por_sucursal"]] == [
        ("Complejo Centro", 1), ("Complejo Norte", 2)]
    assert [s["sucursal"] for s in _panel(api, MARTES, MARTES, sucursal_id=suc_norte.id)["por_sucursal"]] == [
        "Complejo Norte"]


def test_una_sucursal_sin_actividad_sale_igual_en_cero(api, sucursal, cancha, norte):
    """Un cero y un ausente no son lo mismo: la sucursal que no vendió tiene que verse para compararla."""
    panel = _panel(api, MARTES, MARTES)

    assert len(panel["por_sucursal"]) == 2
    for fila in panel["por_sucursal"]:
        assert fila["reservas"] == fila["canceladas"] == fila["ausentes"] == 0
        assert fila["ingresos"]["total"] == 0.0


def test_una_sucursal_dada_de_baja_sale_si_vendio_en_el_periodo_y_si_no_no(
    api, sesion, sucursal, cancha, cliente, norte
):
    suc_norte, cancha_norte = norte
    suc_norte.activa = False
    sesion.commit()

    assert [s["sucursal"] for s in _panel(api, MARTES, MARTES)["por_sucursal"]] == ["Complejo Centro"]

    _turno(sesion, cancha_norte, cliente, MARTES, time(20, 0))
    assert [s["sucursal"] for s in _panel(api, MARTES, MARTES)["por_sucursal"]] == [
        "Complejo Centro", "Complejo Norte"]


# ── Cancelaciones, ausentes y origen ─────────────────────────────────────


def test_canceladas_y_ausentes_se_cuentan_aparte_y_el_ausente_cuenta_como_vendido(
    api, sesion, sucursal, cancha, cliente
):
    _turno(sesion, cancha, cliente, MARTES, time(10, 0), estado=EstadoReserva.CANCELADA)
    _turno(sesion, cancha, cliente, MARTES, time(12, 0), estado=EstadoReserva.CANCELADA)
    _turno(sesion, cancha, cliente, MARTES, time(14, 0), estado=EstadoReserva.AUSENTE)
    _turno(sesion, cancha, cliente, MARTES, time(16, 0), estado=EstadoReserva.JUGADA)

    fila = _sucursal_del(_panel(api, MARTES, MARTES), sucursal)

    assert (fila["canceladas"], fila["ausentes"], fila["reservas"]) == (2, 1, 2)


def test_un_bloqueo_y_una_reserva_en_conflicto_no_son_reservas(api, sesion, sucursal, cancha, cliente):
    _turno(sesion, cancha, None, MARTES, time(10, 0), estado=EstadoReserva.BLOQUEO, precio=None)
    _turno(sesion, cancha, cliente, MARTES, time(12, 0), estado=EstadoReserva.EN_CONFLICTO)

    fila = _sucursal_del(_panel(api, MARTES, MARTES), sucursal)

    assert (fila["reservas"], fila["canceladas"], fila["ausentes"]) == (0, 0, 0)
    assert sum(fila["origen"].values()) == 0


def test_el_top_de_ausentes_ordena_por_cantidad_y_corta_en_diez(api, sesion, sucursal, cancha):
    # 12 clientes: el 1 falta 3 veces, el 2 falta 2, y los otros 10 una sola vez. Un día, una cancha: se reparten
    # en los días del período para no pisarse.
    clientes = [Cliente(nombre=f"Jugador {n:02d}") for n in range(1, 13)]
    sesion.add_all(clientes)
    sesion.commit()
    faltas = {0: 3, 1: 2, **{n: 1 for n in range(2, 12)}}
    dia, hora = DESDE, 8
    for indice, veces in faltas.items():
        for _ in range(veces):
            _turno(sesion, cancha, clientes[indice], dia, time(hora, 0), minutos=60, estado=EstadoReserva.AUSENTE)
            hora += 1
            if hora > 22:
                dia, hora = dia + timedelta(days=1), 8

    top = _panel(api)["top_ausentes"]

    assert len(top) == 10
    assert top[0] == {"cliente_id": clientes[0].id, "nombre": "Jugador 01", "ausentes": 3}
    assert top[1] == {"cliente_id": clientes[1].id, "nombre": "Jugador 02", "ausentes": 2}
    assert [t["ausentes"] for t in top[2:]] == [1] * 8
    assert [t["nombre"] for t in top[2:]] == sorted(t["nombre"] for t in top[2:]), "los empates, por nombre"


def test_el_top_de_ausentes_respeta_la_sucursal_y_el_periodo(api, sesion, sucursal, cancha, cliente, norte):
    suc_norte, cancha_norte = norte
    otro = Cliente(nombre="Otro Jugador")
    sesion.add(otro)
    sesion.commit()
    _turno(sesion, cancha, cliente, MARTES, time(10, 0), estado=EstadoReserva.AUSENTE)
    _turno(sesion, cancha_norte, otro, MARTES, time(10, 0), estado=EstadoReserva.AUSENTE)
    _turno(sesion, cancha, otro, ANTERIOR, time(10, 0), estado=EstadoReserva.AUSENTE)

    assert {t["nombre"] for t in _panel(api)["top_ausentes"]} == {"Juan Pérez", "Otro Jugador"}
    assert [t["nombre"] for t in _panel(api, sucursal_id=sucursal.id)["top_ausentes"]] == ["Juan Pérez"]
    assert _panel(api, sucursal_id=sucursal.id)["top_ausentes"][0]["ausentes"] == 1, "el de ANTERIOR no entra"


def test_el_origen_trae_todas_las_claves_del_enum_y_suma_las_reservas(api, sesion, sucursal, cancha, cliente):
    """Las claves son los valores del enum en minúscula, siempre todas (en cero las que no hubo), y suman `reservas`."""
    _turno(sesion, cancha, cliente, MARTES, time(10, 0), origen=OrigenReserva.PORTAL)
    _turno(sesion, cancha, cliente, MARTES, time(12, 0), origen=OrigenReserva.PORTAL)
    _turno(sesion, cancha, cliente, MARTES, time(14, 0), origen=OrigenReserva.WHATSAPP, estado=EstadoReserva.AUSENTE)
    _turno(sesion, cancha, cliente, MARTES, time(16, 0), origen=OrigenReserva.SERIE)
    # Una cancelada no es una reserva vendida: no se cuenta en el origen (como no se cuenta en `reservas`).
    _turno(sesion, cancha, cliente, MARTES, time(18, 0), origen=OrigenReserva.TELEFONO, estado=EstadoReserva.CANCELADA)

    fila = _sucursal_del(_panel(api, MARTES, MARTES), sucursal)

    assert fila["origen"] == {"mostrador": 0, "telefono": 0, "whatsapp": 1, "portal": 2, "serie": 1}
    assert set(fila["origen"]) == {o.value for o in OrigenReserva}
    assert sum(fila["origen"].values()) == fila["reservas"] == 4


# ── Ingresos ─────────────────────────────────────────────────────────────


def test_los_ingresos_son_lo_cobrado_de_los_turnos_jugados_y_se_comparan_con_el_periodo_anterior(
    api, sesion, sucursal, cancha, cliente
):
    """`reservas` = cobrado de turnos jugados; el anterior es el período de igual largo inmediatamente antes."""
    ahora = _turno(sesion, cancha, cliente, JUGADO, time(18, 0), estado=EstadoReserva.JUGADA)
    antes = _turno(sesion, cancha, cliente, ANTERIOR, time(18, 0), estado=EstadoReserva.JUGADA)
    _cobro_de(ahora, 8000)
    _cobro_de(antes, 6000, dia=ANTERIOR)

    ingresos = _sucursal_del(_panel(api), sucursal)["ingresos"]

    assert ingresos == {
        "reservas": 8000.0, "senas": 0.0, "buffet": 0.0, "total": 8000.0, "total_periodo_anterior": 6000.0}


def test_un_turno_sin_cobrar_no_es_un_ingreso(api, sesion, sucursal, cancha, cliente):
    _turno(sesion, cancha, cliente, JUGADO, time(18, 0), estado=EstadoReserva.JUGADA)

    assert _sucursal_del(_panel(api), sucursal)["ingresos"]["total"] == 0.0


def test_lo_cobrado_de_un_turno_que_todavia_no_se_jugo_es_sena_y_lo_cancelado_se_netea_con_la_devolucion(
    api, sesion, sucursal, cancha, cliente
):
    """`senas` = plata a cuenta de lo que falta jugar y lo retenido de lo cancelado, neto de lo devuelto."""
    futuro = _turno(sesion, cancha, cliente, FUTURO, time(18, 0), estado=EstadoReserva.PENDIENTE_PAGO)
    retenida = _turno(sesion, cancha, cliente, JUGADO, time(10, 0), estado=EstadoReserva.CANCELADA)
    devuelta = _turno(sesion, cancha, cliente, JUGADO, time(12, 0), estado=EstadoReserva.CANCELADA)
    _cobro_de(futuro, 4000)
    _cobro_de(retenida, 4000)
    _cobro(f"lc-{devuelta.id}-ab12cd", 4000)
    _cobro(f"devolucion-lc-{devuelta.id}-ab12cd", 4000, tipo="egreso")

    ingresos = _sucursal_del(_panel(api), sucursal)["ingresos"]

    assert ingresos["senas"] == 8000.0, "la del turno futuro y la retenida; la devuelta vale cero"
    assert ingresos["reservas"] == 0.0
    assert ingresos["total"] == 8000.0


def test_lo_cobrado_de_mas_sobre_el_precio_son_consumos_y_no_se_cuenta_dos_veces(
    api, sesion, sucursal, cancha, cliente
):
    """El cliente pagó 11.000 contra un turno de 8.000: los 3.000 son buffet, que ya está en `buffet`."""
    turno = _turno(sesion, cancha, cliente, JUGADO, time(18, 0), estado=EstadoReserva.JUGADA, precio="8000.00")
    _cobro_de(turno, 8000, "a1")
    _cobro_de(turno, 3000, "b2")

    assert _sucursal_del(_panel(api), sucursal)["ingresos"]["reservas"] == 8000.0


def test_un_cobro_anulado_o_de_otro_concepto_no_es_un_ingreso_del_turno(api, sesion, sucursal, cancha, cliente):
    turno = _turno(sesion, cancha, cliente, JUGADO, time(18, 0), estado=EstadoReserva.JUGADA)
    _cobro_de(turno, 8000)
    _cobro("lc-buf-99-ab12", 1500)        # un cobro de buffet por QR: no cuelga de ningún turno
    _cobro("factura-7-xx", 9999)          # cualquier otra cosa de la caja
    _filas("UPDATE caja_movimientos SET anulado = 1 WHERE referencia = %s", (f"reserva-{turno.id}-a1",))

    assert _sucursal_del(_panel(api), sucursal)["ingresos"]["total"] == 0.0


def _filas(sql: str, params: tuple = ()):
    with psycopg.connect(url_del_core(), autocommit=True) as con:
        cur = con.execute(sql, params)
        return cur.fetchall() if cur.description else []


def test_el_buffet_es_lo_vendido_en_la_sucursal_y_el_periodo(
    api, sesion, sucursal, cancha, cliente, norte, gaseosa, abrir_caja
):
    """Venta confirmada por la fecha de negocio de la venta, abierta por sucursal; la de otro período va al anterior."""
    suc_norte, _ = norte
    abrir_caja(api, sucursal, "0")
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    venta = _consumir(api, sucursal, gaseosa["item_id"], 2)       # 2.400, del complejo Centro
    vieja = _consumir(api, sucursal, gaseosa["item_id"], 1)       # 1.200, la corro al período anterior
    _filas("UPDATE sales SET occurred_on = %s WHERE id = %s", (MARTES.isoformat(), venta["id"]))
    _filas("UPDATE sales SET occurred_on = %s WHERE id = %s", (ANTERIOR.isoformat(), vieja["id"]))

    panel = _panel(api)

    centro = _sucursal_del(panel, sucursal)["ingresos"]
    assert (centro["buffet"], centro["total"], centro["total_periodo_anterior"]) == (2400.0, 2400.0, 1200.0)
    assert _sucursal_del(panel, suc_norte)["ingresos"]["buffet"] == 0.0


def test_el_total_suma_reservas_senas_y_buffet(api, sesion, sucursal, cancha, cliente, gaseosa, abrir_caja):
    jugado = _turno(sesion, cancha, cliente, JUGADO, time(18, 0), estado=EstadoReserva.JUGADA)
    futuro = _turno(sesion, cancha, cliente, FUTURO, time(18, 0))
    _cobro_de(jugado, 8000)
    _cobro_de(futuro, 4000)
    abrir_caja(api, sucursal, "0")
    _reponer(api, sucursal, gaseosa["item_id"], 24)
    venta = _consumir(api, sucursal, gaseosa["item_id"], 1)
    _filas("UPDATE sales SET occurred_on = %s WHERE id = %s", (MARTES.isoformat(), venta["id"]))

    assert _sucursal_del(_panel(api), sucursal)["ingresos"] == {
        "reservas": 8000.0, "senas": 4000.0, "buffet": 1200.0, "total": 13200.0, "total_periodo_anterior": 0.0}


def test_sin_la_base_de_libracore_los_ingresos_son_NULL_y_no_cero(api, sesion, sucursal, cancha, monkeypatch):
    """Una instancia que no puede medir la plata no informa cero: informa que no sabe."""
    monkeypatch.setattr(facturacion, "hay_base", lambda: False)

    fila = _sucursal_del(_panel(api), sucursal)

    assert fila["ingresos"] is None
    assert fila["reservas"] == 0, "lo demás sale de la base del dominio y sigue andando"


# ── Los dos caminos ──────────────────────────────────────────────────────


def test_el_resumen_del_panel_trae_la_clave_club_con_la_forma_del_contrato(
    api, sesion, sucursal, cancha, cliente, norte
):
    """`libra-panel` lee `club.por_sucursal` de `/api/resumen`: la forma es la del contrato y no cambia."""
    jugado = _turno(sesion, cancha, cliente, JUGADO, time(18, 0), estado=EstadoReserva.JUGADA)
    _cobro_de(jugado, 8000)

    r = api.get("/api/resumen", params={"desde": DESDE.isoformat(), "hasta": HASTA.isoformat()},
                headers={"X-Panel-Auth": TOKEN})
    assert r.status_code == 200, r.text
    cuerpo = r.json()

    assert set(cuerpo) >= {"instancia", "periodo", "nucleo", "comercio", "agenda", "club"}, "lo anterior sigue"
    club = cuerpo["club"]
    assert (club["desde"], club["hasta"]) == (DESDE.isoformat(), HASTA.isoformat())
    assert [s["sucursal"] for s in club["por_sucursal"]] == ["Complejo Centro", "Complejo Norte"]
    centro = club["por_sucursal"][0]
    assert set(centro) >= {
        "sucursal_id", "sucursal", "ocupacion_pct", "franjas", "ingresos", "canceladas", "ausentes", "reservas",
        "origen"}
    assert set(centro["ingresos"]) == {"reservas", "senas", "buffet", "total", "total_periodo_anterior"}
    assert centro["ingresos"]["total"] == 8000.0
    assert all(set(f) == {"dia", "hora", "ocupacion_pct"} for f in centro["franjas"])
    # Y es el mismo bloque que da la pantalla.
    assert _panel(api)["por_sucursal"] == club["por_sucursal"]


def test_el_resumen_sin_rango_calcula_el_club_con_el_periodo_del_motor(api, sucursal, cancha):
    r = api.get("/api/resumen", headers={"X-Panel-Auth": TOKEN})
    assert r.status_code == 200, r.text
    club = r.json()["club"]
    assert club["desde"] == r.json()["periodo"]["desde"]
    assert club["hasta"] == r.json()["periodo"]["hasta"]


def test_el_resumen_acota_el_periodo_con_un_422_y_no_con_un_500(api, sucursal):
    r = api.get("/api/resumen", params={"desde": "2020-01-01", "hasta": "2026-09-13"},
                headers={"X-Panel-Auth": TOKEN})
    assert r.status_code == 422, r.text


# ── La pantalla: período, filtros y guard ────────────────────────────────


def test_sin_rango_toma_los_ultimos_30_dias_contando_hoy(api, sucursal):
    from app.tiempo import hoy

    r = api.get("/api/admin/panel-del-dueno").json()

    assert r["hasta"] == hoy().isoformat()
    assert r["desde"] == (hoy() - timedelta(days=29)).isoformat()


def test_los_rangos_que_no_se_pueden_calcular_dan_422(api, sucursal):
    ruta = "/api/admin/panel-del-dueno"
    assert api.get(ruta, params={"desde": "2026-09-13", "hasta": "2026-09-07"}).status_code == 422
    assert api.get(ruta, params={"desde": "2025-01-01", "hasta": "2026-09-13"}).status_code == 422
    assert api.get(ruta, params={"desde": "ayer"}).status_code == 422
    # El tope es de 366 días y entra justo: el 13-09-2025 al 13-09-2026 son 366 (el 12-09 ya serían 367).
    assert api.get(ruta, params={"desde": "2025-09-12", "hasta": "2026-09-13"}).status_code == 422
    assert api.get(ruta, params={"desde": "2025-09-13", "hasta": "2026-09-13"}).status_code == 200


def test_una_sucursal_o_una_cancha_que_no_existen_dan_404(api, sucursal, cancha, norte):
    suc_norte, cancha_norte = norte
    ruta = "/api/admin/panel-del-dueno"
    assert api.get(ruta, params={"sucursal_id": 9999}).status_code == 404
    assert api.get(ruta, params={"cancha_id": 9999}).status_code == 404
    # Una cancha que existe pero no es de esa sucursal: tampoco se inventa un cruce.
    assert api.get(ruta, params={"sucursal_id": sucursal.id, "cancha_id": cancha_norte.id}).status_code == 404
    assert api.get(ruta, params={"sucursal_id": suc_norte.id, "cancha_id": cancha_norte.id}).status_code == 200


def test_es_de_admin_y_la_credencial_del_panel_no_lo_abre(api, sucursal):
    """Mismo guard que el resto del admin. La credencial del panel (`LIBRA_PANEL_TOKEN`) sirve para `/api/resumen`
    y para nada más: este endpoint trae nombres de clientes, que el panel multi-instancia no necesita."""
    ruta = "/api/admin/panel-del-dueno"
    anonimo = TestClient(api.app, base_url="https://testserver")
    sin_sesion = anonimo.get(ruta)
    assert sin_sesion.status_code == 401, sin_sesion.text
    con_token = anonimo.get(ruta, headers={"X-Panel-Auth": TOKEN})
    assert con_token.status_code == 401, "la credencial del panel no abre el panel del dueño de la pantalla"
    # Control positivo: la misma credencial SÍ abre el resumen, así que el 401 de arriba es del guard.
    assert anonimo.get("/api/resumen", headers={"X-Panel-Auth": TOKEN}).status_code == 200
    assert api.get(ruta).status_code == 200
