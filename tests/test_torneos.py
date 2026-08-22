"""Torneos: sorteo, resultados, programación de canchas y posiciones.

Los tests de `test_fixture.py` prueban el armado del cuadro sin base. Éstos
prueban lo que sólo se puede probar contra PostgreSQL: que el sorteo se
persista, que programar un partido **ocupe la cancha de verdad**, y que un
resultado corregido no reescriba un torneo ya jugado.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.models.enums import (
    ESTADOS_QUE_OCUPAN,
    Deporte,
    EstadoReserva,
    EstadoTorneo,
    EtapaTorneo,
    FormatoTorneo,
)
from app.models.maestros import Cancha
from app.models.reservas import Reserva
from app.models.torneos import PartidoDeTorneo, Torneo
from app.servicios import reservas as servicio_reservas
from app.servicios import torneos as servicio
from app.tiempo import TZ

#: Un pádel al mejor de tres que gana el de arriba, y el mismo al revés.
GANA_A = [(6, 4), (6, 3)]
GANA_B = [(4, 6), (3, 6)]


@pytest.fixture
def torneo(sesion, sucursal) -> Torneo:
    item = Torneo(
        sucursal_id=sucursal.id,
        nombre="Apertura",
        deporte=Deporte.PADEL,
        formato=FormatoTorneo.ELIMINACION,
        desde=date(2026, 9, 5),
        sets_para_ganar=2,
    )
    sesion.add(item)
    sesion.commit()
    return item


def inscribir(sesion, torneo, cuantos, sembrados=0):
    for numero in range(1, cuantos + 1):
        servicio.inscribir(
            sesion,
            torneo,
            nombre=f"Pareja {numero}",
            siembra=numero if numero <= sembrados else None,
        )
    sesion.commit()


def de_ronda(sesion, torneo, ronda):
    return [p for p in servicio.partidos_de(sesion, torneo) if p.ronda == ronda]


# ── Sorteo ──────────────────────────────────────────────────────────────────


def test_la_misma_semilla_da_el_mismo_cuadro(sesion, sucursal, torneo):
    """🔑 Lo que hace auditable al sorteo.

    Sin esto, "¿por qué me tocó el primero?" no tiene respuesta verificable, que
    en un torneo con premio es un problema y no una curiosidad.
    """
    inscribir(sesion, torneo, 8)
    servicio.sortear(sesion, torneo, semilla=4242)
    sesion.commit()
    uno = _forma(sesion, torneo)

    otro = Torneo(
        sucursal_id=sucursal.id, nombre="Apertura bis", deporte=Deporte.PADEL,
        formato=FormatoTorneo.ELIMINACION, desde=date(2026, 9, 5), sets_para_ganar=2,
    )
    sesion.add(otro)
    sesion.commit()
    inscribir(sesion, otro, 8)
    servicio.sortear(sesion, otro, semilla=4242)
    sesion.commit()

    assert _forma(sesion, otro) == uno


def test_semillas_distintas_dan_cuadros_distintos(sesion, sucursal, torneo):
    """El control del test de arriba: si el sorteo ignorara la semilla, aquel
    pasaría igual y este no."""
    inscribir(sesion, torneo, 8)
    servicio.sortear(sesion, torneo, semilla=1)
    sesion.commit()
    uno = _forma(sesion, torneo)

    otro = Torneo(
        sucursal_id=sucursal.id, nombre="Otro", deporte=Deporte.PADEL,
        formato=FormatoTorneo.ELIMINACION, desde=date(2026, 9, 5), sets_para_ganar=2,
    )
    sesion.add(otro)
    sesion.commit()
    inscribir(sesion, otro, 8)
    servicio.sortear(sesion, otro, semilla=999)
    sesion.commit()
    assert _forma(sesion, otro) != uno


def _forma(sesion, torneo):
    nombres = {c.id: c.nombre for c in servicio.competidores_de(sesion, torneo)}
    return [
        (p.ronda, p.orden, nombres.get(p.competidor_a_id), nombres.get(p.competidor_b_id))
        for p in servicio.partidos_de(sesion, torneo)
    ]


def test_el_sorteo_guarda_la_semilla_aunque_no_se_la_pasen(sesion, torneo):
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo)
    sesion.commit()
    assert torneo.semilla is not None


def test_los_sembrados_no_entran_al_bombo(sesion, torneo):
    """Con 6 y dos sembrados, los sembrados son los que descansan.

    🔴 Si se mezclaran con el resto, ser cabeza de serie no significaría nada —
    que es exactamente lo que no se puede notar mirando un cuadro.
    """
    inscribir(sesion, torneo, 6, sembrados=2)
    servicio.sortear(sesion, torneo, semilla=7)
    sesion.commit()
    nombres = {c.id: c.nombre for c in servicio.competidores_de(sesion, torneo)}
    juegan_primera = {
        nombres[x]
        for p in de_ronda(sesion, torneo, 1)
        for x in (p.competidor_a_id, p.competidor_b_id)
    }
    assert "Pareja 1" not in juegan_primera
    assert "Pareja 2" not in juegan_primera


def test_no_se_sortea_dos_veces(sesion, torneo):
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo)
    sesion.commit()
    with pytest.raises(servicio.EstadoDelTorneo):
        servicio.sortear(sesion, torneo)


def test_un_torneo_de_uno_no_se_sortea(sesion, torneo):
    inscribir(sesion, torneo, 1)
    with pytest.raises(servicio.TorneoInvalido):
        servicio.sortear(sesion, torneo)


def test_despues_del_sorteo_no_se_inscribe(sesion, torneo):
    """Un inscripto tardío no tendría dónde entrar en el cuadro."""
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo)
    sesion.commit()
    with pytest.raises(servicio.EstadoDelTorneo):
        servicio.inscribir(sesion, torneo, nombre="Tarde")


def test_despues_del_sorteo_no_se_da_de_baja(sesion, torneo):
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo)
    sesion.commit()
    alguno = servicio.competidores_de(sesion, torneo)[0]
    with pytest.raises(servicio.EstadoDelTorneo):
        servicio.bajar_competidor(sesion, alguno)


# ── Resultados ──────────────────────────────────────────────────────────────


def test_el_ganador_pasa_a_la_ronda_siguiente(sesion, torneo):
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()

    semi = de_ronda(sesion, torneo, 1)[0]
    servicio.cargar_resultado(sesion, semi, GANA_A)
    sesion.commit()

    final = sesion.get(PartidoDeTorneo, semi.avanza_a_id)
    llego = getattr(final, f"competidor_{semi.avanza_a_slot}_id")
    assert llego == semi.competidor_a_id


def test_el_perdedor_no_pasa(sesion, torneo):
    """El control del de arriba: si `_propagar` escribiera cualquiera de los
    dos, aquel pasaría la mitad de las veces."""
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    semi = de_ronda(sesion, torneo, 1)[0]
    servicio.cargar_resultado(sesion, semi, GANA_B)
    sesion.commit()
    final = sesion.get(PartidoDeTorneo, semi.avanza_a_id)
    assert getattr(final, f"competidor_{semi.avanza_a_slot}_id") == semi.competidor_b_id


def test_no_se_carga_un_partido_sin_rivales(sesion, torneo):
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    final = de_ronda(sesion, torneo, 2)[0]
    with pytest.raises(servicio.EstadoDelTorneo, match="quiénes juegan"):
        servicio.cargar_resultado(sesion, final, GANA_A)


@pytest.mark.parametrize(
    "parciales,porque",
    [
        ([(6, 4)], "un solo set en un partido al mejor de tres"),
        ([(6, 6)], "un set no termina empatado"),
        ([(6, 4), (6, 3), (2, 6)], "no se sigue jugando después de ganar"),
        ([(6, 4), (3, 6), (6, 2), (6, 1)], "cuatro sets en un partido a dos"),
    ],
)
def test_resultados_que_no_pueden_ser(sesion, torneo, parciales, porque):
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    semi = de_ronda(sesion, torneo, 1)[0]
    with pytest.raises(servicio.TorneoInvalido):
        servicio.cargar_resultado(sesion, semi, parciales)


def test_el_ultimo_parcial_lo_gana_el_que_gana(sesion, torneo):
    """🔑 Es el error de tipeo más común: cargar los sets en cualquier orden.

    `6-4 / 3-6 / 2-6` es una victoria de B; cargado como si ganara A, el cuadro
    haría avanzar al que perdió.
    """
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    semi = de_ronda(sesion, torneo, 1)[0]
    # Éste sí es válido: gana B 2-1.
    servicio.cargar_resultado(sesion, semi, [(6, 4), (3, 6), (2, 6)])
    sesion.commit()
    assert semi.ganador_id == semi.competidor_b_id


def test_una_llave_no_termina_empatada(sesion, sucursal):
    """En fútbol de zona el empate existe; en una llave, alguien tiene que pasar."""
    torneo = Torneo(
        sucursal_id=sucursal.id, nombre="Copa", deporte=Deporte.FUTBOL,
        formato=FormatoTorneo.ELIMINACION, desde=date(2026, 9, 5), sets_para_ganar=1,
    )
    sesion.add(torneo)
    sesion.commit()
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    semi = de_ronda(sesion, torneo, 1)[0]
    with pytest.raises(servicio.TorneoInvalido, match="empatada"):
        servicio.cargar_resultado(sesion, semi, [(1, 1)])


def test_en_una_zona_de_futbol_el_empate_vale(sesion, sucursal):
    torneo = Torneo(
        sucursal_id=sucursal.id, nombre="Liga", deporte=Deporte.FUTBOL,
        formato=FormatoTorneo.LIGA, desde=date(2026, 9, 5), sets_para_ganar=1,
    )
    sesion.add(torneo)
    sesion.commit()
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    partido = servicio.partidos_de(sesion, torneo)[0]
    servicio.cargar_resultado(sesion, partido, [(1, 1)])
    sesion.commit()
    assert partido.finalizado and partido.ganador_id is None


def test_un_partido_de_futbol_es_un_solo_resultado(sesion, sucursal):
    torneo = Torneo(
        sucursal_id=sucursal.id, nombre="Liga", deporte=Deporte.FUTBOL,
        formato=FormatoTorneo.LIGA, desde=date(2026, 9, 5), sets_para_ganar=1,
    )
    sesion.add(torneo)
    sesion.commit()
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    partido = servicio.partidos_de(sesion, torneo)[0]
    with pytest.raises(servicio.TorneoInvalido, match="un solo resultado"):
        servicio.cargar_resultado(sesion, partido, [(1, 0), (2, 1)])


def test_corregir_el_marcador_sin_cambiar_el_ganador(sesion, torneo):
    """El caso frecuente: cargaron 6-3 donde iba 6-2. Tiene que dejarse."""
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    primera = de_ronda(sesion, torneo, 1)
    for partido in primera:
        servicio.cargar_resultado(sesion, partido, GANA_A)
    final = sesion.get(PartidoDeTorneo, primera[0].avanza_a_id)
    servicio.cargar_resultado(sesion, final, GANA_A)
    sesion.commit()

    servicio.cargar_resultado(sesion, primera[0], [(6, 2), (6, 1)])
    sesion.commit()
    assert [(p.puntos_a, p.puntos_b) for p in primera[0].parciales] == [(6, 2), (6, 1)]


def test_no_se_cambia_el_ganador_si_el_siguiente_ya_se_jugo(sesion, torneo):
    """🔴 Dejaría a alguien jugando un partido al que nunca clasificó.

    El cuadro contaría una historia que no pasó, y nada avisaría. Se rechaza y
    se pide borrar el resultado de abajo primero — que es una decisión con
    consecuencias y tiene que ser deliberada.
    """
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    primera = de_ronda(sesion, torneo, 1)
    for partido in primera:
        servicio.cargar_resultado(sesion, partido, GANA_A)
    final = sesion.get(PartidoDeTorneo, primera[0].avanza_a_id)
    servicio.cargar_resultado(sesion, final, GANA_A)
    sesion.commit()

    with pytest.raises(servicio.EstadoDelTorneo, match="ya tiene resultado"):
        servicio.cargar_resultado(sesion, primera[0], GANA_B)


def test_borrar_el_resultado_saca_al_ganador_de_la_ronda_siguiente(sesion, torneo):
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    semi = de_ronda(sesion, torneo, 1)[0]
    servicio.cargar_resultado(sesion, semi, GANA_A)
    sesion.commit()
    final = sesion.get(PartidoDeTorneo, semi.avanza_a_id)
    assert getattr(final, f"competidor_{semi.avanza_a_slot}_id") is not None

    servicio.borrar_resultado(sesion, semi)
    sesion.commit()
    sesion.refresh(final)
    assert getattr(final, f"competidor_{semi.avanza_a_slot}_id") is None
    assert not semi.finalizado and semi.ganador_id is None


def test_el_torneo_se_cierra_cuando_se_jugo_todo(sesion, torneo):
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    for partido in de_ronda(sesion, torneo, 1):
        servicio.cargar_resultado(sesion, partido, GANA_A)
    sesion.commit()
    assert torneo.estado is EstadoTorneo.SORTEADO, "todavía falta la final"

    final = de_ronda(sesion, torneo, 2)[0]
    servicio.cargar_resultado(sesion, final, GANA_A)
    sesion.commit()
    assert torneo.estado is EstadoTorneo.FINALIZADO
    campeon = servicio.campeon(sesion, torneo)
    assert campeon is not None and campeon.id == final.competidor_a_id


def test_borrar_un_resultado_reabre_el_torneo(sesion, torneo):
    """Un torneo finalizado con un resultado borrado ya no tiene campeón."""
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    for partido in servicio.partidos_de(sesion, torneo):
        if partido.competidor_a_id and partido.competidor_b_id:
            servicio.cargar_resultado(sesion, partido, GANA_A)
    final = de_ronda(sesion, torneo, 2)[0]
    servicio.cargar_resultado(sesion, final, GANA_A)
    sesion.commit()
    assert torneo.estado is EstadoTorneo.FINALIZADO

    servicio.borrar_resultado(sesion, final)
    sesion.commit()
    assert torneo.estado is EstadoTorneo.SORTEADO
    assert servicio.campeon(sesion, torneo) is None


# ── Programación: la cancha se ocupa de verdad ──────────────────────────────


@pytest.fixture
def sorteado(sesion, torneo, tarifa_base):
    inscribir(sesion, torneo, 4)
    servicio.sortear(sesion, torneo, semilla=3)
    sesion.commit()
    return torneo


def _cuando(hora=20):
    return datetime(2026, 9, 5, hora, 0, tzinfo=TZ)


def test_programar_ocupa_la_cancha(sesion, sorteado, cancha):
    """🔑 La razón por la que un partido de torneo crea un bloqueo real.

    Sin el bloqueo, el mostrador puede alquilar esa cancha a esa hora y el día
    del torneo hay dos grupos en la puerta. Lo que lo impide es el constraint de
    exclusión, que sólo mira `reservas`.
    """
    partido = de_ronda(sesion, sorteado, 1)[0]
    servicio.programar(sesion, partido, cancha_id=cancha.id, comienza_at=_cuando())
    sesion.commit()

    bloqueo = sesion.get(Reserva, partido.reserva_id)
    assert bloqueo.estado is EstadoReserva.BLOQUEO
    assert bloqueo.cancha_id == cancha.id
    assert sorteado.nombre in bloqueo.motivo
    # Y la cancha aparece ocupada para cualquiera que la mire.
    assert servicio_reservas.ocupadas(
        sesion, cancha.id, _cuando(), _cuando() + timedelta(minutes=90)
    )


def test_no_se_puede_reservar_encima_de_un_partido_de_torneo(
    sesion, sorteado, cancha, cliente
):
    partido = de_ronda(sesion, sorteado, 1)[0]
    servicio.programar(sesion, partido, cancha_id=cancha.id, comienza_at=_cuando())
    sesion.commit()
    with pytest.raises(servicio_reservas.Superpuesta):
        servicio_reservas.crear(
            sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_cuando()
        )


def test_dos_partidos_no_entran_en_la_misma_cancha_y_hora(sesion, sorteado, cancha):
    uno, otro = de_ronda(sesion, sorteado, 1)
    servicio.programar(sesion, uno, cancha_id=cancha.id, comienza_at=_cuando())
    sesion.commit()
    with pytest.raises(servicio_reservas.Superpuesta):
        servicio.programar(sesion, otro, cancha_id=cancha.id, comienza_at=_cuando())


def test_reprogramar_libera_el_horario_viejo(sesion, sorteado, cancha):
    partido = de_ronda(sesion, sorteado, 1)[0]
    servicio.programar(sesion, partido, cancha_id=cancha.id, comienza_at=_cuando(20))
    sesion.commit()
    viejo = partido.reserva_id

    servicio.programar(sesion, partido, cancha_id=cancha.id, comienza_at=_cuando(22))
    sesion.commit()
    assert partido.reserva_id != viejo
    assert sesion.get(Reserva, viejo).estado is EstadoReserva.CANCELADA
    # Las 20:00 quedaron libres de verdad.
    assert not servicio_reservas.ocupadas(
        sesion, cancha.id, _cuando(20), _cuando(20) + timedelta(minutes=90)
    )


def test_una_reprogramacion_fallida_no_deja_al_partido_sin_cancha(
    sesion, sorteado, cancha, sucursal
):
    """🔴 El peor resultado posible de una operación que falló.

    Mover un partido libera el horario viejo antes de tomar el nuevo. Si el
    nuevo está ocupado y las dos cosas no van en el mismo SAVEPOINT, el partido
    se queda sin ninguno: había cancha y ahora no hay.
    """
    otra = Cancha(
        sucursal_id=sucursal.id, nombre="Cancha 2", deporte=Deporte.PADEL,
        duracion_turno_min=90,
    )
    sesion.add(otra)
    sesion.commit()

    partido = de_ronda(sesion, sorteado, 1)[0]
    servicio.programar(sesion, partido, cancha_id=cancha.id, comienza_at=_cuando())
    sesion.commit()
    tenia = partido.reserva_id

    servicio_reservas.crear_bloqueo(
        sesion, cancha_id=otra.id, comienza_at=_cuando(),
        termina_at=_cuando() + timedelta(minutes=90), motivo="mantenimiento",
    )
    sesion.commit()

    with pytest.raises(servicio_reservas.Superpuesta):
        servicio.programar(sesion, partido, cancha_id=otra.id, comienza_at=_cuando())
    sesion.commit()

    sesion.refresh(partido)
    assert partido.reserva_id == tenia, "se quedó sin cancha"
    assert sesion.get(Reserva, tenia).estado is EstadoReserva.BLOQUEO


def test_liberar_devuelve_el_horario(sesion, sorteado, cancha):
    partido = de_ronda(sesion, sorteado, 1)[0]
    servicio.programar(sesion, partido, cancha_id=cancha.id, comienza_at=_cuando())
    sesion.commit()
    servicio.desprogramar(sesion, partido)
    sesion.commit()
    assert partido.reserva_id is None
    assert not servicio_reservas.ocupadas(
        sesion, cancha.id, _cuando(), _cuando() + timedelta(minutes=90)
    )


def test_cancelar_el_torneo_libera_todas_las_canchas(sesion, sorteado, cancha):
    """Sin esto, las canchas del fin de semana quedan tomadas por un torneo que
    no se juega, y nadie tiene cómo saber por qué."""
    for numero, partido in enumerate(de_ronda(sesion, sorteado, 1)):
        servicio.programar(
            sesion, partido, cancha_id=cancha.id, comienza_at=_cuando(18 + numero * 2)
        )
    sesion.commit()

    liberadas = servicio.cancelar(sesion, sorteado)
    sesion.commit()
    assert liberadas == 2
    assert sorteado.estado is EstadoTorneo.CANCELADO
    vivos = [
        r
        for r in sesion.query(Reserva).all()
        if r.estado in ESTADOS_QUE_OCUPAN and sorteado.nombre in (r.motivo or "")
    ]
    assert vivos == []


def test_no_se_programa_un_partido_ya_jugado(sesion, sorteado, cancha):
    partido = de_ronda(sesion, sorteado, 1)[0]
    servicio.cargar_resultado(sesion, partido, GANA_A)
    sesion.commit()
    with pytest.raises(servicio.EstadoDelTorneo, match="ya se jugó"):
        servicio.programar(sesion, partido, cancha_id=cancha.id, comienza_at=_cuando())


# ── Tabla de posiciones ─────────────────────────────────────────────────────


@pytest.fixture
def liga(sesion, sucursal):
    item = Torneo(
        sucursal_id=sucursal.id, nombre="Liga", deporte=Deporte.FUTBOL,
        formato=FormatoTorneo.LIGA, desde=date(2026, 9, 5), sets_para_ganar=1,
    )
    sesion.add(item)
    sesion.commit()
    inscribir(sesion, item, 4)
    servicio.sortear(sesion, item, semilla=11)
    sesion.commit()
    return item


def test_la_tabla_cuenta_puntos_y_diferencia(sesion, liga):
    por_nombre = {c.nombre: c.id for c in servicio.competidores_de(sesion, liga)}
    uno = por_nombre["Pareja 1"]
    for partido in servicio.partidos_de(sesion, liga):
        # La 1 gana todos los suyos 3-0; el resto empata 0-0.
        if uno in (partido.competidor_a_id, partido.competidor_b_id):
            gana_a = partido.competidor_a_id == uno
            servicio.cargar_resultado(sesion, partido, [(3, 0)] if gana_a else [(0, 3)])
        else:
            servicio.cargar_resultado(sesion, partido, [(0, 0)])
    sesion.commit()

    tabla = servicio.tabla_de_posiciones(sesion, liga)[0]
    primero = tabla.filas[0]
    assert primero.competidor_id == uno
    assert (primero.jugados, primero.ganados, primero.empatados, primero.perdidos) == (3, 3, 0, 0)
    assert (primero.a_favor, primero.en_contra, primero.diferencia) == (9, 0, 9)
    assert primero.puntos == 9
    # Los otros tres: dos empates y una derrota.
    for fila in tabla.filas[1:]:
        assert (fila.ganados, fila.empatados, fila.perdidos) == (0, 2, 1)
        assert fila.puntos == 2


def test_la_tabla_incluye_al_que_no_jugo(sesion, liga):
    """Esconderlo hace creer que se olvidaron de inscribirlo."""
    tabla = servicio.tabla_de_posiciones(sesion, liga)[0]
    assert len(tabla.filas) == 4
    assert all(f.jugados == 0 for f in tabla.filas)


def test_una_liga_no_tiene_zonas(sesion, liga):
    """Inventarle una zona «Única» pondría un encabezado sin información."""
    tablas = servicio.tabla_de_posiciones(sesion, liga)
    assert len(tablas) == 1
    assert tablas[0].zona_id is None and tablas[0].nombre is None
    assert all(p.zona_id is None for p in servicio.partidos_de(sesion, liga))


# ── Zonas y playoff ─────────────────────────────────────────────────────────


@pytest.fixture
def por_zonas(sesion, sucursal):
    item = Torneo(
        sucursal_id=sucursal.id, nombre="Clausura", deporte=Deporte.PADEL,
        formato=FormatoTorneo.ZONAS, desde=date(2026, 9, 5), sets_para_ganar=2,
        cantidad_zonas=2, clasifican_por_zona=2,
    )
    sesion.add(item)
    sesion.commit()
    inscribir(sesion, item, 8, sembrados=2)
    servicio.sortear(sesion, item, semilla=5)
    sesion.commit()
    return item


def test_el_sorteo_reparte_en_zonas_parejas(sesion, por_zonas):
    zonas = {}
    for competidor in servicio.competidores_de(sesion, por_zonas):
        zonas.setdefault(competidor.zona_id, []).append(competidor.nombre)
    assert len(zonas) == 2
    assert sorted(len(v) for v in zonas.values()) == [4, 4]


def test_los_dos_sembrados_caen_en_zonas_distintas(sesion, por_zonas):
    """Con los dos mejores en la misma zona, uno queda afuera en la primera
    fase y el torneo pierde la final que la gente vino a ver."""
    por_nombre = {c.nombre: c.zona_id for c in servicio.competidores_de(sesion, por_zonas)}
    assert por_nombre["Pareja 1"] != por_nombre["Pareja 2"]


def test_no_se_larga_el_playoff_con_los_grupos_sin_terminar(sesion, por_zonas):
    with pytest.raises(servicio.EstadoDelTorneo, match="Faltan"):
        servicio.generar_playoff(sesion, por_zonas)


def _jugar_los_grupos(sesion, torneo):
    """Gana siempre el de id más bajo, para que la tabla sea previsible."""
    for partido in servicio.partidos_de(sesion, torneo):
        if partido.etapa is not EtapaTorneo.GRUPOS or partido.finalizado:
            continue
        gana_a = (partido.competidor_a_id or 0) < (partido.competidor_b_id or 0)
        servicio.cargar_resultado(sesion, partido, GANA_A if gana_a else GANA_B)
    sesion.commit()


def test_los_grupos_terminados_no_terminan_el_torneo(sesion, por_zonas):
    """Falta el playoff: darlo por finalizado dejaría un torneo sin campeón."""
    _jugar_los_grupos(sesion, por_zonas)
    assert por_zonas.estado is EstadoTorneo.SORTEADO
    assert servicio.campeon(sesion, por_zonas) is None


def test_el_playoff_no_cruza_dos_de_la_misma_zona(sesion, por_zonas):
    """🔑 Acaban de jugar entre ellos: cruzarlos otra vez le saca la gracia."""
    _jugar_los_grupos(sesion, por_zonas)
    servicio.generar_playoff(sesion, por_zonas)
    sesion.commit()

    zonas = {c.id: c.zona_id for c in servicio.competidores_de(sesion, por_zonas)}
    primera = [
        p
        for p in servicio.partidos_de(sesion, por_zonas)
        if p.etapa is EtapaTorneo.LLAVES and p.ronda == 1
    ]
    assert primera
    for partido in primera:
        assert zonas[partido.competidor_a_id] != zonas[partido.competidor_b_id]


def test_al_playoff_pasan_los_primeros_de_cada_zona(sesion, por_zonas):
    _jugar_los_grupos(sesion, por_zonas)
    esperados = {
        fila.competidor_id
        for tabla in servicio.tabla_de_posiciones(sesion, por_zonas)
        for fila in tabla.filas[:2]
    }
    servicio.generar_playoff(sesion, por_zonas)
    sesion.commit()
    clasificados = {
        x
        for p in servicio.partidos_de(sesion, por_zonas)
        if p.etapa is EtapaTorneo.LLAVES
        for x in (p.competidor_a_id, p.competidor_b_id)
        if x is not None
    }
    assert clasificados == esperados


def test_el_playoff_no_se_arma_dos_veces(sesion, por_zonas):
    _jugar_los_grupos(sesion, por_zonas)
    servicio.generar_playoff(sesion, por_zonas)
    sesion.commit()
    with pytest.raises(servicio.EstadoDelTorneo, match="ya está armado"):
        servicio.generar_playoff(sesion, por_zonas)


def test_una_eliminacion_no_tiene_playoff(sesion, sorteado):
    with pytest.raises(servicio.EstadoDelTorneo, match="por zonas"):
        servicio.generar_playoff(sesion, sorteado)


def test_las_dos_zonas_no_comparten_posicion_en_el_fixture(sesion, por_zonas):
    """🔴 La clave única lleva la zona, y hace falta que la lleve.

    Sin ella, «Zona A · Fecha 1 · orden 0» y «Zona B · Fecha 1 · orden 0» son la
    misma clave y el sorteo de la segunda zona revienta.
    """
    grupos = [
        p for p in servicio.partidos_de(sesion, por_zonas) if p.etapa is EtapaTorneo.GRUPOS
    ]
    posiciones = [(p.zona_id, p.ronda, p.orden) for p in grupos]
    assert len(posiciones) == len(set(posiciones))
    # Y las dos zonas usan efectivamente las mismas (ronda, orden).
    sin_zona = [(p.ronda, p.orden) for p in grupos]
    assert len(sin_zona) != len(set(sin_zona))
