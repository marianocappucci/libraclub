"""Huso horario y formato de fecha del ecosistema.

Argentina, UTC-3 fijo, sin horario de verano. La base guarda `timestamptz`; el
formateo `dd-mm-aaaa` es sólo de presentación y vive **acá**, no repetido por
vista.

`ahora()` y `hoy()` delegan en `libracore.fechas` (ADR-070, LibraCore v1.182.0):
un solo reloj de Argentina para la fecha de negocio de todo el producto y del
motor, el mismo que estampa las tablas del core. No se define otro acá.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from libracore import fechas

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
UTC = ZoneInfo("UTC")


def ahora() -> datetime:
    """Momento actual, consciente de zona horaria (hora de Argentina)."""
    return fechas.ahora()


def hoy() -> date:
    """El día de hoy en Argentina: la fecha de negocio (`libracore.fechas.hoy()`)."""
    return fechas.hoy()


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
