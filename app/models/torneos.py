"""Torneos: competidores, zonas, fixture y resultados.

Un torneo **no ocupa canchas por sí mismo**: lo que las ocupa es el bloqueo que
se crea al programar cada partido, que es una fila de `reservas` como cualquier
otra. Es la misma decisión que toma `Serie` con las canchas fijas, y por el
mismo motivo: el constraint de exclusión sólo puede mirar su propia tabla, así
que un partido de torneo guardado en otro lado no impediría que alguien alquile
esa cancha a esa hora.
"""

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
from app.models.enums import Deporte, EstadoTorneo, EtapaTorneo, FormatoTorneo


class Torneo(Base, Auditable, Anotable):
    """El torneo. Su formato decide cómo se arma el fixture y ya no cambia.

    🔑 **`sets_para_ganar` es lo que unifica los deportes.** Un partido de fútbol
    es un partido a un parcial —el resultado— y uno de pádel es al mejor de tres.
    Con esa única columna, cargar un resultado es el mismo código para los dos y
    no hay una rama `if deporte == FUTBOL` esperando al deporte que nadie previó.

    `cantidad_zonas` y `clasifican_por_zona` existen **sólo** en formato
    `zonas`. Un CHECK lo garantiza en vez de dejarlos en 1 y 0 para los otros
    formatos: un número que miente es peor que un `NULL`, porque el que lo lee
    no tiene forma de saber que no significa nada.
    """

    __tablename__ = "torneos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sucursal_id: Mapped[int] = mapped_column(
        ForeignKey("sucursales.id", ondelete="RESTRICT"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    deporte: Mapped[Deporte] = mapped_column(
        Enum(Deporte, name="deporte", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=Deporte.PADEL,
    )
    formato: Mapped[FormatoTorneo] = mapped_column(
        Enum(
            FormatoTorneo,
            name="formato_torneo",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    estado: Mapped[EstadoTorneo] = mapped_column(
        Enum(
            EstadoTorneo,
            name="estado_torneo",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=EstadoTorneo.ARMADO,
    )

    #: Cuándo se juega. Es informativo —lo que ocupa la cancha es el bloqueo de
    #: cada partido— pero es lo que se publica y por lo que pregunta la gente.
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)

    #: Cuántos parciales hay que ganar. 1 = fútbol (un resultado), 2 = al mejor
    #: de tres, 3 = al mejor de cinco.
    sets_para_ganar: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    cantidad_zonas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clasifican_por_zona: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: La semilla del sorteo. 🔑 **Se guarda para que el sorteo sea auditable**:
    #: con este número y la lista de inscriptos, cualquiera reproduce el mismo
    #: cuadro. Sin ella, "¿por qué me tocó el 1º en primera ronda?" no tiene
    #: respuesta verificable, que en un torneo con premio es un problema.
    semilla: Mapped[int | None] = mapped_column(Integer, nullable=True)

    competidores: Mapped[list[Competidor]] = relationship(
        back_populates="torneo", cascade="all, delete-orphan"
    )
    zonas: Mapped[list[Zona]] = relationship(
        back_populates="torneo", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("sucursal_id", "nombre", name="uq_torneos_sucursal_nombre"),
        CheckConstraint("hasta IS NULL OR hasta >= desde", name="ck_torneos_rango"),
        CheckConstraint(
            "sets_para_ganar BETWEEN 1 AND 5", name="ck_torneos_sets_para_ganar"
        ),
        # Los dos parámetros de zonas existen sólo en el formato que los usa, y
        # cuando existen tienen que tener sentido: menos de dos zonas no es un
        # torneo por zonas, y cero clasificados dejaría el playoff vacío.
        #
        # ⚠️ El tope de 2 clasificados no es arbitrario: es hasta dónde llega la
        # regla de cruce de `fixture.orden_de_clasificados`. Ver su docstring.
        CheckConstraint(
            "(formato = 'zonas' AND cantidad_zonas >= 2 "
            " AND clasifican_por_zona BETWEEN 1 AND 2) "
            "OR (formato <> 'zonas' AND cantidad_zonas IS NULL "
            " AND clasifican_por_zona IS NULL)",
            name="ck_torneos_zonas_coherente",
        ),
        Index("ix_torneos_sucursal", "sucursal_id"),
    )


class Zona(Base, Auditable):
    """Un grupo del torneo. Sólo existe en formato `zonas`.

    Una liga —todos contra todos, sin playoff— **no crea zonas**: sus partidos
    van con `zona_id` en `NULL`. Inventarle una zona «Única» pondría un
    encabezado sin información arriba de la única tabla de posiciones.
    """

    __tablename__ = "zonas_de_torneo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    torneo_id: Mapped[int] = mapped_column(
        ForeignKey("torneos.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(40), nullable=False)

    torneo: Mapped[Torneo] = relationship(back_populates="zonas")

    __table_args__ = (
        UniqueConstraint("torneo_id", "nombre", name="uq_zonas_torneo_nombre"),
        Index("ix_zonas_torneo", "torneo_id"),
    )


class Competidor(Base, Auditable, Anotable):
    """Quién juega: una pareja de pádel, un equipo de fútbol, un tenista.

    🔑 **Uno solo para los tres casos.** Lo que cambia entre deportes es cuánta
    gente lo integra, y eso vive en `integrantes`. Un modelo con `Pareja` y
    `Equipo` separados duplicaría el fixture entero, que es lo mismo para los
    dos.

    `nombre` es lo que se dibuja en el cuadro y es obligatorio: «Los Pumas» o
    «Pérez / García». La pantalla lo propone a partir de los integrantes cuando
    son dos, pero lo guardado es el nombre — el cuadro de un torneo se lee de
    lejos y no puede depender de una concatenación que cambie si alguien corrige
    un apellido a mitad de campeonato.
    """

    __tablename__ = "competidores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    torneo_id: Mapped[int] = mapped_column(
        ForeignKey("torneos.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    #: La zona que le tocó en el sorteo. `NULL` mientras no se sorteó, y siempre
    #: en los formatos que no tienen zonas.
    zona_id: Mapped[int | None] = mapped_column(
        ForeignKey("zonas_de_torneo.id", ondelete="SET NULL"), nullable=True
    )
    #: Cabeza de serie: 1 es la primera. `NULL` = entra al bombo.
    #:
    #: 🔴 Las sembradas **no se sortean**: van a posiciones fijas del cuadro para
    #: no cruzarse antes de tiempo. Sortearlas junto al resto haría que la
    #: siembra no signifique nada.
    siembra: Mapped[int | None] = mapped_column(Integer, nullable=True)

    torneo: Mapped[Torneo] = relationship(back_populates="competidores")
    integrantes: Mapped[list[IntegranteDeCompetidor]] = relationship(
        back_populates="competidor", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("torneo_id", "nombre", name="uq_competidores_torneo_nombre"),
        # Dos cabezas de serie con el mismo número no se pueden ordenar, y el
        # sorteo tendría que elegir por criterio propio cuál va primero.
        Index(
            "uq_competidores_siembra",
            "torneo_id",
            "siembra",
            unique=True,
            postgresql_where="siembra IS NOT NULL",
        ),
        CheckConstraint("siembra IS NULL OR siembra >= 1", name="ck_competidores_siembra"),
        Index("ix_competidores_torneo", "torneo_id"),
        Index("ix_competidores_zona", "zona_id"),
    )


class IntegranteDeCompetidor(Base, Auditable):
    """Quién juega adentro de un competidor, y cómo se lo llama por teléfono.

    El teléfono vive acá y **no** en `Competidor`: en una pareja de pádel los dos
    números importan, y un único campo de contacto obligaría a elegir uno. En un
    equipo de fútbol se carga sólo el capitán y el resto queda sin número, que es
    exactamente lo que hace falta.
    """

    __tablename__ = "integrantes_de_competidor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competidor_id: Mapped[int] = mapped_column(
        ForeignKey("competidores.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)

    competidor: Mapped[Competidor] = relationship(back_populates="integrantes")

    __table_args__ = (Index("ix_integrantes_competidor", "competidor_id"),)


class PartidoDeTorneo(Base, Auditable):
    """Un cruce del fixture. Con o sin cancha, con o sin resultado.

    🔑 **`avanza_a_id` es lo que hace que el cuadro se mueva solo.** Al cargar un
    resultado, el ganador se escribe en el slot que este partido alimenta; sin
    ese enlace habría que deducir a quién le toca, y esa deducción —con byes de
    por medio— es justo la que sale mal.

    `reserva_id` apunta al **bloqueo** que ocupa la cancha. Es `NULL` mientras el
    partido no tenga día y hora, que es el estado normal apenas se sortea.
    """

    __tablename__ = "partidos_de_torneo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    torneo_id: Mapped[int] = mapped_column(
        ForeignKey("torneos.id", ondelete="CASCADE"), nullable=False
    )
    etapa: Mapped[EtapaTorneo] = mapped_column(
        Enum(
            EtapaTorneo,
            name="etapa_torneo",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    #: La zona, en los partidos de grupos de un torneo por zonas. `NULL` en una
    #: liga —que es grupos sin zonas— y siempre en las llaves.
    zona_id: Mapped[int | None] = mapped_column(
        ForeignKey("zonas_de_torneo.id", ondelete="CASCADE"), nullable=True
    )
    #: En grupos es el número de fecha; en llaves, la ronda (1 = la primera que
    #: se juega, la última es la final).
    ronda: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Posición dentro de la ronda. Es el orden del dibujo del cuadro, no el
    #: orden en que se juega.
    orden: Mapped[int] = mapped_column(Integer, nullable=False)

    competidor_a_id: Mapped[int | None] = mapped_column(
        ForeignKey("competidores.id", ondelete="CASCADE"), nullable=True
    )
    competidor_b_id: Mapped[int | None] = mapped_column(
        ForeignKey("competidores.id", ondelete="CASCADE"), nullable=True
    )

    avanza_a_id: Mapped[int | None] = mapped_column(
        ForeignKey("partidos_de_torneo.id", ondelete="CASCADE"), nullable=True
    )
    avanza_a_slot: Mapped[str | None] = mapped_column(String(1), nullable=True)

    #: El bloqueo que ocupa la cancha. Sin `ondelete` en cascada: borrar una
    #: reserva no puede borrar el partido del fixture.
    reserva_id: Mapped[int | None] = mapped_column(
        ForeignKey("reservas.id", ondelete="SET NULL"), nullable=True
    )

    ganador_id: Mapped[int | None] = mapped_column(
        ForeignKey("competidores.id", ondelete="SET NULL"), nullable=True
    )
    #: Un partido jugado sin ganador es un **empate**, que existe en fútbol de
    #: zona. Por eso hace falta el booleano: `ganador_id IS NULL` no alcanza para
    #: distinguir "empataron" de "todavía no se jugó".
    finalizado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    parciales: Mapped[list[ParcialDePartido]] = relationship(
        back_populates="partido",
        cascade="all, delete-orphan",
        order_by="ParcialDePartido.numero",
    )

    __table_args__ = (
        # 🔴 **La zona entra en la clave, y con `NULLS NOT DISTINCT`.** Sin la
        # zona, la fecha 1 de la Zona A y la fecha 1 de la Zona B chocan: las
        # dos son (torneo, grupos, 1, 0). Y con la zona a secas se abre el
        # agujero opuesto — en las llaves `zona_id` es NULL, y en PostgreSQL dos
        # NULL no colisionan, así que el cuadro admitiría dos finales.
        #
        # `NULLS NOT DISTINCT` (PostgreSQL 15+) trata los NULL como iguales, que
        # es justo lo que hace falta acá: una liga y un cuadro tienen una sola
        # posición por (ronda, orden) aunque no tengan zona.
        UniqueConstraint(
            "torneo_id", "etapa", "zona_id", "ronda", "orden",
            name="uq_partidos_torneo_posicion",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "(etapa = 'llaves' AND zona_id IS NULL) OR etapa = 'grupos'",
            name="ck_partidos_zona_segun_etapa",
        ),
        # Nadie juega contra sí mismo. Con `IS DISTINCT FROM` y no `<>` porque
        # los dos pueden ser NULL —un partido de llaves que espera dos
        # ganadores— y `NULL <> NULL` da NULL, que un CHECK acepta.
        CheckConstraint(
            "competidor_a_id IS NULL OR competidor_b_id IS NULL "
            "OR competidor_a_id <> competidor_b_id",
            name="ck_partidos_distintos",
        ),
        CheckConstraint(
            "ganador_id IS NULL OR finalizado", name="ck_partidos_ganador_finalizado"
        ),
        CheckConstraint(
            "(avanza_a_id IS NULL AND avanza_a_slot IS NULL) "
            "OR (avanza_a_id IS NOT NULL AND avanza_a_slot IN ('a', 'b'))",
            name="ck_partidos_avanza_coherente",
        ),
        Index("ix_partidos_torneo", "torneo_id"),
        Index("ix_partidos_zona", "zona_id"),
        Index("ix_partidos_avanza", "avanza_a_id"),
        # Una reserva sostiene UN partido. Sin esto, reprogramar mal dejaría dos
        # partidos colgados del mismo bloqueo y liberar uno le sacaría la cancha
        # al otro.
        Index(
            "uq_partidos_reserva",
            "reserva_id",
            unique=True,
            postgresql_where="reserva_id IS NOT NULL",
        ),
    )


class ParcialDePartido(Base, Auditable):
    """Un set de pádel o de tenis. En fútbol, **el** resultado.

    🔑 Se llama parcial y no set porque en fútbol no hay sets: un partido de
    fútbol se guarda como un único parcial 2–1, y así el mismo código cuenta
    quién ganó en los tres deportes. Ver `Torneo.sets_para_ganar`.
    """

    __tablename__ = "parciales_de_partido"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    partido_id: Mapped[int] = mapped_column(
        ForeignKey("partidos_de_torneo.id", ondelete="CASCADE"), nullable=False
    )
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    puntos_a: Mapped[int] = mapped_column(Integer, nullable=False)
    puntos_b: Mapped[int] = mapped_column(Integer, nullable=False)

    partido: Mapped[PartidoDeTorneo] = relationship(back_populates="parciales")

    __table_args__ = (
        UniqueConstraint("partido_id", "numero", name="uq_parciales_partido_numero"),
        CheckConstraint("numero >= 1", name="ck_parciales_numero"),
        CheckConstraint(
            "puntos_a >= 0 AND puntos_b >= 0", name="ck_parciales_puntos"
        ),
    )
