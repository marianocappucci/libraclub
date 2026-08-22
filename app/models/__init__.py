"""Modelos del dominio.

Se importan todos acá para que `Base.metadata` esté completo cuando Alembic lo
lea. Un modelo que no llegue a este archivo **no existe para el autogenerate**, y
el síntoma es una migración que borra la tabla que nadie declaró.
"""

from app.models.base import Anotable, Auditable, Base
from app.models.enums import (
    ESTADOS_QUE_OCUPAN,
    AlcanceDia,
    Deporte,
    EstadoReserva,
    EstadoTorneo,
    EtapaTorneo,
    FormatoTorneo,
    MedioPago,
    OrigenReserva,
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
    "Base",
    "Cancha",
    "Cliente",
    "Competidor",
    "Deporte",
    "EstadoReserva",
    "EstadoTorneo",
    "EtapaTorneo",
    "Feriado",
    "FormatoTorneo",
    "IntegranteDeCompetidor",
    "MedioPago",
    "OrigenReserva",
    "ParcialDePartido",
    "PartidoDeTorneo",
    "Reserva",
    "Serie",
    "Sucursal",
    "Tarifa",
    "Torneo",
    "Zona",
    "WHERE_OCUPA",
]
