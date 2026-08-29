"""Lo que se le avisó al cliente sobre su turno.

🔑 **Esta tabla es un registro, no una cola.** No hay filas `pendiente`: lo que
falta mandar se **deduce de las reservas** en cada barrida, y acá se anota
únicamente lo que ya se intentó. El porqué está en `servicios/avisos.py` y en
DECISIONS.md ADR-015; en dos líneas: una cola hay que llenarla desde cada camino
que confirma o cancela un turno, y este producto tiene **tres** —el mostrador,
el `cambiar_estado` y el webhook de MercadoPago, que escribe
`reserva.estado = CONFIRMADA` a mano—. El día que aparezca un cuarto, la cola se
queda callada y nadie se entera; la barrida lo levanta sola.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Auditable, Base
from app.models.enums import CanalAviso, EstadoAviso, TipoAviso
from app.models.reservas import Reserva


class Aviso(Base, Auditable):
    """Un intento de avisarle algo al cliente de una reserva."""

    __tablename__ = "avisos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reserva_id: Mapped[int] = mapped_column(
        ForeignKey("reservas.id", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[TipoAviso] = mapped_column(
        Enum(TipoAviso, name="tipo_aviso", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    canal: Mapped[CanalAviso] = mapped_column(
        Enum(CanalAviso, name="canal_aviso", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    #: Con cuánta anticipación, en horas. Sólo para `RECORDATORIO`; `NULL` en los
    #: otros dos, que no tienen anticipación que declarar.
    horas_antes: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    estado: Mapped[EstadoAviso] = mapped_column(
        Enum(EstadoAviso, name="estado_aviso", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    #: A dónde salió, **congelado**. No se lee del cliente al mostrar: si mañana
    #: cambia su email, la pregunta que aparece es "¿a qué dirección se mandó?",
    #: y la respuesta correcta es la vieja. Vacío cuando el estado es `OMITIDO`
    #: justamente porque no había a dónde mandarlo.
    destino: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    #: Lo que efectivamente se mandó. Se guarda en vez de re-renderizarse al
    #: mirarlo: el texto sale de una plantilla y de los datos del turno, y los
    #: dos cambian. Un aviso que se muestra distinto de como salió no sirve para
    #: resolver la discusión con el cliente, que es para lo único que se mira.
    asunto: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cuerpo: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: El motivo, cuando no salió. Para `OMITIDO` es la regla que lo dejó afuera
    #: —«sin email», «no acepta avisos»—; para `FALLIDO`, lo que dijo el
    #: servidor SMTP.
    detalle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    intentos: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    enviado_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    reserva: Mapped[Reserva] = relationship()

    __table_args__ = (
        # 🔴 **Es lo único que impide mandar el mismo aviso dos veces**, y no es
        # una prolijidad: el cron corre cada pocos minutos y la barrida vuelve a
        # evaluar exactamente las mismas reservas. Sin esta clave, un turno del
        # viernes recibe un recordatorio por cada corrida entre las 24 h y la
        # hora del partido — unas 280 con un cron de cinco minutos.
        #
        # `horas_antes` entra en la clave porque el recordatorio de 24 h y el de
        # 2 h son **avisos distintos del mismo tipo**; sin ella, mandar el
        # primero cancela el segundo para siempre. Y va con `NULLS NOT DISTINCT`
        # (PostgreSQL 15+) porque en confirmación y cancelación es `NULL`, y con
        # la semántica normal dos `NULL` no colisionan: la clave no aplicaría
        # justamente a los dos tipos que **nunca** se repiten.
        UniqueConstraint(
            "reserva_id",
            "tipo",
            "canal",
            "horas_antes",
            name="uq_avisos_reserva_tipo_canal",
            postgresql_nulls_not_distinct=True,
        ),
        # La barrida pregunta "qué avisos tienen estas reservas" con un `IN` de
        # los ids del rango de la corrida. Sin índice eso es un seq scan sobre
        # una tabla que crece con cada turno de cada sucursal.
        Index("ix_avisos_reserva", "reserva_id"),
        Index("ix_avisos_estado", "estado"),
    )
