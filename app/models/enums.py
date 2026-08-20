"""Enums del dominio.

Todos se materializan como tipos `ENUM` de PostgreSQL: un `varchar` con
convención admite el valor que nadie previó, y el que lo descubre es el reporte
que no cuadra.
"""

from __future__ import annotations

import enum


class Deporte(enum.Enum):
    PADEL = "padel"
    FUTBOL = "futbol"
    TENIS = "tenis"
    BASQUET = "basquet"
    VOLEY = "voley"
    HOCKEY = "hockey"
    OTRO = "otro"


class EstadoReserva(enum.Enum):
    """Ver DECISIONS.md ADR-006.

    Cuáles de estos ocupan la cancha no es una convención: es la cláusula
    `WHERE` del constraint de exclusión. Agregar un valor acá **sin** decidir de
    qué lado del predicado cae deja un estado que no reserva nada o que reserva
    para siempre.
    """

    #: Retenida sin confirmar, con `vence_at`. Es lo que hace posible un portal
    #: público sin que un carrito abandonado deje la cancha muerta.
    PROVISORIA = "provisoria"
    #: Esperando la seña. Se separa de PROVISORIA porque la política de
    #: cancelación es distinta: acá ya hubo intención de pago.
    PENDIENTE_PAGO = "pendiente_pago"
    CONFIRMADA = "confirmada"
    JUGADA = "jugada"
    CANCELADA = "cancelada"
    #: El cliente no vino. Libera la cancha hacia atrás pero no es lo mismo que
    #: cancelar: es el número que mide si conviene exigir seña.
    AUSENTE = "ausente"
    #: No es una reserva. Mantenimiento, torneo, lluvia, uso interno. Vive en
    #: esta tabla —y no en una propia— para que el constraint de exclusión lo
    #: cubra; un bloqueo en otra tabla no puede impedir una reserva.
    BLOQUEO = "bloqueo"


#: Los estados que **ocupan** la cancha. Es la fuente de la cláusula `WHERE` del
#: constraint de exclusión y del filtro de la grilla: se define una sola vez para
#: que la migración y la aplicación no puedan divergir.
ESTADOS_QUE_OCUPAN: tuple[EstadoReserva, ...] = (
    EstadoReserva.PROVISORIA,
    EstadoReserva.PENDIENTE_PAGO,
    EstadoReserva.CONFIRMADA,
    EstadoReserva.JUGADA,
    EstadoReserva.BLOQUEO,
)


class OrigenReserva(enum.Enum):
    """De dónde vino. Es el número que dice si el portal sirvió para algo."""

    MOSTRADOR = "mostrador"
    TELEFONO = "telefono"
    WHATSAPP = "whatsapp"
    PORTAL = "portal"
    SERIE = "serie"


class AlcanceDia(enum.Enum):
    """A qué días aplica una tarifa.

    Se modela explícito y no con un `dia_semana` nullable más un booleano
    `es_feriado`, porque esa combinación admite estados sin sentido —feriado
    *y* martes— y no hay forma de que la base los rechace.
    """

    TODOS = "todos"
    DIA_SEMANA = "dia_semana"
    FERIADO = "feriado"


class MedioPago(enum.Enum):
    EFECTIVO = "efectivo"
    TRANSFERENCIA = "transferencia"
    DEBITO = "debito"
    CREDITO = "credito"
    MERCADOPAGO = "mercadopago"
    OTRO = "otro"
