"""Tarifas por cancha, día y franja.

Vive en LibraClub y no en LibraGenda a propósito: el motor no tiene ningún
modelo de precio, y Gestiolibra ya resolvió lo mismo con un repositorio de
precios propio. Ver DECISIONS.md ADR-003.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Time,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Auditable, Base
from app.models.enums import AlcanceDia


class Tarifa(Base, Auditable):
    """El precio de una hora de cancha, para un día y una franja.

    ## Cómo se resuelve

    Se buscan todas las tarifas vigentes y activas que *matcheen* el turno, y se
    decide en este orden — **la primera clave que difiera resuelve**:

    | Orden | Clave | Gana |
    |---|---|---|
    | 1 | `prioridad` | el número más alto |
    | 2 | Alcance del día | `feriado` > `dia_semana` > `todos` |
    | 3 | Cancha | una cancha > toda la sucursal (`cancha_id IS NULL`) |
    | 4 | `id` | la más nueva |

    **`prioridad` va primero, no último.** Es el escape manual: existe para que
    una promoción de sucursal pueda ganarle a la tarifa específica de una cancha
    sin tener que borrarla —y después acordarse de volver a cargarla—. Si fuera
    sólo un desempate, no podría hacer eso. Su default es `0`, así que en el uso
    normal no interviene y decide la especificidad.

    ## Lo que NO hace

    No prorratea. Un turno de 90 minutos que arranca a las 17:30 y cruza al
    horario nocturno de las 18:00 **se cobra con la tarifa de las 17:30**, entera.
    Prorratear suena más justo y es la clase de cosa que ningún encargado quiere
    explicarle a un cliente en el mostrador. Si aparece un complejo que lo pide,
    es una decisión de producto, no un bug.
    """

    __tablename__ = "tarifas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sucursal_id: Mapped[int] = mapped_column(
        ForeignKey("sucursales.id", ondelete="CASCADE"), nullable=False
    )
    #: `NULL` = aplica a todas las canchas de la sucursal.
    cancha_id: Mapped[int | None] = mapped_column(
        ForeignKey("canchas.id", ondelete="CASCADE"), nullable=True
    )
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)

    alcance_dia: Mapped[AlcanceDia] = mapped_column(
        Enum(AlcanceDia, name="alcance_dia", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=AlcanceDia.TODOS,
    )
    #: 0 = lunes … 6 = domingo. Obligatorio si `alcance_dia = 'dia_semana'`, y
    #: prohibido en los otros dos casos — lo garantiza un CHECK, no el código.
    dia_semana: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Franja en **hora de pared del complejo**, no en UTC. Ver `app/tiempo.py`.
    #: Semiabierta: `[hora_desde, hora_hasta)`, para que dos franjas contiguas no
    #: se peleen el instante del borde.
    hora_desde: Mapped[time] = mapped_column(Time, nullable=False)
    hora_hasta: Mapped[time] = mapped_column(Time, nullable=False)

    #: Precio del turno completo, no por hora: es lo que el encargado dice cuando
    #: le preguntan "¿cuánto sale la cancha?".
    precio: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    #: Porcentaje de seña, 0-100. `0` = no se pide seña en esta franja. Entra en
    #: juego en F2; se define ahora para no migrar la tabla después.
    sena_porcentaje: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    vigente_desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    vigente_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("hora_desde < hora_hasta", name="ck_tarifas_franja"),
        CheckConstraint("precio >= 0", name="ck_tarifas_precio"),
        CheckConstraint(
            "sena_porcentaje >= 0 AND sena_porcentaje <= 100",
            name="ck_tarifas_sena_porcentaje",
        ),
        # El estado imposible que el modelo explícito permite rechazar: una
        # tarifa de feriado con día de semana, o una de día de semana sin él.
        CheckConstraint(
            "(alcance_dia = 'dia_semana' AND dia_semana IS NOT NULL "
            " AND dia_semana BETWEEN 0 AND 6) "
            "OR (alcance_dia <> 'dia_semana' AND dia_semana IS NULL)",
            name="ck_tarifas_dia_semana_coherente",
        ),
        CheckConstraint(
            "vigente_hasta IS NULL OR vigente_desde IS NULL "
            "OR vigente_hasta >= vigente_desde",
            name="ck_tarifas_vigencia",
        ),
        Index("ix_tarifas_sucursal", "sucursal_id"),
        Index("ix_tarifas_cancha", "cancha_id"),
    )


class Promocion(Base, Auditable):
    """Un descuento en porcentaje sobre la tarifa, para una franja y una vigencia.

    Cubre las dos cosas que el rubro llama distinto y son lo mismo: la **hora valle**
    («martes a jueves de 14 a 17, 20% menos») y la **promoción con vigencia** («del 1 al 15
    de noviembre, 10% menos»). Lo que cambia es qué campos se llenan: la hora valle lleva
    días y franja; la promoción, fechas.

    ## Por qué no es una `Tarifa` con precio menor

    Se podía —`prioridad` existe justamente para que una promoción le gane a la tarifa
    normal—, y a mano sigue sirviendo. Se hizo aparte (ADR-029) por tres cosas que una
    tarifa no puede dar:

    1. **Es un porcentaje y no un precio.** Un complejo con canchas a $18.000 y a $26.000
       carga *una* promoción de 20%, no una tarifa por cancha que hay que acordarse de
       mover cuando sube la lista.
    2. **El portal necesita el precio de lista.** Para mostrar «~~$18.000~~ $14.400» hay que
       saber cuál era el precio sin promoción; entre dos tarifas, ninguna dice cuál es la
       «normal».
    3. **Se nombra.** Una promoción tiene nombre y un descuento: se puede decir cuánta plata
       se rebajó y en qué franja, que es para lo que se carga.

    ## Cómo se aplica

    La resuelve `servicios/tarifario.cotizar`, **sobre el precio de la tarifa ganadora**, y es
    la misma cuenta para el mostrador, el portal y las series: no hay un segundo cálculo de
    precio. Si aplican varias, **gana la de mayor descuento y no se suman** (apilar
    porcentajes es la forma de regalar la cancha sin darse cuenta).

    ## Lo que NO hace

    - **No aplica en feriado** salvo que `aplica_en_feriados` lo pida: la hora valle existe
      porque hay poca demanda, y un feriado no la tiene. (Mismo criterio que una tarifa de
      día de semana: ver `servicios/tarifario.candidatas`.)
    - **No llega al 100%.** Un turno en $0 descuadra la caja (ver `SinTarifa`). El tope es 99.
    """

    __tablename__ = "promociones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sucursal_id: Mapped[int] = mapped_column(
        ForeignKey("sucursales.id", ondelete="CASCADE"), nullable=False
    )
    #: `NULL` = todas las canchas de la sucursal.
    cancha_id: Mapped[int | None] = mapped_column(
        ForeignKey("canchas.id", ondelete="CASCADE"), nullable=True
    )
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    descuento_porcentaje: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    #: 0 = lunes … 6 = domingo. `NULL` = todos los días. Un arreglo y no siete booleanos ni
    #: una fila por día: «lunes a jueves» es una promoción, no cuatro.
    dias_semana: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger), nullable=True)
    #: Franja en **hora de pared del complejo**, semiabierta `[desde, hasta)`, como `Tarifa`.
    hora_desde: Mapped[time] = mapped_column(Time, nullable=False)
    hora_hasta: Mapped[time] = mapped_column(Time, nullable=False)
    vigente_desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    vigente_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    aplica_en_feriados: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("hora_desde < hora_hasta", name="ck_promociones_franja"),
        CheckConstraint(
            "descuento_porcentaje >= 1 AND descuento_porcentaje <= 99",
            name="ck_promociones_descuento",
        ),
        CheckConstraint(
            "dias_semana IS NULL OR (cardinality(dias_semana) > 0 "
            "AND dias_semana <@ ARRAY[0,1,2,3,4,5,6]::smallint[])",
            name="ck_promociones_dias",
        ),
        CheckConstraint(
            "vigente_hasta IS NULL OR vigente_desde IS NULL "
            "OR vigente_hasta >= vigente_desde",
            name="ck_promociones_vigencia",
        ),
        Index("ix_promociones_sucursal", "sucursal_id"),
        Index("ix_promociones_cancha", "cancha_id"),
    )
