"""El armado del fixture. **Funciones puras, sin base de datos.**

Está separado de `servicios/torneos.py` a propósito: el sorteo de una llave de
16 con tres byes es la parte que se puede equivocar en silencio —una llave mal
armada no falla, sólo hace que dos cabezas de serie se crucen en octavos— y
probarla contra la base costaría un torneo entero por caso. Acá se prueba con
una lista de enteros.

Los competidores se manejan por **índice** (0…n-1), ya ordenados por siembra.
Quién es cada índice es problema del que llama.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Los dos slots de un partido. `a` es el que va arriba en el dibujo de la
#: llave; no significa localía —en un complejo se juega todo en casa—.
SLOTS = ("a", "b")


@dataclass(frozen=True, slots=True)
class Cruce:
    """Un partido del fixture, todavía sin cancha ni horario.

    `a` y `b` son el índice del competidor cuando ya se sabe quién juega
    (primera ronda de la llave, o cualquier partido de zona), y `None` cuando
    depende de un partido anterior. Quién lo alimenta no se guarda acá sino en
    el `avanza_a` del partido de origen: así el que carga un resultado sabe a
    dónde escribir el ganador sin tener que buscar quién lo esperaba.
    """

    ronda: int
    orden: int
    a: int | None
    b: int | None
    #: `(ronda, orden)` del partido al que pasa el ganador. `None` en la final.
    avanza_a: tuple[int, int] | None = None
    #: En qué slot del partido siguiente cae el ganador.
    avanza_a_slot: str | None = None


def orden_de_siembra(tamano: int) -> list[int]:
    """Las posiciones de una llave de `tamano`, en orden de siembra.

    Devuelve, para cada posición del dibujo, **qué número de siembra la ocupa**.
    Para 8: `[0, 7, 3, 4, 1, 6, 2, 5]` — o sea 1º contra 8º, 4º contra 5º, 2º
    contra 7º, 3º contra 6º.

    🔑 **Esto es lo que hace que las cabezas de serie no se crucen antes de
    tiempo.** Con las posiciones en orden natural (0, 1, 2, 3…) el 1º y el 2º
    juegan en la primera ronda y el torneo se termina ahí. La construcción por
    reflejo —cada ronda espeja la anterior— garantiza que el 1º y el 2º sólo se
    puedan encontrar en la final, el 1º y el 3º en semis, y así.
    """
    if tamano < 2 or tamano & (tamano - 1):
        raise ValueError("El tamaño de una llave es una potencia de 2 y al menos 2.")
    orden = [0]
    while len(orden) < tamano:
        espejo = len(orden) * 2 - 1
        orden = [x for posicion in orden for x in (posicion, espejo - posicion)]
    return orden


def tamano_de_llave(competidores: int) -> int:
    """La potencia de 2 que aloja a todos. 6 competidores → llave de 8."""
    tamano = 2
    while tamano < competidores:
        tamano *= 2
    return tamano


def llaves(competidores: int) -> list[Cruce]:
    """La llave completa de eliminación directa, con byes.

    🔑 **Un bye no genera un partido.** El que sortea con suerte aparece
    directamente en la segunda ronda, que es como se dibuja un cuadro de verdad.
    La alternativa —crear el partido igual y marcarlo ganado— llena la pantalla
    de «próximos partidos» con encuentros que nadie va a jugar, y obliga a que
    todo lo que recorra el fixture sepa distinguirlos.

    Los byes caen sobre las siembras más bajas —el 1º, el 2º…— porque
    `orden_de_siembra` las pone enfrentadas a las más altas, que son las que no
    existen. Es la regla de cualquier cuadro: el que sembró mejor descansa.

    La ronda 1 es la primera que se juega y la última es la final. Cuántas son
    depende de `tamano_de_llave` y **no** de cuántos partidos tenga la ronda 1:
    con byes tiene menos.
    """
    if competidores < 2:
        raise ValueError("Una llave necesita al menos dos competidores.")

    tamano = tamano_de_llave(competidores)
    #: Cada posición del cuadro: qué la ocupa, o `None` si esa siembra no existe.
    #: `("c", i)` es el competidor `i`; `("g", ronda, orden)` es "el ganador de".
    posiciones: list[tuple | None] = [
        ("c", siembra) if siembra < competidores else None
        for siembra in orden_de_siembra(tamano)
    ]

    cruces: list[Cruce] = []
    rondas = tamano.bit_length() - 1
    for ronda in range(1, rondas + 1):
        siguiente: list[tuple | None] = []
        orden = 0
        for izquierda, derecha in zip(posiciones[::2], posiciones[1::2], strict=True):
            if izquierda is None or derecha is None:
                # Bye: pasa el que está —o nadie, si faltaban los dos— sin
                # partido y sin dejar rastro en el cuadro.
                siguiente.append(izquierda if izquierda is not None else derecha)
                continue
            cruces.append(
                Cruce(
                    ronda=ronda,
                    orden=orden,
                    a=izquierda[1] if izquierda[0] == "c" else None,
                    b=derecha[1] if derecha[0] == "c" else None,
                )
            )
            siguiente.append(("g", ronda, orden))
            orden += 1
        posiciones = siguiente

    return _enlazar(cruces)


def _enlazar(cruces: list[Cruce]) -> list[Cruce]:
    """Completa el `avanza_a` de cada cruce mirando quién lo espera.

    🔴 **Segunda pasada y no al construir**, porque el orden del partido
    siguiente no es deducible en el momento: con byes, la ronda que viene puede
    tener menos partidos que posiciones el cuadro, así que el índice de destino
    recién se sabe cuando esa ronda terminó de armarse.

    Los slots vacíos de la ronda `r+1` —los `None`, que son los que espera un
    ganador— se consumen **en orden**, que es el mismo en que se generaron los
    partidos de la ronda `r`. Por eso alcanza con un `zip`: no hay que buscar
    nada, la correspondencia es posicional por construcción.
    """
    por_ronda: dict[int, list[Cruce]] = {}
    for cruce in cruces:
        por_ronda.setdefault(cruce.ronda, []).append(cruce)

    destinos: dict[tuple[int, int], tuple[int, int, str]] = {}
    for ronda in sorted(por_ronda)[:-1]:
        libres = [
            (siguiente.ronda, siguiente.orden, slot)
            for siguiente in por_ronda.get(ronda + 1, [])
            for slot, quien in zip(SLOTS, (siguiente.a, siguiente.b), strict=True)
            if quien is None
        ]
        # `strict=True`: cada partido de esta ronda alimenta exactamente un
        # slot vacío de la siguiente. Si eso deja de ser cierto, el cuadro está
        # mal armado y hay que enterarse acá y no en la pantalla.
        for cruce, destino in zip(por_ronda[ronda], libres, strict=True):
            destinos[(cruce.ronda, cruce.orden)] = destino

    salida = []
    for cruce in cruces:
        destino = destinos.get((cruce.ronda, cruce.orden))
        salida.append(
            Cruce(
                ronda=cruce.ronda,
                orden=cruce.orden,
                a=cruce.a,
                b=cruce.b,
                avanza_a=(destino[0], destino[1]) if destino else None,
                avanza_a_slot=destino[2] if destino else None,
            )
        )
    return salida


def ronda_robin(competidores: int) -> list[list[tuple[int, int]]]:
    """Todos contra todos, por fecha. Método del círculo.

    Devuelve una lista de fechas; cada fecha es la lista de cruces que se juegan
    ese día. Con un número impar de competidores uno **descansa** cada fecha, y
    eso sale solo agregando un competidor fantasma: los cruces contra él no se
    generan.

    🔑 Las fechas importan aunque el complejo juegue todo el mismo día: son las
    que garantizan que nadie juegue dos partidos a la vez, que es justo lo que
    se rompe si los cruces se generan con dos `for` anidados.
    """
    if competidores < 2:
        raise ValueError("Una zona necesita al menos dos competidores.")

    ruedan: list[int | None] = list(range(competidores))
    if competidores % 2:
        ruedan.append(None)  # el que descansa
    total = len(ruedan)

    fechas = []
    for numero in range(total - 1):
        cruces = [
            # Se alterna el orden por fecha para que el mismo competidor no
            # quede siempre del lado `a`: en la pantalla `a` va arriba, y una
            # tabla donde uno aparece siempre primero se lee como un privilegio.
            (arriba, abajo) if numero % 2 == 0 else (abajo, arriba)
            for arriba, abajo in zip(ruedan[: total // 2], ruedan[total // 2 :][::-1], strict=True)
            if arriba is not None and abajo is not None
        ]
        fechas.append(cruces)
        # Rota todos menos el primero. Es lo que hace que en `total - 1` fechas
        # cada uno juegue contra todos exactamente una vez.
        ruedan = [ruedan[0], ruedan[-1], *ruedan[1:-1]]
    return fechas


def orden_de_clasificados(por_zona: list[list[int]]) -> list[int]:
    """Los clasificados de cada zona, ordenados para que el cuadro los cruce.

    `por_zona[z]` son los competidores de la zona `z` **ya ordenados por la
    tabla**: el primero es el que salió 1º.

    🔴 **El problema que resuelve: dos de la misma zona no se pueden cruzar en
    la primera ronda del playoff.** Ya se jugaron entre ellos y el playoff
    perdería la gracia. Poner los clasificados en el orden obvio —1ºA, 2ºA,
    1ºB, 2ºB…— hace exactamente eso, porque `orden_de_siembra` enfrenta la
    siembra `k` con la `K-1-k`.

    La solución es elegir la siembra de cada uno para que ese enfrentamiento
    caiga cruzado: el 1º de la zona `z` termina jugando contra el 2º de la zona
    siguiente. Con dos zonas queda 1ºA–2ºB y 1ºB–2ºA, que es lo que arma
    cualquiera a mano.

    ⚠️ **Soporta 1 o 2 clasificados por zona**, y la validación de eso vive en
    `servicios/torneos.py`. Con tres o más, la regla de cruce deja de ser una
    rotación y pasa a depender del reglamento del torneo —hay varios— así que se
    prefiere no soportarlo antes que soportarlo de una forma que parezca
    correcta y no lo sea.
    """
    zonas = len(por_zona)
    if not zonas:
        raise ValueError("No hay zonas.")
    cuantos = len(por_zona[0])
    if any(len(z) != cuantos for z in por_zona):
        raise ValueError("Todas las zonas tienen que clasificar la misma cantidad.")
    if cuantos not in (1, 2):
        raise ValueError("Sólo se soportan 1 o 2 clasificados por zona.")

    if cuantos == 1:
        # Los ganadores de zona y nada más: el cuadro los siembra por orden y no
        # hay forma de que dos de la misma zona se crucen —hay uno solo—.
        return [zona[0] for zona in por_zona]

    total = zonas * 2
    siembras: list[int] = [zona[0] for zona in por_zona]
    # Las siembras altas se llenan al revés para que la `k` y la `K-1-k` —las
    # que el cuadro enfrenta— caigan en zonas distintas. Ver el docstring.
    siembras += [por_zona[(-posicion) % zonas][1] for posicion in range(zonas, total)]
    return siembras


#: Cómo se llama cada ronda según lo que falte para la final. La clave es la
#: **distancia a la final**, no el número de ronda: en una llave de 8 la ronda 1
#: son cuartos, y en una de 16 es octavos.
_NOMBRES = {0: "Final", 1: "Semifinal", 2: "Cuartos de final", 3: "Octavos de final"}


def nombre_de_ronda(ronda: int, rondas: int) -> str:
    """«Cuartos de final», «Semifinal», «Final»."""
    faltan = rondas - ronda
    if faltan in _NOMBRES:
        return _NOMBRES[faltan]
    # 16avos, 32avos… Se arma en vez de listarse: una llave de 64 es rara pero
    # no imposible, y un `KeyError` en la pantalla del fixture sería peor.
    return f"{2 ** faltan}avos de final"
