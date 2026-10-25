"""Contrato de la API para torneos: competidores, fixture, posiciones."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import Deporte, EstadoTorneo, EtapaTorneo, FormatoTorneo
from app.servicios.sets_de_games import GAMES_VALIDOS


def _limpiar_categoria(valor: str | None) -> str | None:
    """«  Caballeros 5ta » es «Caballeros 5ta»; vacío es sin categoría."""
    if valor is None:
        return None
    return " ".join(valor.split()) or None


class TorneoEntrada(BaseModel):
    sucursal_id: int
    nombre: str = Field(min_length=1, max_length=120)
    deporte: Deporte = Deporte.PADEL
    formato: FormatoTorneo
    desde: date
    hasta: date | None = None
    #: 1 = fútbol (un resultado). 2 = al mejor de tres, que es el pádel normal.
    sets_para_ganar: int = Field(default=2, ge=1, le=5)
    #: A cuántos games se juega cada set en pádel y tenis: 6 o 9. `null` = no se
    #: controlan los games del set (fútbol y demás, o un torneo sin esa regla).
    games_por_set: int | None = None
    cantidad_zonas: int | None = Field(default=None, ge=2)
    clasifican_por_zona: int | None = Field(default=None, ge=1, le=2)
    #: Un torneo por zonas que no tiene llaves: el primero de cada zona es el
    #: campeón de su zona. Excluye a `clasifican_por_zona`.
    termina_en_zonas: bool = False
    #: «Caballeros 5ta», «Damas», «Mixto».
    categoria: str | None = Field(default=None, max_length=60)
    #: El evento del que es una categoría. Las fechas las pone el evento.
    evento_id: int | None = None
    observaciones: str | None = None

    @field_validator("categoria")
    @classmethod
    def _categoria_limpia(cls, valor: str | None) -> str | None:
        return _limpiar_categoria(valor)

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
        if de_zonas and self.termina_en_zonas:
            if self.cantidad_zonas is None:
                raise ValueError("Un torneo por zonas necesita cuántas zonas.")
            if self.clasifican_por_zona is not None:
                raise ValueError(
                    "Un torneo que termina en las zonas no lleva clasificados: "
                    "no hay llaves a las que pasar."
                )
        elif de_zonas and not (
            self.cantidad_zonas is not None and self.clasifican_por_zona is not None
        ):
            raise ValueError(
                "Un torneo por zonas necesita cuántas zonas y cuántos clasifican."
            )
        if not de_zonas and (tiene or self.termina_en_zonas):
            raise ValueError(
                "Sólo un torneo por zonas lleva cantidad de zonas y clasificados."
            )
        return self

    @model_validator(mode="after")
    def _games_coherentes(self) -> TorneoEntrada:
        """Los games por set son de pádel y de tenis, y de 6 o de 9."""
        if self.games_por_set is None:
            return self
        if self.games_por_set not in GAMES_VALIDOS:
            raise ValueError("Los sets se juegan a 6 o a 9 games.")
        if self.deporte not in (Deporte.PADEL, Deporte.TENIS):
            raise ValueError("Los games por set son sólo de pádel y de tenis.")
        return self

    @model_validator(mode="after")
    def _categoria_del_evento(self) -> TorneoEntrada:
        if self.evento_id is not None and not self.categoria:
            raise ValueError("Una categoría de un evento necesita su categoría.")
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
    #: Si no viene, la categoría queda como está. Con `null` explícito se saca.
    categoria: str | None = Field(default=None, max_length=60)

    @field_validator("categoria")
    @classmethod
    def _categoria_limpia(cls, valor: str | None) -> str | None:
        return _limpiar_categoria(valor)


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
    #: Sólo en pádel y tenis; `null` en el resto, donde un parcial no es un set.
    sets_a_favor: int | None = None
    sets_en_contra: int | None = None
    diferencia_sets: int | None = None


class TablaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    zona_id: int | None
    nombre: str | None
    filas: list[FilaSalida]
    #: Se jugaron todos los partidos de la zona: con `termina_en_zonas`, la
    #: primera fila es su campeón.
    completa: bool = False
    #: Si la tabla lleva las columnas de sets (pádel y tenis).
    con_sets: bool = False


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
    games_por_set: int | None
    cantidad_zonas: int | None
    clasifican_por_zona: int | None
    termina_en_zonas: bool
    categoria: str | None
    evento_id: int | None
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
    #: En un torneo que termina en las zonas con varias zonas, no hay un campeón:
    #: son los de cada zona que ya terminó, «Zona A: Pérez / García · Zona B: …».
    campeon: str | None
    #: El nombre del evento, si es una categoría de uno.
    evento: str | None = None


# ── Eventos ─────────────────────────────────────────────────────────────────


class EventoEntrada(BaseModel):
    sucursal_id: int
    nombre: str = Field(min_length=1, max_length=120)
    desde: date
    hasta: date | None = None
    observaciones: str | None = None
    #: Las canchas del evento. Vacío = cualquiera de la sucursal.
    cancha_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rango(self) -> EventoEntrada:
        if self.hasta is not None and self.hasta < self.desde:
            raise ValueError("El evento no puede terminar antes de empezar.")
        return self


class EventoEdicion(BaseModel):
    """La sucursal no se cambia: las categorías ya están en ella."""

    nombre: str = Field(min_length=1, max_length=120)
    desde: date
    hasta: date | None = None
    observaciones: str | None = None
    cancha_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rango(self) -> EventoEdicion:
        if self.hasta is not None and self.hasta < self.desde:
            raise ValueError("El evento no puede terminar antes de empezar.")
        return self


class EventoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sucursal_id: int
    nombre: str
    desde: date
    hasta: date | None
    observaciones: str | None
    cancha_ids: list[int] = Field(default_factory=list)


class EventoEnLista(EventoSalida):
    categorias: int


class EventoDetalle(EventoSalida):
    """El evento con sus categorías, cada una con lo que muestra la lista de torneos."""

    categorias: list[TorneoEnLista]
