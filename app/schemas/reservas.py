"""Contrato de la API para reservas, bloqueos, series y la grilla."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EstadoReserva, OrigenReserva


class ReservaEntrada(BaseModel):
    cancha_id: int
    cliente_id: int
    #: ISO 8601 **con offset**. Un datetime sin zona se toma como UTC, y la
    #: reserva de las 20:00 aparecería a las 17:00. El frontend manda el offset;
    #: no se adivina acá.
    comienza_at: datetime
    #: `null` = la duración estándar de la cancha.
    duracion_min: int | None = Field(default=None, ge=1, le=480)
    estado: EstadoReserva = EstadoReserva.CONFIRMADA
    origen: OrigenReserva = OrigenReserva.MOSTRADOR
    #: Precio a mano. `null` = lo resuelve el tarifario.
    precio: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    observaciones: str | None = None


class BloqueoEntrada(BaseModel):
    cancha_id: int
    comienza_at: datetime
    termina_at: datetime
    motivo: str = Field(min_length=1, max_length=200)


class CambioDeEstado(BaseModel):
    estado: EstadoReserva
    motivo: str | None = Field(default=None, max_length=200)


class ReservaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cancha_id: int
    cliente_id: int | None
    serie_id: int | None
    estado: EstadoReserva
    origen: OrigenReserva
    comienza_at: datetime
    termina_at: datetime
    precio: Decimal | None
    sena: Decimal | None
    vence_at: datetime | None
    motivo: str | None
    observaciones: str | None


class SerieEntrada(BaseModel):
    cancha_id: int
    cliente_id: int
    dia_semana: int = Field(ge=0, le=6)
    hora: time
    duracion_min: int = Field(ge=1, le=480)
    desde: date
    #: `null` = sin fin. Es el caso normal de una cancha fija.
    hasta: date | None = None
    observaciones: str | None = None


class SerieSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cancha_id: int
    cliente_id: int
    dia_semana: int
    hora: time
    duracion_min: int
    desde: date
    hasta: date | None
    activa: bool


class SalteadaSalida(BaseModel):
    """Una fecha de la serie que no se pudo crear, con el motivo."""

    comienza_at: datetime
    #: Código estable para la pantalla: `sin_tarifa`, `ocupada`,
    #: `fuera_de_horario`.
    motivo: str
    #: El mensaje de la excepción, que nombra la cancha y el horario del día.
    detalle: str


class SerieCreada(BaseModel):
    """El resultado de materializar una serie.

    Devuelve las salteadas y no sólo las creadas: una cancha fija que chocó con
    un torneo el tercer martes tiene que decírselo al operador **en el momento**,
    no dejar que lo descubra el martes.

    🔑 **Y con el motivo de cada una.** "Se saltearon 3 de 13" no alcanza: si fue
    por falta de tarifa el operador carga la tarifa, si fue por horario revisa el
    horario, y si fue por superposición le avisa al cliente. Sin el motivo tiene
    que ir a buscar cada fecha a la grilla.
    """

    serie: SerieSalida
    creadas: list[ReservaSalida]
    salteadas: list[SalteadaSalida]


class TurnoSalida(BaseModel):
    comienza_at: datetime
    termina_at: datetime
    libre: bool
    precio: Decimal | None = None
    reserva_id: int | None = None
    estado: EstadoReserva | None = None
    cliente: str | None = None
    motivo: str | None = None
