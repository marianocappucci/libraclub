"""Resolución del precio de un turno.

No importa FastAPI: se prueba llamándolo, sin levantar la aplicación.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import AlcanceDia
from app.models.maestros import Cancha, Feriado
from app.models.tarifas import Promocion, Tarifa
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


#: «Todavía no miré si es feriado». `None` ya significa «no es feriado», así que no sirve de marca.
_SIN_MIRAR = object()


def candidatas(
    sesion: Session, cancha: Cancha, comienza_at: datetime, *, feriado=_SIN_MIRAR
) -> list[Tarifa]:
    """Todas las tarifas que cubren ese turno, sin ordenar.

    `feriado` lo pasa quien ya lo averiguó (`cotizar` lo necesita también para las
    promociones): preguntarlo dos veces por casillero es una consulta de más en cada celda de
    la grilla de la semana.
    """
    local = a_local(comienza_at)
    dia = local.date()
    hora = hora_local(comienza_at)
    weekday = dia_de_semana(comienza_at)
    if feriado is _SIN_MIRAR:
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


def resolver(sesion: Session, cancha: Cancha, comienza_at: datetime, *, feriado=_SIN_MIRAR) -> Tarifa:
    """La tarifa que corresponde. Levanta `SinTarifa` si no hay ninguna."""
    opciones = candidatas(sesion, cancha, comienza_at, feriado=feriado)
    if not opciones:
        raise SinTarifa(
            f"No hay tarifa cargada para {cancha.nombre} el "
            f"{a_local(comienza_at).strftime('%d-%m-%Y a las %H:%M')}."
        )
    return max(opciones, key=_especificidad)


def promociones_aplicables(
    sesion: Session, cancha: Cancha, comienza_at: datetime, *, feriado=_SIN_MIRAR
) -> list[Promocion]:
    """Las promociones que cubren ese turno, sin ordenar. Misma lectura de día y hora que las tarifas."""
    dia = a_local(comienza_at).date()
    hora = hora_local(comienza_at)
    weekday = dia_de_semana(comienza_at)
    if feriado is _SIN_MIRAR:
        feriado = es_feriado(sesion, cancha.sucursal_id, comienza_at)

    filas = sesion.scalars(
        select(Promocion).where(
            Promocion.sucursal_id == cancha.sucursal_id,
            Promocion.activa.is_(True),
            (Promocion.cancha_id.is_(None)) | (Promocion.cancha_id == cancha.id),
            (Promocion.vigente_desde.is_(None)) | (Promocion.vigente_desde <= dia),
            (Promocion.vigente_hasta.is_(None)) | (Promocion.vigente_hasta >= dia),
            Promocion.hora_desde <= hora,
            Promocion.hora_hasta > hora,
        )
    ).all()

    def aplica(promo: Promocion) -> bool:
        # 🔴 En un feriado sólo aplica la que lo pide: la hora valle existe porque hay poca
        # demanda, y un feriado no tiene poca demanda. Sin esta guarda, «martes de 14 a 17» se
        # regalaba el martes que cae 25 de mayo.
        if feriado is not None and not promo.aplica_en_feriados:
            return False
        return promo.dias_semana is None or weekday in promo.dias_semana

    return [promo for promo in filas if aplica(promo)]


def _mejor_promocion(promociones: list[Promocion]) -> Promocion | None:
    """La que más descuenta. **No se suman**: apilar porcentajes regala la cancha sin darse cuenta.

    Empate: la de una cancha en particular antes que la de toda la sucursal, y después la más
    nueva (el `id`, por lo mismo que en `_especificidad`: sin desempate final el precio
    dependería del orden en que PostgreSQL devuelva las filas).
    """
    if not promociones:
        return None
    return max(
        promociones,
        key=lambda p: (p.descuento_porcentaje, 1 if p.cancha_id is not None else 0, p.id),
    )


@dataclass(frozen=True, slots=True)
class Cotizacion:
    """El precio de un turno, con de dónde sale.

    `precio` es **lo que se cobra**; `precio_lista` es el de la tarifa sin promoción. Son
    iguales cuando `promocion` es `None`.
    """

    tarifa: Tarifa
    promocion: Promocion | None
    precio_lista: Decimal
    precio: Decimal
    sena: Decimal


def _a_centavos(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def cotizar(
    sesion: Session, cancha: Cancha, comienza_at: datetime, *, con_promocion: bool = True
) -> Cotizacion:
    """El precio del turno: la tarifa ganadora, menos la mejor promoción si hay.

    🔑 **Es el único lugar donde se calcula un precio** (ADR-029). El mostrador, las series, el
    portal y la grilla pasan por acá —`precio_y_sena` es esto mismo con otra forma—, así que
    una promoción cargada aplica en todos los canales sin tocar a ninguno, y el precio que el
    portal muestra tachado es el mismo que `Reserva.precio` congela después.

    La seña se saca del **precio con promoción**: quien paga menos pone menos de seña.

    🔑 **`con_promocion=False` cotiza al precio de lista**, con el mismo cálculo y sin mirar las
    promociones. Es lo que usan los **turnos fijos** (las series): quien tiene la cancha todas las
    semanas paga la tarifa, no la hora valle ni la promoción de la semana (decisión del humano,
    2026-10-28). No es un segundo cálculo: es éste sin el paso de la promoción, así que la tarifa,
    el feriado y la seña salen exactamente igual.
    """
    feriado = es_feriado(sesion, cancha.sucursal_id, comienza_at)
    tarifa = resolver(sesion, cancha, comienza_at, feriado=feriado)
    lista = Decimal(tarifa.precio)

    promocion = (
        _mejor_promocion(promociones_aplicables(sesion, cancha, comienza_at, feriado=feriado))
        if con_promocion
        else None
    )
    precio = lista
    if promocion is not None:
        precio = _a_centavos(lista * Decimal(100 - promocion.descuento_porcentaje) / Decimal(100))

    # La seña se redondea a dos decimales **hacia arriba en el .5** (`ROUND_HALF_UP`), que es
    # lo que espera cualquiera que haga la cuenta a mano. El default de `Decimal` es
    # `ROUND_HALF_EVEN`, que redondea 2.5 a 2 y no coincide con la calculadora del encargado.
    sena = _a_centavos(precio * Decimal(tarifa.sena_porcentaje) / Decimal(100))
    return Cotizacion(tarifa, promocion, lista, precio, sena)


def precio_y_sena(
    sesion: Session, cancha: Cancha, comienza_at: datetime, *, con_promocion: bool = True
) -> tuple[Decimal, Decimal]:
    """El precio del turno (con promoción, salvo `con_promocion=False`) y la seña que le corresponde."""
    cotizacion = cotizar(sesion, cancha, comienza_at, con_promocion=con_promocion)
    return cotizacion.precio, cotizacion.sena
