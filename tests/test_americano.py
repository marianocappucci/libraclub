"""Campeonatos americanos (ADR-024): zonas de todos contra todos, cómo se juega el
partido, el desempate de la tabla, torneos que terminan en las zonas y eventos con
varias categorías.

Todos los nombres son ficticios.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.models.enums import Deporte, EstadoTorneo, EtapaTorneo, FormatoTorneo
from app.models.torneos import Torneo
from app.servicios import desempate, sets_de_games
from app.servicios import torneos as servicio
from tests.conftest import RAIZ
from tests.test_api import api, api_staff  # noqa: F401  (fixtures)
from tests.test_torneos_api import HOY, _crear, _inscribir, complejo  # noqa: F401  (fixtures)

# ── Helpers ─────────────────────────────────────────────────────────────────


def _torneo(sesion, sucursal, *, nombre="Americano", formato=FormatoTorneo.LIGA, **extra):
    campos = dict(
        sucursal_id=sucursal.id, nombre=nombre, deporte=Deporte.PADEL, formato=formato,
        desde=date(2026, 9, 5), sets_para_ganar=2, games_por_set=6,
    )
    campos.update(extra)
    item = Torneo(**campos)
    sesion.add(item)
    sesion.commit()
    return item


def _con_parejas(sesion, torneo, cuantas):
    for numero in range(1, cuantas + 1):
        servicio.inscribir(sesion, torneo, nombre=f"Pareja {numero}")
    sesion.commit()


def _sortear(sesion, torneo, semilla=7):
    servicio.sortear(sesion, torneo, semilla=semilla)
    sesion.commit()


def _jugar(sesion, torneo, uno: str, otro: str, *parciales: tuple[int, int]):
    """Carga el resultado **desde el punto de vista de `uno`**, sin depender del lado que le tocó."""
    por_nombre = {c.nombre: c.id for c in servicio.competidores_de(sesion, torneo)}
    a, b = por_nombre[uno], por_nombre[otro]
    partido = next(
        p for p in servicio.partidos_de(sesion, torneo)
        if {p.competidor_a_id, p.competidor_b_id} == {a, b}
    )
    derecho = partido.competidor_a_id == a
    servicio.cargar_resultado(
        sesion, partido, list(parciales) if derecho else [(y, x) for x, y in parciales]
    )
    sesion.commit()


def _orden(sesion, torneo, zona=0):
    return [f.nombre for f in servicio.tabla_de_posiciones(sesion, torneo)[zona].filas]


# ── 1. Todos contra todos dentro de cada zona ───────────────────────────────


def test_cada_pareja_juega_una_vez_contra_las_otras_de_su_zona(sesion, sucursal):
    torneo = _torneo(
        sesion, sucursal, formato=FormatoTorneo.ZONAS, cantidad_zonas=2,
        clasifican_por_zona=2,
    )
    _con_parejas(sesion, torneo, 8)
    _sortear(sesion, torneo)

    partidos = servicio.partidos_de(sesion, torneo)
    assert len(partidos) == 12, "dos zonas de cuatro: seis cruces en cada una"
    zona_de = {c.id: c.zona_id for c in servicio.competidores_de(sesion, torneo)}
    cruces = set()
    for partido in partidos:
        assert partido.etapa is EtapaTorneo.GRUPOS
        a, b = partido.competidor_a_id, partido.competidor_b_id
        assert zona_de[a] == zona_de[b] == partido.zona_id, "nadie cruza de zona"
        par = (partido.zona_id, frozenset((a, b)))
        assert par not in cruces, "cada par se juega una sola vez"
        cruces.add(par)
    assert len(cruces) == 12


def test_una_liga_de_seis_parejas_son_quince_cruces(sesion, sucursal):
    torneo = _torneo(sesion, sucursal)
    _con_parejas(sesion, torneo, 6)
    _sortear(sesion, torneo)
    assert len(servicio.partidos_de(sesion, torneo)) == 15


# ── 2. Cómo se juega el partido ─────────────────────────────────────────────


@pytest.mark.parametrize("a,b", [(6, 0), (6, 1), (6, 2), (6, 3), (6, 4), (7, 5), (7, 6)])
def test_un_set_a_6_games_acepta_sus_resultados(a, b):
    assert sets_de_games.marcador_valido(6, a, b)
    assert sets_de_games.marcador_valido(6, b, a), "y al revés, si gana el otro"


@pytest.mark.parametrize("a,b", [(6, 5), (7, 4), (7, 7), (6, 6), (8, 6), (5, 3), (7, 3), (0, 0)])
def test_un_set_a_6_games_rechaza_lo_que_no_termina_asi(a, b):
    assert not sets_de_games.marcador_valido(6, a, b)


@pytest.mark.parametrize("perdedor", range(0, 9))
def test_un_set_a_9_games_acepta_de_9_0_a_9_8(perdedor):
    assert sets_de_games.marcador_valido(9, 9, perdedor)
    assert sets_de_games.marcador_valido(9, perdedor, 9)


@pytest.mark.parametrize("a,b", [(10, 8), (9, 9), (8, 6), (7, 5), (6, 4), (10, 9)])
def test_un_set_a_9_games_rechaza_lo_que_no_termina_asi(a, b):
    """El 10-8 no existe: el tie-break en 8-8 deja el set en 9-8."""
    assert not sets_de_games.marcador_valido(9, a, b)


def _partido(sesion, torneo):
    return servicio.partidos_de(sesion, torneo)[0]


@pytest.mark.parametrize(
    "parciales",
    [[(6, 4)], [(7, 6)], [(3, 6)]],
)
def test_un_set_a_6_se_carga_con_un_solo_parcial_valido(sesion, sucursal, parciales):
    torneo = _torneo(sesion, sucursal, sets_para_ganar=1, games_por_set=6)
    _con_parejas(sesion, torneo, 3)
    _sortear(sesion, torneo)
    partido = servicio.cargar_resultado(sesion, _partido(sesion, torneo), parciales)
    assert partido.finalizado and partido.ganador_id is not None


def test_un_set_a_6_rechaza_un_6_5(sesion, sucursal):
    torneo = _torneo(sesion, sucursal, sets_para_ganar=1, games_por_set=6)
    _con_parejas(sesion, torneo, 3)
    _sortear(sesion, torneo)
    with pytest.raises(servicio.TorneoInvalido, match="6-5.*un set a 6 games"):
        servicio.cargar_resultado(sesion, _partido(sesion, torneo), [(6, 5)])


def test_un_set_a_9_acepta_9_8_y_rechaza_10_8(sesion, sucursal):
    torneo = _torneo(sesion, sucursal, sets_para_ganar=1, games_por_set=9)
    _con_parejas(sesion, torneo, 3)
    _sortear(sesion, torneo)
    partido = _partido(sesion, torneo)
    with pytest.raises(servicio.TorneoInvalido, match="10-8.*un set a 9 games"):
        servicio.cargar_resultado(sesion, partido, [(10, 8)])
    servicio.cargar_resultado(sesion, partido, [(9, 8)])
    assert partido.ganador_id == partido.competidor_a_id


def test_un_set_no_admite_dos_parciales(sesion, sucursal):
    torneo = _torneo(sesion, sucursal, sets_para_ganar=1, games_por_set=6)
    _con_parejas(sesion, torneo, 3)
    _sortear(sesion, torneo)
    with pytest.raises(servicio.TorneoInvalido, match="un solo resultado"):
        servicio.cargar_resultado(sesion, _partido(sesion, torneo), [(6, 4), (6, 3)])


def test_al_mejor_de_3_valida_cada_set(sesion, sucursal):
    torneo = _torneo(sesion, sucursal)
    _con_parejas(sesion, torneo, 3)
    _sortear(sesion, torneo)
    partido = _partido(sesion, torneo)

    servicio.cargar_resultado(sesion, partido, [(6, 4), (3, 6), (7, 6)])
    assert partido.ganador_id == partido.competidor_a_id

    with pytest.raises(servicio.TorneoInvalido, match="El set 2 \\(6-5\\)"):
        servicio.cargar_resultado(sesion, partido, [(6, 4), (6, 5)])


def test_al_mejor_de_3_un_1_1_no_es_un_empate_sino_un_partido_sin_terminar(sesion, sucursal):
    """🔴 Sin esto, `6-4 / 4-6` en una zona se guardaba como empate y le daba un
    punto a cada pareja en un deporte que no tiene empates."""
    torneo = _torneo(sesion, sucursal)
    _con_parejas(sesion, torneo, 3)
    _sortear(sesion, torneo)
    with pytest.raises(servicio.TorneoInvalido, match="set decisivo"):
        servicio.cargar_resultado(sesion, _partido(sesion, torneo), [(6, 4), (4, 6)])


def test_sin_games_por_set_el_marcador_del_set_no_se_controla(sesion, sucursal):
    """Los torneos anteriores y el resto de los deportes siguen como estaban."""
    torneo = _torneo(sesion, sucursal, games_por_set=None)
    _con_parejas(sesion, torneo, 3)
    _sortear(sesion, torneo)
    servicio.cargar_resultado(sesion, _partido(sesion, torneo), [(6, 5), (21, 3)])


def test_el_futbol_no_cambia(sesion, sucursal):
    torneo = _torneo(
        sesion, sucursal, deporte=Deporte.FUTBOL, sets_para_ganar=1, games_por_set=None,
        nombre="Liga de fútbol",
    )
    _con_parejas(sesion, torneo, 3)
    _sortear(sesion, torneo)
    servicio.cargar_resultado(sesion, _partido(sesion, torneo), [(10, 9)])
    servicio.cargar_resultado(sesion, _partido(sesion, torneo), [(2, 2)])  # y el empate vale
    assert _partido(sesion, torneo).ganador_id is None


def test_la_base_no_acepta_games_en_futbol_ni_un_set_a_7(sesion, sucursal):
    with pytest.raises(IntegrityError, match="ck_torneos_games_por_set"):
        _torneo(sesion, sucursal, deporte=Deporte.FUTBOL, sets_para_ganar=1, games_por_set=6)
    sesion.rollback()
    with pytest.raises(IntegrityError, match="ck_torneos_games_por_set"):
        _torneo(sesion, sucursal, nombre="Otro", games_por_set=7)
    sesion.rollback()


# ── 3. El desempate de la zona ──────────────────────────────────────────────


def test_el_cara_a_cara_gana_a_la_diferencia_de_sets(sesion, sucursal):
    """🔑 Dos empatados en partidos ganados: manda el resultado entre ellos, aunque el
    que perdió ese cruce tenga mejor diferencia de sets.

    A y B ganan dos partidos; A le ganó a B (2-1) pero B tiene +3 en sets contra 0 de
    A. Lo mismo C y D con un partido ganado cada una. Sin el cara a cara el orden
    sería B, A, D, C; con él es A, B, C, D.
    """
    torneo = _torneo(sesion, sucursal)
    _con_parejas(sesion, torneo, 4)
    _sortear(sesion, torneo)
    A, B, C, D = (f"Pareja {n}" for n in (1, 2, 3, 4))
    _jugar(sesion, torneo, A, B, (6, 4), (3, 6), (7, 5))    # A gana 2-1
    _jugar(sesion, torneo, A, C, (6, 4), (3, 6), (7, 5))    # A gana 2-1
    _jugar(sesion, torneo, D, A, (6, 0), (6, 0))            # D gana 2-0 (A: 0-2)
    _jugar(sesion, torneo, B, C, (6, 0), (6, 0))            # B gana 2-0
    _jugar(sesion, torneo, B, D, (6, 0), (6, 0))            # B gana 2-0
    _jugar(sesion, torneo, C, D, (6, 4), (3, 6), (7, 5))    # C gana 2-1

    tabla = servicio.tabla_de_posiciones(sesion, torneo)[0]
    por_nombre = {f.nombre: f for f in tabla.filas}
    assert (por_nombre[A].ganados, por_nombre[B].ganados) == (2, 2)
    assert por_nombre[B].diferencia_sets > por_nombre[A].diferencia_sets, "control del escenario"
    assert por_nombre[D].diferencia_sets > por_nombre[C].diferencia_sets, "control del escenario"
    assert _orden(sesion, torneo) == [A, B, C, D]


def test_con_tres_empatados_no_vale_el_cara_a_cara_y_decide_la_diferencia_de_sets():
    """El triángulo (X le ganó a Y, Y a Z y Z a X) no ordena a nadie."""

    class F:
        def __init__(self, id, nombre, dif_sets, dif_games=0, a_favor=0, puntos=3):
            self.competidor_id, self.nombre, self.puntos = id, nombre, puntos
            self.diferencia_sets, self.diferencia, self.a_favor = dif_sets, dif_games, a_favor

    X, Y, Z = F(1, "X", 0), F(2, "Y", 1), F(3, "Z", 2)
    ganadores = {frozenset((1, 2)): 1, frozenset((2, 3)): 2, frozenset((1, 3)): 3}
    orden = desempate.ordenar_zona([X, Y, Z], lambda a, b: ganadores.get(frozenset((a, b))))
    assert [f.nombre for f in orden] == ["Z", "Y", "X"]


def test_la_diferencia_de_games_y_los_games_a_favor_desempatan_en_ese_orden():
    class F:
        def __init__(self, id, nombre, dif_sets, dif_games, a_favor):
            self.competidor_id, self.nombre, self.puntos = id, nombre, 3
            self.diferencia_sets, self.diferencia, self.a_favor = dif_sets, dif_games, a_favor

    sin_cara_a_cara = lambda a, b: None  # noqa: E731
    # Tres empatados en puntos y en sets: manda la diferencia de games.
    filas = [F(1, "A", 0, -2, 20), F(2, "B", 0, 5, 20), F(3, "C", 0, 1, 20)]
    assert [f.nombre for f in desempate.ordenar_zona(filas, sin_cara_a_cara)] == ["B", "C", "A"]
    # Con la misma diferencia de games, manda lo hecho a favor.
    filas = [F(1, "A", 0, 4, 18), F(2, "B", 0, 4, 30), F(3, "C", 0, 4, 24)]
    assert [f.nombre for f in desempate.ordenar_zona(filas, sin_cara_a_cara)] == ["B", "C", "A"]
    # Y con todo igual, el nombre: el orden no se mueve entre consultas.
    filas = [F(3, "C", 0, 4, 24), F(1, "A", 0, 4, 24), F(2, "B", 0, 4, 24)]
    assert [f.nombre for f in desempate.ordenar_zona(filas, sin_cara_a_cara)] == ["A", "B", "C"]


def test_dos_empatados_que_todavia_no_jugaron_entre_ellos_siguen_por_sets(sesion, sucursal):
    torneo = _torneo(sesion, sucursal)
    _con_parejas(sesion, torneo, 4)
    _sortear(sesion, torneo)
    A, B, C, D = (f"Pareja {n}" for n in (1, 2, 3, 4))
    # A y B ganaron un partido cada una, pero no se jugaron entre ellas.
    _jugar(sesion, torneo, A, C, (6, 4), (3, 6), (7, 5))   # A: +1 set
    _jugar(sesion, torneo, B, D, (6, 0), (6, 0))           # B: +2 sets
    tabla = servicio.tabla_de_posiciones(sesion, torneo)[0]
    assert [f.nombre for f in tabla.filas][:2] == [B, A]
    assert tabla.completa is False


def test_la_tabla_de_padel_trae_los_sets_y_la_de_futbol_no(sesion, sucursal):
    padel = _torneo(sesion, sucursal)
    futbol = _torneo(
        sesion, sucursal, nombre="Fútbol", deporte=Deporte.FUTBOL, sets_para_ganar=1,
        games_por_set=None,
    )
    for torneo in (padel, futbol):
        _con_parejas(sesion, torneo, 3)
        _sortear(sesion, torneo)
    _jugar(sesion, padel, "Pareja 1", "Pareja 2", (6, 4), (6, 3))
    _jugar(sesion, futbol, "Pareja 1", "Pareja 2", (3, 1))

    tabla = servicio.tabla_de_posiciones(sesion, padel)[0]
    primero = tabla.filas[0]
    assert tabla.con_sets
    assert (primero.sets_a_favor, primero.sets_en_contra, primero.diferencia_sets) == (2, 0, 2)
    assert (primero.a_favor, primero.en_contra, primero.diferencia) == (12, 7, 5)

    tabla = servicio.tabla_de_posiciones(sesion, futbol)[0]
    assert not tabla.con_sets
    assert tabla.filas[0].diferencia_sets is None


def test_el_orden_de_la_tabla_de_futbol_no_cambia(sesion, sucursal):
    """Sin sets ni cara a cara: puntos, diferencia, a favor."""
    torneo = _torneo(
        sesion, sucursal, deporte=Deporte.FUTBOL, sets_para_ganar=1, games_por_set=None,
        nombre="Fútbol",
    )
    _con_parejas(sesion, torneo, 3)
    _sortear(sesion, torneo)
    # P1 le ganó a P2 por poco, P2 le ganó a P3 por mucho, P3 a P1 por poco:
    # 3 puntos cada uno; manda la diferencia aunque P1 le ganó a P2.
    _jugar(sesion, torneo, "Pareja 1", "Pareja 2", (1, 0))
    _jugar(sesion, torneo, "Pareja 2", "Pareja 3", (5, 0))
    _jugar(sesion, torneo, "Pareja 3", "Pareja 1", (1, 0))
    assert _orden(sesion, torneo) == ["Pareja 2", "Pareja 1", "Pareja 3"]


# ── 4. Un torneo que termina en las zonas ───────────────────────────────────


def _de_zonas_sin_llaves(sesion, sucursal, parejas=6):
    torneo = _torneo(
        sesion, sucursal, formato=FormatoTorneo.ZONAS, cantidad_zonas=2,
        clasifican_por_zona=None, termina_en_zonas=True,
    )
    _con_parejas(sesion, torneo, parejas)
    _sortear(sesion, torneo)
    return torneo


def _jugar_zona(sesion, torneo, zona_id, ganador_por_nombre=None):
    """Juega todos los partidos de una zona; gana siempre el de nombre menor."""
    nombres = {c.id: c.nombre for c in servicio.competidores_de(sesion, torneo)}
    for partido in servicio.partidos_de(sesion, torneo):
        if partido.zona_id != zona_id:
            continue
        a, b = nombres[partido.competidor_a_id], nombres[partido.competidor_b_id]
        _jugar(sesion, torneo, min(a, b), max(a, b), (6, 2), (6, 3))


def test_sin_llaves_el_primero_de_cada_zona_es_campeon_de_su_zona(sesion, sucursal):
    torneo = _de_zonas_sin_llaves(sesion, sucursal)
    zonas = {t.zona_id for t in servicio.tabla_de_posiciones(sesion, torneo)}
    zona_a, zona_b = sorted(zonas)

    assert servicio.campeones_de_zonas(sesion, torneo) == []

    # La zona A termina antes: ya tiene campeón aunque el torneo siga.
    _jugar_zona(sesion, torneo, zona_a)
    campeones = servicio.campeones_de_zonas(sesion, torneo)
    assert [zona for zona, _ in campeones] == ["Zona A"]
    assert torneo.estado is EstadoTorneo.SORTEADO
    assert servicio.campeon(sesion, torneo) is None

    _jugar_zona(sesion, torneo, zona_b)
    campeones = servicio.campeones_de_zonas(sesion, torneo)
    assert [zona for zona, _ in campeones] == ["Zona A", "Zona B"]
    tablas = servicio.tabla_de_posiciones(sesion, torneo)
    assert [c.id for _, c in campeones] == [t.filas[0].competidor_id for t in tablas]
    assert all(t.completa for t in tablas)
    # 🔑 Termina solo, sin largar un playoff que no existe...
    assert torneo.estado is EstadoTorneo.FINALIZADO
    # ...y no hay UN campeón: son dos.
    assert servicio.campeon(sesion, torneo) is None


def test_sin_llaves_no_se_puede_largar_el_playoff(sesion, sucursal):
    torneo = _de_zonas_sin_llaves(sesion, sucursal)
    for tabla in servicio.tabla_de_posiciones(sesion, torneo):
        _jugar_zona(sesion, torneo, tabla.zona_id)
    with pytest.raises(servicio.EstadoDelTorneo, match="termina en las zonas"):
        servicio.generar_playoff(sesion, torneo)


def test_con_llaves_el_torneo_no_termina_al_cerrar_las_zonas(sesion, sucursal):
    """El control: el comportamiento de siempre sigue en pie."""
    torneo = _torneo(
        sesion, sucursal, formato=FormatoTorneo.ZONAS, cantidad_zonas=2, clasifican_por_zona=2,
    )
    _con_parejas(sesion, torneo, 8)
    _sortear(sesion, torneo)
    for tabla in servicio.tabla_de_posiciones(sesion, torneo):
        _jugar_zona(sesion, torneo, tabla.zona_id)
    assert torneo.estado is EstadoTorneo.SORTEADO
    assert servicio.campeones_de_zonas(sesion, torneo) == []
    servicio.generar_playoff(sesion, torneo)


def test_la_base_exige_coherencia_entre_llaves_y_clasificados(sesion, sucursal):
    # Por zonas, con llaves y sin cuántos clasifican: no.
    with pytest.raises(IntegrityError, match="ck_torneos_zonas_coherente"):
        _torneo(sesion, sucursal, formato=FormatoTorneo.ZONAS, cantidad_zonas=2)
    sesion.rollback()
    # Termina en las zonas Y dice cuántos clasifican: tampoco.
    with pytest.raises(IntegrityError, match="ck_torneos_zonas_coherente"):
        _torneo(
            sesion, sucursal, nombre="B", formato=FormatoTorneo.ZONAS, cantidad_zonas=2,
            clasifican_por_zona=1, termina_en_zonas=True,
        )
    sesion.rollback()
    # «Termina en las zonas» en una liga no significa nada.
    with pytest.raises(IntegrityError, match="ck_torneos_zonas_coherente"):
        _torneo(sesion, sucursal, nombre="C", termina_en_zonas=True)
    sesion.rollback()


# ── 5. Por HTTP ─────────────────────────────────────────────────────────────


def test_la_api_crea_un_americano_sin_llaves(api, complejo):  # noqa: F811
    sucursal, _ = complejo
    r = _crear(
        api, sucursal, nombre="Americano Caballeros", formato="zonas", cantidad_zonas=2,
        termina_en_zonas=True, games_por_set=9, sets_para_ganar=1,
        categoria="  Caballeros   5ta ",
    )
    assert r.status_code == 201, r.text
    torneo = r.json()
    assert torneo["termina_en_zonas"] is True
    assert torneo["clasifican_por_zona"] is None
    assert torneo["games_por_set"] == 9
    assert torneo["categoria"] == "Caballeros 5ta", "se normalizan los blancos"


@pytest.mark.parametrize(
    "extra,motivo",
    [
        (dict(formato="zonas", cantidad_zonas=2, clasifican_por_zona=2, termina_en_zonas=True),
         "no lleva clasificados"),
        (dict(formato="zonas", termina_en_zonas=True), "cuántas zonas"),
        (dict(formato="zonas", cantidad_zonas=2), "cuántos clasifican"),
        (dict(formato="liga", termina_en_zonas=True), "Sólo un torneo por zonas"),
        (dict(games_por_set=7), "6 o a 9"),
        (dict(games_por_set=6, deporte="futbol", sets_para_ganar=1), "pádel y de tenis"),
        (dict(evento_id=1), "necesita su categoría"),
    ],
)
def test_la_api_rechaza_combinaciones_incoherentes(api, complejo, extra, motivo):  # noqa: F811
    sucursal, _ = complejo
    r = _crear(api, sucursal, **extra)
    assert r.status_code == 422, r.text
    assert motivo in r.text


def test_la_api_dice_el_set_que_no_es_valido(api, complejo):  # noqa: F811
    sucursal, _ = complejo
    torneo = _crear(api, sucursal, formato="liga", games_por_set=6, sets_para_ganar=1).json()
    _inscribir(api, torneo["id"], 3)
    api.post(f"/api/torneos/{torneo['id']}/sortear")
    partido = api.get(f"/api/torneos/{torneo['id']}/fixture").json()["partidos"][0]
    r = api.post(
        f"/api/torneos/partidos/{partido['id']}/resultado",
        json={"parciales": [{"puntos_a": 6, "puntos_b": 5}]},
    )
    assert r.status_code == 422
    assert "un set a 6 games" in r.json()["detail"]
    r = api.post(
        f"/api/torneos/partidos/{partido['id']}/resultado",
        json={"parciales": [{"puntos_a": 7, "puntos_b": 5}]},
    )
    assert r.status_code == 200, r.text


def test_la_lista_dice_los_campeones_de_cada_zona(api, complejo):  # noqa: F811
    sucursal, _ = complejo
    torneo = _crear(
        api, sucursal, formato="zonas", cantidad_zonas=2, termina_en_zonas=True,
        games_por_set=6, sets_para_ganar=1,
    ).json()
    _inscribir(api, torneo["id"], 6)
    api.post(f"/api/torneos/{torneo['id']}/sortear?semilla=3")
    partidos = api.get(f"/api/torneos/{torneo['id']}/fixture").json()["partidos"]
    for partido in partidos:
        if partido["zona"] != "Zona A":
            continue
        gana_a = partido["competidor_a"] < partido["competidor_b"]
        r = api.post(
            f"/api/torneos/partidos/{partido['id']}/resultado",
            json={"parciales": [{"puntos_a": 6 if gana_a else 2, "puntos_b": 2 if gana_a else 6}]},
        )
        assert r.status_code == 200, r.text

    tablas = api.get(f"/api/torneos/{torneo['id']}/posiciones").json()
    assert [t["completa"] for t in tablas] == [True, False]
    assert all(t["con_sets"] for t in tablas)
    fila = next(t for t in api.get("/api/torneos").json() if t["id"] == torneo["id"])
    assert fila["campeon"] == f"Zona A: {tablas[0]['filas'][0]['nombre']}"
    assert fila["estado"] == "sorteado"


# ── 6. Categorías y eventos ─────────────────────────────────────────────────


def _evento(api, sucursal, canchas=(), **extra):  # noqa: F811
    cuerpo = {
        "sucursal_id": sucursal["id"], "nombre": "Americano de primavera",
        "desde": "2026-10-10", "hasta": "2026-10-11",
        "cancha_ids": [c["id"] for c in canchas], **extra,
    }
    return api.post("/api/eventos", json=cuerpo)


def test_un_torneo_suelto_lleva_su_categoria(api, complejo):  # noqa: F811
    sucursal, _ = complejo
    torneo = _crear(api, sucursal, categoria="Damas").json()
    fila = next(t for t in api.get("/api/torneos").json() if t["id"] == torneo["id"])
    assert fila["categoria"] == "Damas" and fila["evento_id"] is None and fila["evento"] is None


def test_un_evento_junta_categorias_con_las_mismas_fechas(api, complejo):  # noqa: F811
    sucursal, canchas = complejo
    evento = _evento(api, sucursal, canchas[:1]).json()
    assert evento["cancha_ids"] == [canchas[0]["id"]]

    ids = []
    for categoria in ("Caballeros 5ta", "Caballeros 6ta", "Damas"):
        r = _crear(
            api, sucursal, nombre=f"Americano — {categoria}", categoria=categoria,
            evento_id=evento["id"],
            # 🔑 Las fechas que mande el pedido no cuentan: manda el evento.
            desde="2026-12-01", hasta=None, formato="zonas", cantidad_zonas=2,
            termina_en_zonas=True, games_por_set=6, sets_para_ganar=1,
        )
        assert r.status_code == 201, r.text
        assert (r.json()["desde"], r.json()["hasta"]) == ("2026-10-10", "2026-10-11")
        ids.append(r.json()["id"])

    detalle = api.get(f"/api/eventos/{evento['id']}").json()
    assert [c["categoria"] for c in detalle["categorias"]] == [
        "Caballeros 5ta", "Caballeros 6ta", "Damas",
    ]
    assert {c["id"] for c in detalle["categorias"]} == set(ids)
    assert all(c["evento"] == "Americano de primavera" for c in detalle["categorias"])

    lista = api.get("/api/eventos").json()
    assert [(e["nombre"], e["categorias"]) for e in lista] == [("Americano de primavera", 3)]


def test_una_categoria_no_se_repite_dentro_del_evento(api, complejo):  # noqa: F811
    sucursal, _ = complejo
    evento = _evento(api, sucursal).json()
    primera = _crear(api, sucursal, nombre="Uno", categoria="Mixto", evento_id=evento["id"])
    assert primera.status_code == 201
    repetida = _crear(api, sucursal, nombre="Dos", categoria="mixto", evento_id=evento["id"])
    assert repetida.status_code == 409
    assert "ya tiene la categoría" in repetida.json()["detail"]
    # En otro evento, o suelta, sí puede repetirse.
    assert _crear(api, sucursal, nombre="Tres", categoria="Mixto").status_code == 201


def test_cambiar_las_fechas_del_evento_las_cambia_en_todas_las_categorias(api, complejo):  # noqa: F811
    sucursal, _ = complejo
    evento = _evento(api, sucursal).json()
    uno = _crear(api, sucursal, nombre="Uno", categoria="Damas", evento_id=evento["id"]).json()

    r = api.put(
        f"/api/eventos/{evento['id']}",
        json={"nombre": "Americano de primavera", "desde": "2026-10-17", "hasta": "2026-10-18",
              "observaciones": None, "cancha_ids": []},
    )
    assert r.status_code == 200, r.text
    torneo = api.get(f"/api/torneos/{uno['id']}").json()
    assert (torneo["desde"], torneo["hasta"]) == ("2026-10-17", "2026-10-18")

    # Y una categoría no puede separarse de las fechas del evento.
    r = api.put(
        f"/api/torneos/{uno['id']}",
        json={"nombre": "Uno", "desde": "2026-11-01", "hasta": None},
    )
    assert r.status_code == 422
    assert "las define el evento" in r.json()["detail"]
    # Pero sí se puede corregir el nombre con las fechas del evento.
    r = api.put(
        f"/api/torneos/{uno['id']}",
        json={"nombre": "Uno bis", "desde": "2026-10-17", "hasta": "2026-10-18",
              "categoria": "Damas 4ta"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["categoria"] == "Damas 4ta"


def test_el_evento_valida_su_sucursal_sus_canchas_y_su_nombre(api, complejo):  # noqa: F811
    sucursal, canchas = complejo
    otra = api.post("/api/sucursales", json={"nombre": "Norte"}).json()
    ajena = api.post(
        "/api/canchas",
        json={"sucursal_id": otra["id"], "nombre": "Cancha N", "deporte": "padel",
              "duracion_turno_min": 90},
    ).json()

    r = _evento(api, sucursal, [ajena])
    assert r.status_code == 422 and "es de otra sucursal" in r.json()["detail"]
    assert _evento(api, sucursal, [{"id": 99999}]).status_code == 422
    assert _evento(api, sucursal, hasta="2026-10-01").status_code == 422, "termina antes de empezar"

    assert _evento(api, sucursal).status_code == 201
    repetido = _evento(api, sucursal)
    assert repetido.status_code == 409

    evento = api.get("/api/eventos").json()[0]
    r = _crear(api, otra, nombre="X", categoria="Damas", evento_id=evento["id"])
    assert r.status_code == 422 and "otra sucursal" in r.json()["detail"]
    assert _crear(api, sucursal, nombre="Y", categoria="Damas", evento_id=99999).status_code == 404


def test_las_categorias_de_un_evento_se_juegan_en_las_canchas_del_evento(api, complejo):  # noqa: F811
    sucursal, canchas = complejo
    evento = _evento(api, sucursal, canchas[:1]).json()
    torneo = _crear(
        api, sucursal, nombre="Cat", categoria="Mixto", evento_id=evento["id"],
        formato="liga", sets_para_ganar=1, games_por_set=6,
    ).json()
    _inscribir(api, torneo["id"], 3)
    api.post(f"/api/torneos/{torneo['id']}/sortear")
    partidos = api.get(f"/api/torneos/{torneo['id']}/fixture").json()["partidos"]

    afuera = api.post(
        f"/api/torneos/partidos/{partidos[0]['id']}/programar",
        json={"cancha_id": canchas[1]["id"], "comienza_at": f"{HOY.isoformat()}T20:00:00"},
    )
    assert afuera.status_code == 422
    assert "no es una de las canchas de este evento" in afuera.json()["detail"]

    adentro = api.post(
        f"/api/torneos/partidos/{partidos[0]['id']}/programar",
        json={"cancha_id": canchas[0]["id"], "comienza_at": f"{HOY.isoformat()}T20:00:00"},
    )
    assert adentro.status_code == 200, adentro.text

    # Un evento sin canchas cargadas no restringe nada.
    libre = _evento(api, sucursal, nombre="Libre").json()
    otro = _crear(
        api, sucursal, nombre="Cat libre", categoria="Damas", evento_id=libre["id"],
        formato="liga", sets_para_ganar=1, games_por_set=6,
    ).json()
    _inscribir(api, otro["id"], 3)
    api.post(f"/api/torneos/{otro['id']}/sortear")
    partido = api.get(f"/api/torneos/{otro['id']}/fixture").json()["partidos"][0]
    r = api.post(
        f"/api/torneos/partidos/{partido['id']}/programar",
        json={"cancha_id": canchas[1]["id"],
              "comienza_at": (datetime.fromisoformat(f"{HOY.isoformat()}T20:00:00")
                              + timedelta(days=1)).isoformat()},
    )
    assert r.status_code == 200, r.text


def test_crear_y_editar_eventos_es_de_admin_y_verlos_de_staff(api, api_staff, complejo):  # noqa: F811
    sucursal, _ = complejo
    cuerpo = {"sucursal_id": sucursal["id"], "nombre": "E", "desde": "2026-10-10"}
    assert api_staff.post("/api/eventos", json=cuerpo).status_code == 403
    evento = api.post("/api/eventos", json=cuerpo).json()
    assert api_staff.get("/api/eventos").status_code == 200
    assert api_staff.get(f"/api/eventos/{evento['id']}").status_code == 200
    assert api_staff.put(f"/api/eventos/{evento['id']}", json={
        "nombre": "E2", "desde": "2026-10-10"}).status_code == 403


# ── 7. La migración 0015 ────────────────────────────────────────────────────


def _alembic() -> AlembicConfig:
    cfg = AlembicConfig(os.path.join(RAIZ, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(RAIZ, "migrations"))
    return cfg


def _tablas_y_columnas(motor) -> tuple[set[str], set[str]]:
    with motor.connect() as conexion:
        tablas = set(conexion.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )).scalars())
        columnas = set(conexion.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'torneos'"
        )).scalars())
    return tablas, columnas


def test_la_migracion_0015_es_reversible_y_no_pierde_un_torneo_sin_llaves(base_temporal, monkeypatch):
    """Sube, baja a la `0014` con un torneo que termina en las zonas adentro, y vuelve a subir.

    Al bajar, el CHECK de antes exige `clasifican_por_zona` entre 1 y 2: el torneo
    sin llaves queda con 1 (pasa el primero de cada zona) en vez de trabar la baja.
    """
    url = base_temporal("mig0015")
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _alembic()
    motor = create_engine(url, future=True)
    nuevas = {"games_por_set", "termina_en_zonas", "categoria", "evento_id"}
    try:
        command.upgrade(cfg, "head")
        tablas, columnas = _tablas_y_columnas(motor)
        assert {"eventos", "eventos_canchas"} <= tablas and nuevas <= columnas

        with motor.begin() as conexion:
            conexion.execute(text("INSERT INTO sucursales (nombre, punto_venta_arca) VALUES ('S', 1)"))
            conexion.execute(text(
                "INSERT INTO torneos (sucursal_id, nombre, deporte, formato, desde, sets_para_ganar, "
                "cantidad_zonas, termina_en_zonas, games_por_set, categoria) "
                "VALUES (1, 'Americano', 'padel', 'zonas', '2026-10-10', 1, 2, true, 9, 'Damas')"
            ))

        command.downgrade(cfg, "0014_libraedge")
        tablas, columnas = _tablas_y_columnas(motor)
        assert not ({"eventos", "eventos_canchas"} & tablas) and not (nuevas & columnas)
        with motor.connect() as conexion:
            fila = conexion.execute(text(
                "SELECT nombre, cantidad_zonas, clasifican_por_zona FROM torneos"
            )).one()
        assert tuple(fila) == ("Americano", 2, 1)

        command.upgrade(cfg, "head")
        tablas, columnas = _tablas_y_columnas(motor)
        assert {"eventos", "eventos_canchas"} <= tablas and nuevas <= columnas
        with motor.connect() as conexion:
            assert conexion.execute(text("SELECT termina_en_zonas FROM torneos")).scalar_one() is False
    finally:
        motor.dispose()
