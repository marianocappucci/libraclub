"""Huso horario y formato de fecha del ecosistema.

Argentina, UTC-3 fijo, sin horario de verano. La base guarda `timestamptz`; el
formateo `dd-mm-aaaa` es sólo de presentación y vive **acá**, no repetido por
vista.

> Cuando LibraCore amplíe su alcance en este producto, `ahora()` pasa a delegar
> en su `_ar_now()`. Se define local para no atarlo antes de tiempo.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
UTC = ZoneInfo("UTC")


def ahora() -> datetime:
    """Momento actual, consciente de zona horaria."""
    return datetime.now(TZ)


def hoy() -> date:
    return ahora().date()


def a_local(valor: datetime) -> datetime:
    """El mismo instante, expresado en hora de Argentina.

    🔴 Es la función que hace correcto el tarifario. Una franja "18:00 a 23:00"
    es **hora de pared del complejo**, no un instante: resolverla contra el
    `.hour` de un datetime en UTC corre el turno tres horas y le cobra tarifa de
    tarde a uno de las 21:00. Un datetime naive se toma como UTC, que es lo que
    devuelve psycopg si alguna columna se declaró sin zona por error.
    """
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)
    return valor.astimezone(TZ)


def dia_de_semana(valor: datetime) -> int:
    """0 = lunes … 6 = domingo, **en hora local**.

    Un turno de las 22:00 del sábado es sábado para el complejo aunque en UTC ya
    sea domingo. Sin esto, las tarifas de fin de semana se caen los sábados a la
    noche — que es justamente la franja más cara.
    """
    return a_local(valor).weekday()


def hora_local(valor: datetime) -> time:
    """La hora de pared del complejo. Ver `a_local`."""
    return a_local(valor).timetz().replace(tzinfo=None)


def formatear_fecha(valor: date | None) -> str:
    """`dd-mm-aaaa`. Presentación únicamente: las APIs siguen en ISO 8601."""
    return valor.strftime("%d-%m-%Y") if valor else ""


def formatear_fecha_hora(valor: datetime | None) -> str:
    """`dd-mm-aaaa HH:MM`, reloj de 24 h, en hora local."""
    if valor is None:
        return ""
    return a_local(valor).strftime("%d-%m-%Y %H:%M")
