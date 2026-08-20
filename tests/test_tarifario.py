"""Resolución de tarifas: la más específica gana, y la hora es local."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

import pytest

from app.models.enums import AlcanceDia
from app.models.maestros import Feriado
from app.models.tarifas import Tarifa
from app.servicios import tarifario
from app.tiempo import TZ, UTC


def _tarifa(sucursal_id, **kwargs) -> Tarifa:
    base = dict(
        sucursal_id=sucursal_id,
        nombre="tarifa",
        alcance_dia=AlcanceDia.TODOS,
        hora_desde=time(0, 0),
        hora_hasta=time(23, 59),
        precio=Decimal("1000.00"),
        sena_porcentaje=0,
    )
    base.update(kwargs)
    return Tarifa(**base)


def test_sin_tarifa_levanta_en_vez_de_devolver_cero(sesion, cancha):
    """Una reserva de $0 entra a la caja y descuadra el cierre.

    Levantar es lo que hace que el operador cargue la franja que falta hoy, en
    vez de que aparezca a fin de mes como una diferencia que nadie explica.
    """
    with pytest.raises(tarifario.SinTarifa):
        tarifario.resolver(sesion, cancha, datetime(2026, 9, 1, 20, 0, tzinfo=TZ))


def test_la_franja_es_hora_local_no_utc(sesion, cancha, sucursal):
    """🔴 El caso que rompe si se lee el `.hour` de un datetime en UTC.

    Las 20:00 de Argentina son las 23:00 UTC. Con la franja nocturna 18:00-23:59,
    resolver contra UTC daría 23:00 —que también entra— pero un turno de las
    21:00 locales sería medianoche UTC y **se caería de la franja**. Se prueba
    justamente ese: 21:00 local = 00:00 UTC del día siguiente.
    """
    sesion.add(
        _tarifa(
            sucursal.id,
            nombre="Nocturna",
            hora_desde=time(18, 0),
            hora_hasta=time(23, 59),
            precio=Decimal("15000.00"),
        )
    )
    sesion.commit()

    momento_local = datetime(2026, 9, 1, 21, 0, tzinfo=TZ)
    assert momento_local.astimezone(UTC).hour == 0, "el caso de prueba dejó de ser el que era"

    tarifa = tarifario.resolver(sesion, cancha, momento_local)
    assert tarifa.precio == Decimal("15000.00")


def test_la_de_la_cancha_le_gana_a_la_de_la_sucursal(sesion, cancha, sucursal):
    sesion.add(_tarifa(sucursal.id, nombre="Sucursal", precio=Decimal("8000.00")))
    sesion.add(
        _tarifa(
            sucursal.id, nombre="Cancha 1", cancha_id=cancha.id, precio=Decimal("12000.00")
        )
    )
    sesion.commit()

    tarifa = tarifario.resolver(sesion, cancha, datetime(2026, 9, 1, 20, 0, tzinfo=TZ))
    assert tarifa.nombre == "Cancha 1"


def test_el_feriado_le_gana_al_dia_de_semana(sesion, cancha, sucursal, un_martes):
    """Y la del martes **no** aplica ese día, aunque el feriado caiga martes.

    Si aplicara, el operador que cargó "feriado: $X" vería el precio de un martes
    común cada vez que el feriado cae martes, y sólo se enteraría por un reclamo.
    """
    assert un_martes.weekday() == 1
    sesion.add(
        _tarifa(
            sucursal.id,
            nombre="Martes",
            alcance_dia=AlcanceDia.DIA_SEMANA,
            dia_semana=1,
            precio=Decimal("9000.00"),
        )
    )
    sesion.add(
        _tarifa(
            sucursal.id,
            nombre="Feriado",
            alcance_dia=AlcanceDia.FERIADO,
            precio=Decimal("20000.00"),
        )
    )
    sesion.add(Feriado(sucursal_id=sucursal.id, dia=un_martes, nombre="Prueba"))
    sesion.commit()

    momento = datetime(un_martes.year, un_martes.month, un_martes.day, 20, 0, tzinfo=TZ)
    tarifa = tarifario.resolver(sesion, cancha, momento)
    assert tarifa.nombre == "Feriado"

    # Y el control: el martes siguiente, sin feriado, gana la del martes.
    otro_martes = momento.replace(day=momento.day + 7)
    assert tarifario.resolver(sesion, cancha, otro_martes).nombre == "Martes"


def test_prioridad_desempata_por_encima_de_la_especificidad(sesion, cancha, sucursal):
    """Es el escape para la promoción que tiene que ganarle a la de la cancha.

    Sin `prioridad`, la única forma de que una promoción de sucursal le gane a
    una tarifa de cancha sería borrar la de la cancha — y después habría que
    acordarse de volver a cargarla.
    """
    sesion.add(
        _tarifa(sucursal.id, nombre="Cancha", cancha_id=cancha.id, precio=Decimal("12000.00"))
    )
    sesion.add(
        _tarifa(sucursal.id, nombre="Promo", precio=Decimal("6000.00"), prioridad=10)
    )
    sesion.commit()

    assert tarifario.resolver(
        sesion, cancha, datetime(2026, 9, 1, 20, 0, tzinfo=TZ)
    ).nombre == "Promo"


def test_la_vigencia_saca_la_tarifa_vencida(sesion, cancha, sucursal, un_martes):
    from datetime import date

    sesion.add(
        _tarifa(
            sucursal.id,
            nombre="Temporada vieja",
            precio=Decimal("5000.00"),
            vigente_hasta=date(2026, 8, 31),
        )
    )
    sesion.add(_tarifa(sucursal.id, nombre="Actual", precio=Decimal("11000.00")))
    sesion.commit()

    momento = datetime(un_martes.year, un_martes.month, un_martes.day, 20, 0, tzinfo=TZ)
    assert tarifario.resolver(sesion, cancha, momento).nombre == "Actual"


def test_la_sena_redondea_como_la_calculadora(sesion, cancha, sucursal):
    """`ROUND_HALF_UP`, no el `HALF_EVEN` que trae `Decimal` de fábrica.

    Con el default, 0.005 redondea al par y el encargado que hizo la cuenta a
    mano ve un centavo de diferencia. Se elige un precio que caiga justo en el
    medio para que el test distinga las dos reglas.
    """
    sesion.add(_tarifa(sucursal.id, precio=Decimal("1000.05"), sena_porcentaje=50))
    sesion.commit()

    precio, sena = tarifario.precio_y_sena(
        sesion, cancha, datetime(2026, 9, 1, 20, 0, tzinfo=TZ)
    )
    assert precio == Decimal("1000.05")
    # 1000.05 * 50% = 500.025 → 500.03 con HALF_UP; 500.02 con HALF_EVEN.
    assert sena == Decimal("500.03")


def test_una_tarifa_de_otra_sucursal_no_aplica(sesion, cancha, sucursal):
    from app.models.maestros import Sucursal

    otra = Sucursal(nombre="Complejo Norte")
    sesion.add(otra)
    sesion.commit()
    sesion.add(_tarifa(otra.id, nombre="De la otra", precio=Decimal("1.00")))
    sesion.commit()

    with pytest.raises(tarifario.SinTarifa):
        tarifario.resolver(sesion, cancha, datetime(2026, 9, 1, 20, 0, tzinfo=TZ))
