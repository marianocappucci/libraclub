"""Base declarativa y mixins comunes."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Auditable:
    """`created_at`/`updated_at` en `timestamptz`, y quién lo hizo.

    En un complejo real la pregunta que aparece no es "qué pasó" sino "quién
    cambió esta reserva y cuándo": el turno de las 20:00 movido a las 21:00 sin
    avisar es una discusión con un cliente, no un bug. Sin estas cuatro columnas
    no se puede contestar.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Anotable:
    """Observaciones libres, sin largo máximo.

    Un `varchar(50)` para observaciones se llena el primer mes y lo que sigue es
    gente escribiendo en otro lado.
    """

    observaciones: Mapped[str | None] = mapped_column(String, nullable=True)
