"""Contrato de la API para sucursales, canchas, clientes y feriados.

Todo lo que sale acá va en **ISO 8601**. El `dd-mm-aaaa` es del frontend.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import AlcanceDia, Deporte


class SucursalEntrada(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    direccion: str | None = Field(default=None, max_length=160)
    localidad: str | None = Field(default=None, max_length=80)
    telefono: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    punto_venta_arca: int | None = Field(default=None, ge=1, le=99999)
    #: Con cuántas horas de anticipación hay que cancelar para que se devuelva la
    #: seña. `None` = esta sucursal no devuelve nada automáticamente, que es el
    #: default y lo que hacían todas antes de que la política existiera.
    #:
    #: El tope de 720 h son 30 días: no es una regla de negocio, es el freno al
    #: dedo que escribe 2400 pensando en minutos y deja una política que **nunca**
    #: se cumple —o sea, una devolución que no se hace nunca y nadie entiende por
    #: qué—.
    horas_de_cancelacion: int | None = Field(default=None, ge=1, le=720)
    activa: bool = True
    observaciones: str | None = None


class SucursalSalida(SucursalEntrada):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CanchaEntrada(BaseModel):
    sucursal_id: int
    nombre: str = Field(min_length=1, max_length=80)
    deporte: Deporte = Deporte.PADEL
    duracion_turno_min: int = Field(default=90, ge=1, le=480)
    techada: bool = False
    iluminacion: bool = True
    superficie: str | None = Field(default=None, max_length=40)
    orden: int = 0
    activa: bool = True
    observaciones: str | None = None


class CanchaSalida(CanchaEntrada):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ClienteEntrada(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    telefono: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    documento: str | None = Field(default=None, max_length=20)
    cuit: str | None = Field(default=None, max_length=13)
    activo: bool = True
    #: Si quiere recibir confirmaciones y recordatorios de sus turnos. Arranca en
    #: `True` —quien deja su email al reservar espera que le llegue el turno— y
    #: es lo que el mostrador apaga cuando alguien pide no recibir más.
    acepta_avisos: bool = True
    observaciones: str | None = None


class ClienteSalida(ClienteEntrada):
    model_config = ConfigDict(from_attributes=True)
    id: int


class FeriadoEntrada(BaseModel):
    sucursal_id: int
    dia: date
    nombre: str = Field(min_length=1, max_length=80)
    cerrado: bool = False


class FeriadoSalida(FeriadoEntrada):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TarifaEntrada(BaseModel):
    sucursal_id: int
    cancha_id: int | None = None
    nombre: str = Field(min_length=1, max_length=80)
    alcance_dia: AlcanceDia = AlcanceDia.TODOS
    dia_semana: int | None = Field(default=None, ge=0, le=6)
    hora_desde: time
    hora_hasta: time
    precio: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    sena_porcentaje: int = Field(default=0, ge=0, le=100)
    vigente_desde: date | None = None
    vigente_hasta: date | None = None
    prioridad: int = 0
    activa: bool = True

    @field_validator("hora_hasta")
    @classmethod
    def _franja_valida(cls, valor: time, info) -> time:
        desde = info.data.get("hora_desde")
        if desde is not None and valor <= desde:
            # 🔴 El mismo chequeo está como CHECK en la base. Los dos, a
            # propósito: el CHECK garantiza, este da un 422 con el nombre del
            # campo en vez de un 500 con un error de PostgreSQL.
            raise ValueError("hora_hasta tiene que ser posterior a hora_desde")
        return valor

    @field_validator("dia_semana")
    @classmethod
    def _dia_coherente(cls, valor: int | None, info) -> int | None:
        alcance = info.data.get("alcance_dia")
        if alcance is AlcanceDia.DIA_SEMANA and valor is None:
            raise ValueError("una tarifa por día de semana necesita dia_semana")
        if alcance is not None and alcance is not AlcanceDia.DIA_SEMANA and valor is not None:
            raise ValueError(f"dia_semana no aplica con alcance_dia={alcance.value}")
        return valor


class TarifaSalida(TarifaEntrada):
    model_config = ConfigDict(from_attributes=True)
    id: int


class FranjaEntrada(BaseModel):
    sucursal_id: int
    cancha_id: int | None = None
    alcance_dia: AlcanceDia = AlcanceDia.TODOS
    dia_semana: int | None = Field(default=None, ge=0, le=6)
    abre: time
    cierra: time
    activa: bool = True

    @field_validator("dia_semana")
    @classmethod
    def _dia_coherente(cls, valor: int | None, info) -> int | None:
        # Mismo par validador+CHECK que `TarifaEntrada`, y por el mismo motivo:
        # el CHECK garantiza, éste da un 422 con el nombre del campo.
        alcance = info.data.get("alcance_dia")
        if alcance is AlcanceDia.DIA_SEMANA and valor is None:
            raise ValueError("un horario por día de semana necesita dia_semana")
        if alcance is not None and alcance is not AlcanceDia.DIA_SEMANA and valor is not None:
            raise ValueError(f"dia_semana no aplica con alcance_dia={alcance.value}")
        return valor


class FranjaSalida(FranjaEntrada):
    model_config = ConfigDict(from_attributes=True)
    id: int
