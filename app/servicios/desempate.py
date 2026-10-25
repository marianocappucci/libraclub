"""El orden de una zona de pádel o de tenis. **Funciones puras, sin base.**

Las posiciones de una zona americana se definen, en este orden (ADR-024):

1. **partidos ganados** (en pádel no hay empates, así que son los puntos);
2. si quedan **exactamente dos** empatados, **el resultado entre ellos**;
3. la **diferencia de sets**;
4. la **diferencia de games**;
5. los **games a favor**;
6. el nombre, sólo para que el orden sea estable entre consultas.

🔴 **El cara a cara vale entre dos, no entre tres.** Con tres empatados en
partidos ganados, el resultado entre ellos es un triángulo (A le ganó a B, B a C
y C a A) que no ordena a nadie; ahí se sigue con la diferencia de sets. Por eso
el cara a cara se aplica a cada grupo de empatados **de a dos**, y a los de tres
o más se los ordena por el resto de los criterios.

En fútbol y en el resto de los deportes no se usa nada de esto: sigue el orden de
siempre (puntos, diferencia, a favor) en `servicios/torneos.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol


class Fila(Protocol):
    """Lo que el orden necesita saber de cada competidor de la zona."""

    competidor_id: int
    nombre: str
    puntos: int
    diferencia_sets: int | None
    diferencia: int
    a_favor: int



def _clave(fila: Fila) -> tuple:
    return (
        -fila.puntos,
        -(fila.diferencia_sets or 0),
        -fila.diferencia,
        -fila.a_favor,
        fila.nombre,
    )


def ordenar_zona[F: Fila](
    filas: Sequence[F],
    ganador_entre: Callable[[int, int], int | None],
) -> list[F]:
    """Ordena las filas de una zona con sets.

    `ganador_entre(x, y)` devuelve el `competidor_id` de quien le ganó al otro, o
    `None` si todavía no jugaron entre ellos.
    """
    base = sorted(filas, key=_clave)
    salida: list[F] = []
    inicio = 0
    while inicio < len(base):
        fin = inicio
        while fin < len(base) and base[fin].puntos == base[inicio].puntos:
            fin += 1
        grupo = base[inicio:fin]
        if len(grupo) == 2:
            ganador = ganador_entre(grupo[0].competidor_id, grupo[1].competidor_id)
            if ganador == grupo[1].competidor_id:
                grupo = [grupo[1], grupo[0]]
        salida.extend(grupo)
        inicio = fin
    return salida
