"""Maestros: sucursales, canchas, clientes y feriados."""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Anotable, Auditable, Base
from app.models.enums import Deporte


class Sucursal(Base, Auditable, Anotable):
    """Un complejo. Entidad de primera clase — ver DECISIONS.md ADR-002.

    ContaLibra no tiene esta tabla: tiene `depositos` y `cajas`, y el punto de
    venta colgado de la instancia. Acá existe desde el día uno porque
    retrofitearla después obliga a tocar canchas, tarifas, caja, reportes y
    facturación al mismo tiempo.

    **No es un tenant.** No hay aislamiento de datos entre sucursales de la
    misma instancia. Un cliente que necesite aislamiento real —o que facture con
    otro CUIT— va en otra instancia.
    """

    __tablename__ = "sucursales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    direccion: Mapped[str | None] = mapped_column(String(160), nullable=True)
    localidad: Mapped[str | None] = mapped_column(String(80), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #: 🔴 Propio por sucursal, y por eso está acá y no en la configuración de la
    #: instancia. La numeración de comprobantes de ARCA es por
    #: `(tipo, punto_venta)` y **no lleva CUIT**: dos sucursales del mismo CUIT
    #: emitiendo con el mismo punto de venta se pisan la numeración entre ellas.
    #: Con la columna acá, la trampa deja de depender de que alguien se acuerde.
    #: Se completa en F3, cuando entre la facturación.
    punto_venta_arca: Mapped[int | None] = mapped_column(Integer, nullable=True)

    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    canchas: Mapped[list[Cancha]] = relationship(back_populates="sucursal")

    __table_args__ = (
        UniqueConstraint("nombre", name="uq_sucursales_nombre"),
        # Sin `unique=True` global: dos sucursales pueden no tener punto de venta
        # todavía (NULL no colisiona en un UNIQUE de PostgreSQL), pero dos que sí
        # lo tengan no pueden compartirlo.
        Index(
            "uq_sucursales_punto_venta",
            "punto_venta_arca",
            unique=True,
            postgresql_where="punto_venta_arca IS NOT NULL",
        ),
    )


class Cancha(Base, Auditable, Anotable):
    """El recurso reservable. En LibraGenda sería un `Resource`."""

    __tablename__ = "canchas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sucursal_id: Mapped[int] = mapped_column(
        ForeignKey("sucursales.id", ondelete="RESTRICT"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    deporte: Mapped[Deporte] = mapped_column(
        Enum(Deporte, name="deporte", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=Deporte.PADEL,
    )
    #: Duración estándar del turno, en minutos. Es un **default de la grilla**, no
    #: un límite: una reserva puede durar otra cosa (un torneo toma tres horas), y
    #: nada en el modelo la obliga a ser múltiplo de esto.
    duracion_turno_min: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    techada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    iluminacion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    superficie: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Orden en la grilla. Sin esto las canchas salen por id y "Cancha 10" queda
    #: antes que "Cancha 2".
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    sucursal: Mapped[Sucursal] = relationship(back_populates="canchas")

    __table_args__ = (
        UniqueConstraint("sucursal_id", "nombre", name="uq_canchas_sucursal_nombre"),
        CheckConstraint(
            "duracion_turno_min > 0 AND duracion_turno_min <= 480",
            name="ck_canchas_duracion_turno",
        ),
        Index("ix_canchas_sucursal", "sucursal_id"),
    )


class Cliente(Base, Auditable, Anotable):
    """Quien reserva. Un jugador, un grupo o una empresa.

    No hay `apellido` separado: en un complejo la reserva se toma por teléfono y
    lo que queda anotado es "Juan de los martes". Partirlo en dos campos genera
    dos columnas medio vacías y una búsqueda peor.
    """

    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Para facturar. Texto y no entero: puede venir con guiones, y un DNI con
    #: cero adelante no sobrevive a un `int`.
    documento: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cuit: Mapped[str | None] = mapped_column(String(13), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_clientes_nombre", "nombre"),
        Index("ix_clientes_telefono", "telefono"),
    )


class Feriado(Base, Auditable):
    """Un día con tarifa y horario distintos, por sucursal.

    Por sucursal y no global: un feriado provincial no aplica igual en dos
    localidades, y `libragenda.Holiday` ya lo modela así.
    """

    __tablename__ = "feriados"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sucursal_id: Mapped[int] = mapped_column(
        ForeignKey("sucursales.id", ondelete="CASCADE"), nullable=False
    )
    dia: Mapped[date] = mapped_column(Date, nullable=False)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    #: Un feriado puede ser "tarifa distinta" o "cerrado". No es lo mismo.
    cerrado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("sucursal_id", "dia", name="uq_feriados_sucursal_dia"),
        Index("ix_feriados_dia", "dia"),
    )
