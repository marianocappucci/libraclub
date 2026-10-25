"""El marcador de un set de pádel o de tenis. **Funciones puras, sin base.**

Un torneo puede decir a cuántos games se juega cada set (`Torneo.games_por_set`,
ADR-024) y entonces `6-5` o `9-10` no son marcadores posibles. Está separado de
`servicios/torneos.py` por lo mismo que `fixture.py`: la regla se prueba con
números, no con un torneo entero por caso.

Las dos reglas que se juegan en los americanos de club:

- **A 6 games**: se gana 6-0, 6-1, 6-2, 6-3 o 6-4. Con 5-5 hay que llegar a 7-5, y
  con 6-6 se juega un tie-break que deja el set en 7-6.
- **A 9 games**: se gana de 9-0 a 9-7 por diferencia de dos. Con 8-8 se juega un
  tie-break y el set queda 9-8. No existe el 10-8: el tie-break está para eso.

🔑 **El tie-break no se anota**: el set queda 7-6 o 9-8 y los puntos del
tie-break no suman games. Es lo que hace que la diferencia de games de la tabla
cuente lo mismo que se juega en la cancha.
"""

from __future__ import annotations

#: Los tamaños de set que se juegan. Un tercero se agrega acá y en el CHECK de la
#: base (`ck_torneos_games_por_set`), y en ningún otro lado.
GAMES_VALIDOS = (6, 9)


def marcador_valido(games: int, a: int, b: int) -> bool:
    """Si `a`–`b` puede ser el resultado final de un set a `games` games."""
    ganador, perdedor = max(a, b), min(a, b)
    if games == 6:
        return (ganador == 6 and perdedor <= 4) or (ganador == 7 and perdedor in (5, 6))
    if games == 9:
        return ganador == 9 and perdedor <= 8
    raise ValueError(f"No se juegan sets a {games} games.")


def regla(games: int) -> str:
    """La regla en una frase, para el mensaje de error y para la pantalla."""
    if games == 6:
        return (
            "un set a 6 games termina 6-0, 6-1, 6-2, 6-3, 6-4, 7-5 o 7-6 "
            "(con tie-break en 6-6)"
        )
    if games == 9:
        return (
            "un set a 9 games termina de 9-0 a 9-8 "
            "(el 9-8 sale del tie-break en 8-8)"
        )
    raise ValueError(f"No se juegan sets a {games} games.")


def error_del_set(games: int, numero: int, a: int, b: int) -> str | None:
    """El motivo por el que el set no es válido, o `None` si lo es."""
    if marcador_valido(games, a, b):
        return None
    if a == b:
        return (
            f"El set {numero} no puede terminar {a}-{b}: {regla(games)}."
        )
    return f"El set {numero} ({a}-{b}) no es un resultado posible: {regla(games)}."
