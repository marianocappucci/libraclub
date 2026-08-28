"""El armado del cuadro. Sin base de datos: son funciones puras.

🔑 **Lo que se prueba acá son propiedades, no ejemplos.** Un cuadro mal armado
no falla: dibuja bien, deja jugar y recién en semifinales alguien nota que las
dos cabezas de serie se cruzaron antes de tiempo. Un test que compare contra una
lista escrita a mano sólo protege ese tamaño; los de acá valen para todos.
"""

from __future__ import annotations

import pytest

from app.servicios import fixture

# ── Siembra ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tamano", [2, 4, 8, 16, 32, 64])
def test_la_siembra_es_una_permutacion(tamano):
    """Cada siembra ocupa exactamente una posición del cuadro."""
    orden = fixture.orden_de_siembra(tamano)
    assert sorted(orden) == list(range(tamano))


@pytest.mark.parametrize("tamano", [4, 8, 16, 32])
def test_los_dos_primeros_solo_se_cruzan_en_la_final(tamano):
    """La propiedad que justifica sembrar.

    Si el 1º y el 2º pueden encontrarse antes, ser cabeza de serie no significa
    nada — y es lo que pasa con las posiciones en orden natural.
    """
    cruces = fixture.llaves(tamano)
    rondas = tamano.bit_length() - 1
    donde = _ronda_del_encuentro(cruces, 0, 1)
    assert donde == rondas, f"el 1 y el 2 se cruzan en la ronda {donde} de {rondas}"


@pytest.mark.parametrize("tamano", [8, 16, 32])
def test_las_semis_son_uno_contra_cuatro_y_dos_contra_tres(tamano):
    """El emparejamiento clásico, que es lo que la siembra promete.

    El 1º cruza al **4º** en semifinales y al 2º en la final; el 3º le toca en la
    final también, porque cae en la otra mitad junto al 2º. Es contraintuitivo
    la primera vez —uno espera 1 contra 3 en semis— y por eso está escrito.
    """
    cruces = fixture.llaves(tamano)
    rondas = tamano.bit_length() - 1
    assert _ronda_del_encuentro(cruces, 0, 3) == rondas - 1, "el 1 y el 4, en semis"
    assert _ronda_del_encuentro(cruces, 1, 2) == rondas - 1, "el 2 y el 3, en semis"
    assert _ronda_del_encuentro(cruces, 0, 2) == rondas, "el 1 y el 3, sólo en la final"


@pytest.mark.parametrize("tamano", [8, 16, 32])
def test_los_cuatro_primeros_caen_en_cuartos_distintos(tamano):
    """Ninguno de los cuatro mejores se encuentra con otro antes de semifinales."""
    cruces = fixture.llaves(tamano)
    rondas = tamano.bit_length() - 1
    for uno in range(4):
        for otro in range(uno + 1, 4):
            assert _ronda_del_encuentro(cruces, uno, otro) >= rondas - 1


def _ronda_del_encuentro(cruces, uno: int, otro: int) -> int:
    """En qué ronda pueden encontrarse dos siembras, suponiendo que ganan todo.

    Se sigue el camino de cada una por el cuadro y se busca el primer partido
    que comparten.
    """
    camino = {}
    for quien in (uno, otro):
        actual = next(
            c for c in cruces if quien in (c.a, c.b)
        )
        pasos = [(actual.ronda, actual.orden)]
        while actual.avanza_a is not None:
            pasos.append(actual.avanza_a)
            actual = next(
                c for c in cruces if (c.ronda, c.orden) == actual.avanza_a
            )
        camino[quien] = pasos
    comunes = set(camino[uno]) & set(camino[otro])
    return min(r for r, _ in comunes)


# ── Llaves ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("competidores", range(2, 25))
def test_todos_entran_al_cuadro_una_sola_vez(competidores):
    cruces = fixture.llaves(competidores)
    puestos = [x for c in cruces for x in (c.a, c.b) if x is not None]
    assert sorted(puestos) == sorted(set(puestos)), "alguien entró dos veces"
    assert set(puestos) <= set(range(competidores))


@pytest.mark.parametrize("competidores", range(2, 25))
def test_el_cuadro_termina_en_un_solo_partido(competidores):
    """Hay exactamente una final, y todo camino desemboca en ella."""
    cruces = fixture.llaves(competidores)
    finales = [c for c in cruces if c.avanza_a is None]
    assert len(finales) == 1
    rondas = fixture.tamano_de_llave(competidores).bit_length() - 1
    assert finales[0].ronda == rondas


@pytest.mark.parametrize("competidores", range(2, 25))
def test_cada_partido_alimenta_un_solo_slot(competidores):
    """Dos partidos que escriben en el mismo slot serían un ganador borrado."""
    cruces = fixture.llaves(competidores)
    destinos = [
        (c.avanza_a, c.avanza_a_slot) for c in cruces if c.avanza_a is not None
    ]
    assert len(destinos) == len(set(destinos))


@pytest.mark.parametrize("competidores", range(2, 25))
def test_cada_slot_vacio_lo_llena_alguien(competidores):
    """Ningún partido queda esperando a un ganador que nadie le manda.

    🔴 Es el reverso del test de arriba y hace falta igual: aquel encuentra dos
    partidos escribiendo en el mismo lugar, y éste, un lugar donde no escribe
    nadie — que es un partido que nunca se puede jugar y un cuadro trabado.
    """
    cruces = fixture.llaves(competidores)
    vacios = {
        (c.ronda, c.orden, slot)
        for c in cruces
        for slot, quien in zip(fixture.SLOTS, (c.a, c.b), strict=True)
        if quien is None
    }
    llenados = {
        (*c.avanza_a, c.avanza_a_slot) for c in cruces if c.avanza_a is not None
    }
    assert vacios == llenados


@pytest.mark.parametrize(
    "competidores,partidos",
    # Un cuadro de N se define en N-1 partidos, **con byes o sin ellos**: cada
    # partido elimina exactamente a uno y hay que eliminar a todos menos al
    # campeón. Si este número no da, sobran partidos fantasma o falta alguno.
    [(2, 1), (3, 2), (4, 3), (5, 4), (6, 5), (7, 6), (8, 7), (13, 12), (16, 15)],
)
def test_un_cuadro_de_n_son_n_menos_un_partidos(competidores, partidos):
    assert len(fixture.llaves(competidores)) == partidos


def test_el_bye_le_toca_a_las_mejores_siembras():
    """Con 6 en un cuadro de 8, descansan el 1º y el 2º.

    Es la regla de cualquier torneo: el que sembró mejor descansa. Si los byes
    cayeran en las siembras altas, ser cabeza de serie sería un castigo.
    """
    cruces = fixture.llaves(6)
    primera = [c for c in cruces if c.ronda == 1]
    juegan = {x for c in primera for x in (c.a, c.b)}
    assert 0 not in juegan and 1 not in juegan
    # Y aparecen en la ronda siguiente, ya puestos en el cuadro.
    segunda = {x for c in cruces if c.ronda == 2 for x in (c.a, c.b)}
    assert {0, 1} <= segunda


def test_un_bye_no_genera_partido():
    """Con 5 competidores hay 4 partidos, no 8.

    🔑 La alternativa —crear el partido igual y darlo por ganado— llena la
    pantalla de encuentros que nadie va a jugar.
    """
    cruces = fixture.llaves(5)
    assert len(cruces) == 4
    assert all(c.a is not None or c.ronda > 1 for c in cruces)
    # Nadie juega contra un hueco.
    primera = [c for c in cruces if c.ronda == 1]
    assert all(c.a is not None and c.b is not None for c in primera)


@pytest.mark.parametrize("cuantos", [0, 1])
def test_una_llave_necesita_dos(cuantos):
    with pytest.raises(ValueError):
        fixture.llaves(cuantos)


@pytest.mark.parametrize("tamano", [0, 1, 3, 6, 12])
def test_el_tamano_de_una_llave_es_potencia_de_dos(tamano):
    with pytest.raises(ValueError):
        fixture.orden_de_siembra(tamano)


@pytest.mark.parametrize(
    "competidores,tamano", [(2, 2), (3, 4), (4, 4), (5, 8), (8, 8), (9, 16), (16, 16)]
)
def test_el_cuadro_se_redondea_hacia_arriba(competidores, tamano):
    assert fixture.tamano_de_llave(competidores) == tamano


# ── Todos contra todos ──────────────────────────────────────────────────────


@pytest.mark.parametrize("competidores", range(2, 13))
def test_todos_juegan_contra_todos_exactamente_una_vez(competidores):
    fechas = fixture.ronda_robin(competidores)
    cruces = [tuple(sorted(par)) for fecha in fechas for par in fecha]
    esperados = {
        (a, b)
        for a in range(competidores)
        for b in range(a + 1, competidores)
    }
    assert sorted(cruces) == sorted(esperados)


@pytest.mark.parametrize("competidores", range(2, 13))
def test_nadie_juega_dos_veces_en_la_misma_fecha(competidores):
    """La propiedad que justifica que existan las fechas.

    🔴 Sin ella, generar los cruces con dos `for` anidados también daría "todos
    contra todos" — pero con el mismo competidor jugando cuatro partidos el
    mismo día, que en una cancha es imposible.
    """
    for numero, fecha in enumerate(fixture.ronda_robin(competidores), start=1):
        quienes = [x for par in fecha for x in par]
        assert len(quienes) == len(set(quienes)), f"alguien repite en la fecha {numero}"


@pytest.mark.parametrize(
    "competidores,fechas", [(2, 1), (3, 3), (4, 3), (5, 5), (6, 5), (8, 7)]
)
def test_cuantas_fechas_tiene_una_liga(competidores, fechas):
    """Par: N-1 fechas. Impar: N, porque uno descansa cada vez."""
    assert len(fixture.ronda_robin(competidores)) == fechas


def test_con_impares_descansa_uno_distinto_cada_fecha():
    fechas = fixture.ronda_robin(5)
    descansan = []
    for fecha in fechas:
        juegan = {x for par in fecha for x in par}
        descansan.append((set(range(5)) - juegan).pop())
    assert sorted(descansan) == [0, 1, 2, 3, 4]


def test_no_siempre_el_mismo_del_lado_a():
    """En la pantalla el lado `a` va arriba; uno siempre primero se lee raro."""
    fechas = fixture.ronda_robin(4)
    arriba = [par[0] for fecha in fechas for par in fecha]
    assert len(set(arriba)) > 1


# ── Clasificados de zona ────────────────────────────────────────────────────


@pytest.mark.parametrize("zonas", [2, 3, 4, 8])
def test_dos_de_la_misma_zona_no_se_cruzan_en_el_playoff(zonas):
    """La razón de existir de `orden_de_clasificados`.

    Con los clasificados en el orden obvio —1ºA, 2ºA, 1ºB, 2ºB…— el cuadro
    enfrenta al 1º con el 2º de su propia zona, que acaban de jugar entre ellos.
    """
    # Competidor `z*10 + p`: la decena es la zona.
    por_zona = [[z * 10, z * 10 + 1] for z in range(zonas)]
    siembras = fixture.orden_de_clasificados(por_zona)
    assert sorted(siembras) == sorted(x for zona in por_zona for x in zona)

    for cruce in fixture.llaves(len(siembras)):
        if cruce.a is None or cruce.b is None:
            continue
        assert siembras[cruce.a] // 10 != siembras[cruce.b] // 10, (
            f"cruce de la misma zona: {siembras[cruce.a]} vs {siembras[cruce.b]}"
        )


@pytest.mark.parametrize("zonas", [2, 3, 4, 8])
def test_con_un_clasificado_por_zona_pasan_los_ganadores(zonas):
    por_zona = [[z * 10] for z in range(zonas)]
    assert fixture.orden_de_clasificados(por_zona) == [z * 10 for z in range(zonas)]


def test_no_se_soportan_tres_clasificados_por_zona():
    """El límite es explícito, no un cruce que parezca correcto y no lo sea."""
    with pytest.raises(ValueError, match="1 o 2"):
        fixture.orden_de_clasificados([[1, 2, 3], [4, 5, 6]])


def test_las_zonas_tienen_que_clasificar_lo_mismo():
    with pytest.raises(ValueError, match="misma cantidad"):
        fixture.orden_de_clasificados([[1, 2], [3]])


# ── Nombres de ronda ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ronda,rondas,nombre",
    [
        (1, 1, "Final"),
        (2, 2, "Final"),
        (1, 2, "Semifinal"),
        (1, 3, "Cuartos de final"),
        (2, 3, "Semifinal"),
        (1, 4, "Octavos de final"),
        (1, 5, "16avos de final"),
        (1, 6, "32avos de final"),
    ],
)
def test_como_se_llama_cada_ronda(ronda, rondas, nombre):
    """🔑 El nombre sale de la **distancia a la final**, no del número de ronda.

    En un cuadro de 8 la ronda 1 son cuartos; en uno de 16, octavos. Nombrarla
    por su número diría "Ronda 1" en los dos y nadie escribe eso en un afiche.
    """
    assert fixture.nombre_de_ronda(ronda, rondas) == nombre
