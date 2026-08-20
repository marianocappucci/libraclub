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
    MedioPago,
    OrigenReserva,
)
from app.models.maestros import Cancha, Cliente, Feriado, Sucursal
from app.models.reservas import WHERE_OCUPA, Reserva, Serie
from app.models.tarifas import Tarifa

__all__ = [
    "ESTADOS_QUE_OCUPAN",
    "AlcanceDia",
    "Anotable",
    "Auditable",
    "Base",
    "Cancha",
    "Cliente",
    "Deporte",
    "EstadoReserva",
    "Feriado",
    "MedioPago",
    "OrigenReserva",
    "Reserva",
    "Serie",
    "Sucursal",
    "Tarifa",
    "WHERE_OCUPA",
]
