"""Reservas, bloqueos y series recurrentes.

Acá vive la garantía central del producto: **dos reservas no se pueden pisar**,
y eso lo sostiene la base, no la aplicación. Ver DECISIONS.md ADR-004 y ADR-005.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import TSTZRANGE, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Anotable, Auditable, Base
from app.models.enums import ESTADOS_QUE_OCUPAN, EstadoReserva, OrigenReserva

#: La cláusula `WHERE` del constraint de exclusión, derivada del enum.
#:
#: 🔴 Se construye y no se escribe a mano **para que no pueda divergir**. Un
#: estado nuevo en `EstadoReserva` que alguien agregue a `ESTADOS_QUE_OCUPAN`
#: entra acá solo; escrito a mano, la lista de la migración y la de la
#: aplicación se separan el día que nadie está mirando, y el síntoma es una
#: cancha que se reserva dos veces.
_ESTADOS_SQL = ", ".join(f"'{estado.value}'" for estado in ESTADOS_QUE_OCUPAN)
WHERE_OCUPA = f"estado IN ({_ESTADOS_SQL})"


class Serie(Base, Auditable, Anotable):
    """Una reserva fija recurrente: "los martes a las 20:00, la cancha 3".

    La serie **no ocupa la cancha por sí misma**: es una regla. Lo que ocupa son
    las reservas que genera, y por eso una serie que no se pudo materializar en
    una fecha —porque había un torneo— no rompe las demás.

    Las ocurrencias se calculan con `libragenda.generate_occurrences`, que es
    justamente la parte del motor que no arrastra persistencia.
    """

    __tablename__ = "series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cancha_id: Mapped[int] = mapped_column(
        ForeignKey("canchas.id", ondelete="RESTRICT"), nullable=False
    )
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=False
    )
    #: 0 = lunes … 6 = domingo, en hora local del complejo.
    dia_semana: Mapped[int] = mapped_column(Integer, nullable=False)
    hora: Mapped[time] = mapped_column(Time, nullable=False)
    duracion_min: Mapped[int] = mapped_column(Integer, nullable=False)
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    #: `NULL` = sin fin. Es el caso normal de una cancha fija: el cliente la tiene
    #: "hasta que avise".
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("dia_semana BETWEEN 0 AND 6", name="ck_series_dia_semana"),
        CheckConstraint(
            "duracion_min > 0 AND duracion_min <= 480", name="ck_series_duracion"
        ),
        CheckConstraint("hasta IS NULL OR hasta >= desde", name="ck_series_rango"),
        Index("ix_series_cancha", "cancha_id"),
    )


class Reserva(Base, Auditable, Anotable):
    """Una cancha ocupada durante un intervalo. También los bloqueos.

    Un bloqueo por mantenimiento, lluvia o torneo es una fila de esta tabla con
    `estado = 'bloqueo'` y sin cliente. **No una tabla aparte**: un constraint
    sólo puede mirar su propia tabla, así que un bloqueo de otro lado no podría
    impedir una reserva, y habría que volver a chequear en la aplicación —que es
    exactamente lo que este diseño evita.
    """

    __tablename__ = "reservas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cancha_id: Mapped[int] = mapped_column(
        ForeignKey("canchas.id", ondelete="RESTRICT"), nullable=False
    )
    #: `NULL` sólo para los bloqueos. Lo garantiza un CHECK.
    cliente_id: Mapped[int | None] = mapped_column(
        ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=True
    )
    serie_id: Mapped[int | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"), nullable=True
    )

    estado: Mapped[EstadoReserva] = mapped_column(
        Enum(
            EstadoReserva,
            name="estado_reserva",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=EstadoReserva.CONFIRMADA,
    )
    origen: Mapped[OrigenReserva] = mapped_column(
        Enum(
            OrigenReserva,
            name="origen_reserva",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=OrigenReserva.MOSTRADOR,
    )

    comienza_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    termina_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Columna **generada** por PostgreSQL a partir de las dos de arriba. No se
    #: escribe nunca desde Python: si fuera una columna común, una reserva creada
    #: por un camino que se olvidara de llenarla quedaría fuera del constraint —
    #: invisible para la exclusión y perfectamente insertable encima de otra.
    #:
    #: Intervalo **semiabierto** `[)`: un turno que termina 20:00 y otro que
    #: empieza 20:00 **no** se solapan. Con `[]` compartirían el instante del
    #: borde y no se podrían encadenar dos turnos seguidos, que es el uso normal.
    periodo: Mapped[object] = mapped_column(
        TSTZRANGE,
        Computed("tstzrange(comienza_at, termina_at, '[)')", persisted=True),
        nullable=False,
    )

    #: Congelado al crear la reserva, no resuelto al leerla: si mañana sube la
    #: tarifa, el turno que ya se tomó sigue valiendo lo que se le dijo al
    #: cliente. `NULL` en los bloqueos.
    precio: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    sena: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    #: Cuándo caduca una `provisoria`. El barrido que las vence lee esto.
    vence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Motivo del bloqueo, o de la cancelación. Texto libre del operador.
    motivo: Mapped[str | None] = mapped_column(String(200), nullable=True)

    cancha = relationship("Cancha")
    cliente = relationship("Cliente")

    __table_args__ = (
        CheckConstraint("termina_at > comienza_at", name="ck_reservas_intervalo"),
        # Un bloqueo no tiene cliente; cualquier otra cosa sí. Sin esto,
        # "reserva sin cliente" es un estado que la base acepta y que la grilla
        # muestra como una fila sin nombre que nadie sabe de quién es.
        CheckConstraint(
            "(estado = 'bloqueo' AND cliente_id IS NULL) "
            "OR (estado <> 'bloqueo' AND cliente_id IS NOT NULL)",
            name="ck_reservas_cliente_segun_estado",
        ),
        CheckConstraint(
            "estado <> 'provisoria' OR vence_at IS NOT NULL",
            name="ck_reservas_provisoria_vence",
        ),
        CheckConstraint("precio IS NULL OR precio >= 0", name="ck_reservas_precio"),
        CheckConstraint(
            "sena IS NULL OR precio IS NULL OR sena <= precio", name="ck_reservas_sena"
        ),
        # 🔑 **La garantía del producto.**
        #
        # `cancha_id WITH =` necesita la extensión `btree_gist`: un índice GiST
        # no sabe comparar un entero por igualdad sin ella. La crea la migración.
        #
        # Esto no reemplaza la validación de la aplicación —que existe para dar
        # un mensaje decente— sino que la respalda en el único caso que la
        # aplicación no puede cubrir: dos transacciones simultáneas que leen las
        # dos "está libre" y escriben las dos.
        ExcludeConstraint(
            ("cancha_id", "="),
            ("periodo", "&&"),
            name="ex_reservas_sin_superposicion",
            using="gist",
            where=text(WHERE_OCUPA),
        ),
        Index("ix_reservas_cancha_comienza", "cancha_id", "comienza_at"),
        Index("ix_reservas_cliente", "cliente_id"),
        Index("ix_reservas_serie", "serie_id"),
        # Para el barrido de vencimiento de provisorias: parcial, porque la
        # inmensa mayoría de las filas no son provisorias y no tiene sentido
        # indexarlas.
        Index(
            "ix_reservas_vence_at",
            "vence_at",
            postgresql_where="estado = 'provisoria'",
        ),
    )
