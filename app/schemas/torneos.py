"""Contrato de la API para torneos: competidores, fixture, posiciones."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import Deporte, EstadoTorneo, EtapaTorneo, FormatoTorneo


class TorneoEntrada(BaseModel):
    sucursal_id: int
    nombre: str = Field(min_length=1, max_length=120)
    deporte: Deporte = Deporte.PADEL
    formato: FormatoTorneo
    desde: date
    hasta: date | None = None
    #: 1 = fútbol (un resultado). 2 = al mejor de tres, que es el pádel normal.
    sets_para_ganar: int = Field(default=2, ge=1, le=5)
    cantidad_zonas: int | None = Field(default=None, ge=2)
    clasifican_por_zona: int | None = Field(default=None, ge=1, le=2)
    observaciones: str | None = None

    @model_validator(mode="after")
    def _zonas_coherentes(self) -> TorneoEntrada:
        """Los parámetros de zonas existen sólo en el formato que los usa.

        🔑 Está también como CHECK en la base — ver `models/torneos.py`—, y las
        dos cosas hacen falta: el CHECK garantiza que nada entre mal por ningún
        camino, y esto da un 422 con un mensaje en castellano en vez de un 500
        con el nombre de un constraint.
        """
        de_zonas = self.formato is FormatoTorneo.ZONAS
        tiene = self.cantidad_zonas is not None or self.clasifican_por_zona is not None
        if de_zonas and not (
            self.cantidad_zonas is not None and self.clasifican_por_zona is not None
        ):
            raise ValueError(
                "Un torneo por zonas necesita cuántas zonas y cuántos clasifican."
            )
        if not de_zonas and tiene:
            raise ValueError(
                "Sólo un torneo por zonas lleva cantidad de zonas y clasificados."
            )
        return self


class TorneoEdicion(BaseModel):
    """Lo que se puede cambiar después de crear.

    🔴 **Ni el formato ni los parámetros de zonas.** Cambiarlos con el torneo
    sorteado no es editar un campo: es tirar el fixture, y con él los partidos
    ya jugados. Lo que sí se corrige es lo que no afecta al cuadro — el nombre,
    las fechas, una observación.
    """

    nombre: str = Field(min_length=1, max_length=120)
    desde: date
    hasta: date | None = None
    observaciones: str | None = None


class IntegranteEntrada(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    telefono: str | None = Field(default=None, max_length=40)


class CompetidorEntrada(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    #: Cabeza de serie. `null` = entra al bombo.
    siembra: int | None = Field(default=None, ge=1)
    integrantes: list[IntegranteEntrada] = Field(default_factory=list)


class IntegranteSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nombre: str
    #: Visible: esto es el backoffice, no el portal. Quien lo consulta es el
    #: encargado que necesita avisarle a la pareja que su partido se movió. En
    #: el portal público la regla es la contraria — ver `servicios/partidos.py`.
    telefono: str | None


class CompetidorSalida(BaseModel):
    id: int
    nombre: str
    siembra: int | None
    zona_id: int | None
    zona: str | None
    integrantes: list[IntegranteSalida]


class ParcialEntrada(BaseModel):
    puntos_a: int = Field(ge=0, le=999)
    puntos_b: int = Field(ge=0, le=999)


class ResultadoEntrada(BaseModel):
    parciales: list[ParcialEntrada] = Field(min_length=1, max_length=9)


class ParcialSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    numero: int
    puntos_a: int
    puntos_b: int


class ProgramacionEntrada(BaseModel):
    cancha_id: int
    #: ISO 8601. Sin offset se toma como hora local del complejo, igual que en
    #: el alta de reservas.
    comienza_at: datetime
    duracion_min: int | None = Field(default=None, ge=1, le=480)


class PartidoSalida(BaseModel):
    id: int
    etapa: EtapaTorneo
    zona_id: int | None
    zona: str | None
    ronda: int
    orden: int
    #: «Semifinal», «Zona A · Fecha 2». Lo resuelve el servidor porque depende
    #: de cuántas rondas tenga el cuadro, que el cliente no tiene por qué saber.
    instancia: str
    competidor_a_id: int | None
    competidor_a: str | None
    competidor_b_id: int | None
    competidor_b: str | None
    avanza_a_id: int | None
    avanza_a_slot: str | None
    reserva_id: int | None
    cancha: str | None
    comienza_at: datetime | None
    termina_at: datetime | None
    ganador_id: int | None
    finalizado: bool
    parciales: list[ParcialSalida]


class FixtureSalida(BaseModel):
    #: Cuántas rondas tiene el cuadro. `0` si el torneo todavía no tiene llaves.
    #: Es lo que la pantalla necesita para dibujar las columnas del bracket.
    rondas: int
    partidos: list[PartidoSalida]


class FilaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    competidor_id: int
    nombre: str
    jugados: int
    ganados: int
    empatados: int
    perdidos: int
    a_favor: int
    en_contra: int
    diferencia: int
    puntos: int


class TablaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    zona_id: int | None
    nombre: str | None
    filas: list[FilaSalida]


class TorneoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sucursal_id: int
    nombre: str
    deporte: Deporte
    formato: FormatoTorneo
    estado: EstadoTorneo
    desde: date
    hasta: date | None
    sets_para_ganar: int
    cantidad_zonas: int | None
    clasifican_por_zona: int | None
    semilla: int | None
    observaciones: str | None


class TorneoEnLista(TorneoSalida):
    """El torneo con lo que la pantalla muestra sin abrirlo.

    🔑 `jugados`/`partidos` se calculan y **no se guardan**: un contador
    persistido hay que acordarse de mover en cada carga de resultado, y el día
    que alguien se olvide la lista miente. Ver el docstring de `EstadoTorneo`,
    que evita `EN_CURSO` por el mismo motivo.
    """

    competidores: int
    partidos: int
    jugados: int
    #: Sin programar todavía: los que no tienen cancha ni horario. Es lo que le
    #: dice al encargado que le falta trabajo.
    sin_programar: int
    campeon: str | None
