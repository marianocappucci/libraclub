"""Modelos del dominio.

Se importan todos acá para que `Base.metadata` esté completo cuando Alembic lo
lea. Un modelo que no llegue a este archivo **no existe para el autogenerate**, y
el síntoma es una migración que borra la tabla que nadie declaró.
"""

from app.models.avisos import Aviso
from app.models.base import Anotable, Auditable, Base
from app.models.enums import (
    ESTADOS_QUE_OCUPAN,
    AlcanceDia,
    CanalAviso,
    Deporte,
    EstadoAviso,
    EstadoReserva,
    EstadoTorneo,
    EtapaTorneo,
    FormatoTorneo,
    OrigenReserva,
    TipoAviso,
)
from app.models.maestros import Cancha, Cliente, Feriado, Sucursal
from app.models.reservas import WHERE_OCUPA, Reserva, Serie
from app.models.tarifas import Tarifa
from app.models.torneos import (
    Competidor,
    IntegranteDeCompetidor,
    ParcialDePartido,
    PartidoDeTorneo,
    Torneo,
    Zona,
)

__all__ = [
    "ESTADOS_QUE_OCUPAN",
    "AlcanceDia",
    "Anotable",
    "Auditable",
    "Aviso",
    "Base",
    "CanalAviso",
    "Cancha",
    "Cliente",
    "Competidor",
    "Deporte",
    "EstadoAviso",
    "EstadoReserva",
    "EstadoTorneo",
    "EtapaTorneo",
    "Feriado",
    "FormatoTorneo",
    "IntegranteDeCompetidor",
    "OrigenReserva",
    "ParcialDePartido",
    "PartidoDeTorneo",
    "Reserva",
    "Serie",
    "Sucursal",
    "Tarifa",
    "TipoAviso",
    "Torneo",
    "Zona",
    "WHERE_OCUPA",
]
