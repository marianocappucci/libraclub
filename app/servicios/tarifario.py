"""Resolución del precio de un turno.

No importa FastAPI: se prueba llamándolo, sin levantar la aplicación.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import AlcanceDia
from app.models.maestros import Cancha, Feriado
from app.models.tarifas import Tarifa
from app.tiempo import a_local, dia_de_semana, hora_local


class SinTarifa(Exception):
    """No hay ninguna tarifa que cubra ese turno.

    Es un error del **operador**, no del sistema: la franja de las 7 de la
    mañana existe y nadie le puso precio. Se levanta en vez de devolver cero
    porque una reserva de $0 entra a la caja y descuadra el cierre, y nadie mira
    de dónde salió hasta fin de mes.
    """


def es_feriado(sesion: Session, sucursal_id: int, momento: datetime) -> Feriado | None:
    """El feriado de esa sucursal ese día, si lo hay.

    El día se calcula en **hora local**: un turno de las 22:00 del 24 de
    diciembre es el 24 para el complejo aunque en UTC ya sea 25.
    """
    dia = a_local(momento).date()
    return sesion.scalars(
        select(Feriado).where(Feriado.sucursal_id == sucursal_id, Feriado.dia == dia)
    ).first()


def _especificidad(tarifa: Tarifa) -> tuple[int, int, int, int]:
    """Cuánto "gana" una tarifa frente a otra. La mayor tupla gana.

    El orden de las claves **es la regla de negocio**, porque una tupla se
    compara de izquierda a derecha y la primera decide:

    1. `prioridad` — el escape manual. Va primero a propósito: existe para que
       una promoción de sucursal pueda ganarle a una tarifa de cancha, y si
       fuera sólo un desempate no podría. Default `0`, así que en el uso normal
       no interviene y deciden las dos claves de abajo.
    2. Alcance del día: `feriado` > `dia_semana` > `todos`.
    3. Cancha específica > toda la sucursal.
    4. El id, como desempate final. **No es decorativo**: sin él, dos tarifas
       idénticas devolverían una u otra según el orden que le haya tocado al
       planner esa vez, y el precio de la misma cancha cambiaría entre dos
       requests seguidos sin que nadie tocara nada.
    """
    por_dia = {AlcanceDia.TODOS: 0, AlcanceDia.DIA_SEMANA: 1, AlcanceDia.FERIADO: 2}
    return (
        tarifa.prioridad,
        por_dia[tarifa.alcance_dia],
        1 if tarifa.cancha_id is not None else 0,
        tarifa.id,
    )


def candidatas(sesion: Session, cancha: Cancha, comienza_at: datetime) -> list[Tarifa]:
    """Todas las tarifas que cubren ese turno, sin ordenar."""
    local = a_local(comienza_at)
    dia = local.date()
    hora = hora_local(comienza_at)
    weekday = dia_de_semana(comienza_at)
    feriado = es_feriado(sesion, cancha.sucursal_id, comienza_at)

    filas = sesion.scalars(
        select(Tarifa).where(
            Tarifa.sucursal_id == cancha.sucursal_id,
            Tarifa.activa.is_(True),
            (Tarifa.cancha_id.is_(None)) | (Tarifa.cancha_id == cancha.id),
            (Tarifa.vigente_desde.is_(None)) | (Tarifa.vigente_desde <= dia),
            (Tarifa.vigente_hasta.is_(None)) | (Tarifa.vigente_hasta >= dia),
            Tarifa.hora_desde <= hora,
            Tarifa.hora_hasta > hora,
        )
    ).all()

    def aplica(tarifa: Tarifa) -> bool:
        if tarifa.alcance_dia is AlcanceDia.TODOS:
            return True
        if tarifa.alcance_dia is AlcanceDia.DIA_SEMANA:
            # 🔴 Una tarifa de día de semana **no** aplica en feriado, aunque el
            # feriado caiga ese día. Si aplicara, el operador que cargó "feriado:
            # $X" vería el precio de un martes común cada vez que el feriado cae
            # martes — y sólo se entera cuando el cliente reclama.
            return feriado is None and tarifa.dia_semana == weekday
        return feriado is not None

    return [tarifa for tarifa in filas if aplica(tarifa)]


def resolver(sesion: Session, cancha: Cancha, comienza_at: datetime) -> Tarifa:
    """La tarifa que corresponde. Levanta `SinTarifa` si no hay ninguna."""
    opciones = candidatas(sesion, cancha, comienza_at)
    if not opciones:
        raise SinTarifa(
            f"No hay tarifa cargada para {cancha.nombre} el "
            f"{a_local(comienza_at).strftime('%d-%m-%Y a las %H:%M')}."
        )
    return max(opciones, key=_especificidad)


def precio_y_sena(
    sesion: Session, cancha: Cancha, comienza_at: datetime
) -> tuple[Decimal, Decimal]:
    """El precio del turno y la seña que le corresponde.

    La seña se redondea a dos decimales **hacia arriba en el .5**
    (`ROUND_HALF_UP`), que es lo que espera cualquiera que haga la cuenta a mano.
    El default de `Decimal` es `ROUND_HALF_EVEN`, que redondea 2.5 a 2 y no
    coincide con la calculadora del encargado.
    """
    tarifa = resolver(sesion, cancha, comienza_at)
    precio = Decimal(tarifa.precio)
    sena = (precio * Decimal(tarifa.sena_porcentaje) / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return precio, sena
