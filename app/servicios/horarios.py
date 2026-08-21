"""Cuándo abre el complejo: de las franjas configuradas a intervalos concretos.

Este módulo traduce las filas de `franjas_de_atencion` a los **intervalos reales
de un día**, que es lo que la grilla y el alta de reservas necesitan. Toda la
lógica de resolución vive acá y no en `disponibilidad`, porque la usan los dos:
si la grilla resolviera por su cuenta y el alta por la suya, terminarían
discrepando y la pantalla ofrecería un turno que el backend rechaza.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import AlcanceDia
from app.models.maestros import Cancha, Feriado, FranjaDeAtencion
from app.tiempo import TZ

#: Horario que se usa cuando la sucursal **no tiene ninguna franja cargada**.
#:
#: 🔴 **Existe para que configurar horarios no sea obligatorio de golpe.** Es el
#: horario que el producto tenía hardcodeado hasta ahora; sin este piso, el
#: deploy de esta feature dejaría sin agenda a toda instancia existente —la
#: grilla vacía, y ningún cartel explicando por qué—. Cuando la sucursal carga
#: su primera franja, deja de aplicar por completo.
APERTURA_POR_DEFECTO = time(8, 0)
CIERRE_POR_DEFECTO = time(0, 0)


class FueraDeHorario(ValueError):
    """El intervalo pedido cae fuera de todo horario de atención."""


def _intervalo(dia: date, abre: time, cierra: time) -> tuple[datetime, datetime]:
    """La franja `[abre, cierra)` de un día, como dos datetimes locales.

    🔑 **`cierra <= abre` corre el fin al día siguiente.** Es el complejo que
    abre a las 16 y cierra a las 02, que en pádel es la mayoría. El caso borde
    `abre == cierra` cae acá también y da 24 horas exactas, sin rama especial.
    """
    inicio = datetime.combine(dia, abre, tzinfo=TZ)
    fin = datetime.combine(dia, cierra, tzinfo=TZ)
    if cierra <= abre:
        fin += timedelta(days=1)
    return inicio, fin


def _mas_especificas(franjas: list[FranjaDeAtencion], cancha: Cancha) -> list[FranjaDeAtencion]:
    """Las de la cancha si hay alguna; si no, las de toda la sucursal.

    Es un corte y no una unión: cargarle horario propio a una cancha significa
    *"ésta abre distinto"*, así que sumarle además el de la sucursal la haría
    abrir en las dos ventanas a la vez.
    """
    propias = [f for f in franjas if f.cancha_id == cancha.id]
    return propias or [f for f in franjas if f.cancha_id is None]


def franjas_del_dia(
    sesion: Session, cancha: Cancha, dia: date
) -> list[tuple[datetime, datetime]]:
    """Los intervalos en que esta cancha atiende ese día. Vacío = cerrado.

    Orden de resolución, el mismo del tarifario:

    1. Si hay un `Feriado` con `cerrado`, no se atiende. Corta acá.
    2. Franjas con `alcance_dia = 'feriado'`, si el día es feriado.
    3. Franjas con `alcance_dia = 'dia_semana'` para ese día.
    4. Franjas con `alcance_dia = 'todos'`.
    5. Si nada de lo anterior dio resultado, el horario por defecto.

    Los tres niveles del medio **no se suman**: gana el primero que tenga alguna
    franja. Un complejo que carga un horario especial para el sábado quiere ése
    y no ése *más* el de todos los días.
    """
    cerrado = sesion.scalars(
        select(Feriado).where(
            Feriado.sucursal_id == cancha.sucursal_id,
            Feriado.dia == dia,
            Feriado.cerrado.is_(True),
        )
    ).first()
    if cerrado is not None:
        return []

    es_feriado = (
        sesion.scalars(
            select(Feriado).where(
                Feriado.sucursal_id == cancha.sucursal_id, Feriado.dia == dia
            )
        ).first()
        is not None
    )

    candidatas = list(
        sesion.scalars(
            select(FranjaDeAtencion).where(
                FranjaDeAtencion.sucursal_id == cancha.sucursal_id,
                FranjaDeAtencion.activa.is_(True),
                # 🔴 **`|` y no `.in_((cancha.id, None))`.** En SQL
                # `cancha_id IN (1, NULL)` **no trae las filas con
                # `cancha_id IS NULL`**: comparar contra NULL da NULL, no
                # verdadero. Escrito con `in_` esto compilaba, corría sin error
                # y devolvía sólo las franjas de la cancha — o sea que el
                # horario de la sucursal no existía y todo caía en el default.
                # Es el mismo predicado que usa el tarifario, por lo mismo.
                (FranjaDeAtencion.cancha_id.is_(None))
                | (FranjaDeAtencion.cancha_id == cancha.id),
            )
        )
    )

    for alcance in (AlcanceDia.FERIADO, AlcanceDia.DIA_SEMANA, AlcanceDia.TODOS):
        if alcance is AlcanceDia.FERIADO and not es_feriado:
            continue
        del_nivel = [f for f in candidatas if f.alcance_dia is alcance]
        if alcance is AlcanceDia.DIA_SEMANA:
            del_nivel = [f for f in del_nivel if f.dia_semana == dia.weekday()]
        elegidas = _mas_especificas(del_nivel, cancha)
        if elegidas:
            return sorted(_intervalo(dia, f.abre, f.cierra) for f in elegidas)

    return [_intervalo(dia, APERTURA_POR_DEFECTO, CIERRE_POR_DEFECTO)]


def hay_horario_configurado(sesion: Session, sucursal_id: int) -> bool:
    """Si esta sucursal cargó alguna franja. Para avisar que rige el default."""
    return (
        sesion.scalars(
            select(FranjaDeAtencion).where(
                FranjaDeAtencion.sucursal_id == sucursal_id,
                FranjaDeAtencion.activa.is_(True),
            )
        ).first()
        is not None
    )


def esta_abierto(
    sesion: Session, cancha: Cancha, comienza_at: datetime, termina_at: datetime
) -> bool:
    """Si el intervalo entra **entero** en una sola franja de atención.

    🔑 **En una sola, no en la unión de varias.** Un complejo que abre de 9 a 13
    y de 16 a 24 está cerrado entre las 13 y las 16, y una reserva de 12 a 17
    atravesaría ese hueco: sumar las franjas la aceptaría.

    Se consultan los dos días —el de inicio y el siguiente— porque una franja
    que cruza medianoche pertenece al día en que **abrió**: un turno de 00:30 del
    sábado vive en la franja del viernes, y mirando sólo el sábado no aparece.
    """
    dia = comienza_at.astimezone(TZ).date()
    intervalos = franjas_del_dia(sesion, cancha, dia) + franjas_del_dia(
        sesion, cancha, dia - timedelta(days=1)
    )
    return any(
        inicio <= comienza_at and termina_at <= fin for inicio, fin in intervalos
    )


def texto_del_horario(sesion: Session, cancha: Cancha, dia: date) -> str:
    """Cómo se le dice al operador que ese día está cerrado o abre a tal hora."""
    intervalos = franjas_del_dia(sesion, cancha, dia)
    if not intervalos:
        return "cerrado"
    return " y ".join(f"{i:%H:%M} a {f:%H:%M}" for i, f in intervalos)
