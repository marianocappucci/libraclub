"""Maestros: sucursales, canchas, clientes, feriados y horarios de atención."""

from __future__ import annotations

from datetime import date, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Anotable, Auditable, Base
from app.models.enums import AlcanceDia, Deporte


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

    #: Con cuántas horas de anticipación hay que cancelar para que **se devuelva
    #: la seña**. Cancelar siempre se puede; lo que cambia es si el complejo
    #: devuelve la plata.
    #:
    #: 🔴 **`NULL` significa «no hay devolución automática», y es el default a
    #: propósito.** Una migración que deje esta columna en 24 le prende la
    #: devolución de plata a todas las instancias que ya existen, sin que nadie
    #: lo haya decidido. La política se enciende cargando el número en la
    #: pantalla de la sucursal.
    #:
    #: Vive en la sucursal y no en la cancha porque la política es del complejo:
    #: «devolvemos si avisás con un día» no cambia según en qué cancha ibas a
    #: jugar. Si algún día cambia, la columna baja a `canchas` con el mismo
    #: nombre y esta pasa a ser el default.
    horas_de_cancelacion: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
    #: Si quiere recibir confirmaciones y recordatorios de sus turnos.
    #:
    #: Arranca en `True` —quien deja su email al reservar espera que le llegue el
    #: turno— y el que dice «no me escriban más» se apaga acá. Es una columna del
    #: cliente y no una lista de bajas aparte: la baja tiene que viajar con él,
    #: si no, el día que se exporte o se migre la tabla se pierde y le vuelven a
    #: escribir justamente a quien pidió que no.
    acepta_avisos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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


class FranjaDeAtencion(Base, Auditable):
    """Cuándo está abierto el complejo. Lo que decide qué turnos existen.

    🔴 **Antes de esto el horario estaba hardcodeado en 8:00–00:00**, igual para
    toda cancha, sucursal y día de la semana (`disponibilidad.APERTURA`). O sea
    que la agenda ofrecía turnos que el complejo no da — el lunes a las 8 de la
    mañana de un club que abre a las 16, por ejemplo — y el alta no validaba
    nada, así que por API entraba una reserva a las 4 de la madrugada.

    Sigue el **mismo patrón de resolución que `Tarifa`**: alcance por día
    (`feriado` > `dia_semana` > `todos`) y cancha > sucursal (`cancha_id IS
    NULL`). Que sea el mismo no es casualidad ni copia: quien configura tarifas
    ya aprendió estas reglas, y dos maestros parecidos con reglas distintas es
    de donde salen los errores de carga.

    🔑 **Pero a diferencia de la tarifa, no gana UNA: se toman TODAS las del
    nivel más específico que tenga alguna.** Una tarifa resuelve un precio, que
    es un valor único; un horario resuelve un conjunto, porque un complejo puede
    abrir de 9 a 13 y de 16 a 24. Elegir una sola franja borraría el turno de la
    tarde sin que nada avise.

    ## El cruce de medianoche

    `cierra <= abre` significa **que cierra al día siguiente**, que en pádel es
    lo normal: se abre a las 16 y se cierra a las 02. No hay una columna
    booleana para eso porque no hace falta — un horario que "termina antes de
    empezar" sólo puede querer decir eso.

    El caso borde `abre == cierra` son **24 horas**, y sale del mismo cálculo
    sin ninguna rama especial: el fin se corre un día y el intervalo mide 24 h.
    """

    __tablename__ = "franjas_de_atencion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sucursal_id: Mapped[int] = mapped_column(
        ForeignKey("sucursales.id", ondelete="CASCADE"), nullable=False
    )
    #: `NULL` = aplica a todas las canchas de la sucursal. Existe para la cancha
    #: que tiene luces y cierra más tarde que el resto.
    cancha_id: Mapped[int | None] = mapped_column(
        ForeignKey("canchas.id", ondelete="CASCADE"), nullable=True
    )

    alcance_dia: Mapped[AlcanceDia] = mapped_column(
        Enum(AlcanceDia, name="alcance_dia", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=AlcanceDia.TODOS,
    )
    #: 0 = lunes … 6 = domingo. Obligatorio si `alcance_dia = 'dia_semana'`, y
    #: prohibido en los otros dos casos — lo garantiza un CHECK, no el código.
    dia_semana: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: En **hora de pared del complejo**, igual que la tarifa. Ver `app/tiempo.py`.
    abre: Mapped[time] = mapped_column(Time, nullable=False)
    cierra: Mapped[time] = mapped_column(Time, nullable=False)

    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        # 🔑 **No hay `CheckConstraint("abre < cierra")`, a propósito.** Es el que
        # tiene la tarifa, y acá sería exactamente el bug: prohibiría el complejo
        # que cierra a las 02:00, que es la mayoría.
        CheckConstraint(
            "(alcance_dia = 'dia_semana' AND dia_semana IS NOT NULL "
            " AND dia_semana BETWEEN 0 AND 6) "
            "OR (alcance_dia <> 'dia_semana' AND dia_semana IS NULL)",
            name="ck_franjas_dia_semana_coherente",
        ),
        Index("ix_franjas_sucursal", "sucursal_id"),
        Index("ix_franjas_cancha", "cancha_id"),
    )


class CuentaDeJugador(Base, Auditable):
    """La cuenta con la que un jugador entra al portal público.

    🔴 **Tabla propia y no columnas en `Cliente`, y no `usuarios` de libraauth.**
    Son tres cosas distintas que se parecen:

    - `usuarios` (libraauth) son **operadores**: entran al sistema de gestión,
      tienen rol `admin`/`staff` y los da de alta el complejo. Un jugador con una
      fila ahí podría entrar a la agenda de todos.
    - `Cliente` es **el dato de negocio**: a quién se le factura y a quién se le
      cobra la cuenta corriente. Lo carga el mostrador, puede ser una empresa, y
      existe sin que nadie se registre.
    - Esto es **quién se logueó desde internet**. Un cliente puede no tener
      cuenta —la mayoría— y una cuenta siempre apunta a un cliente.

    Mezclarlas es lo que convierte un portal público en una puerta al backoffice.

    🔑 **`cliente_id` no es único a propósito.** Dos personas del mismo grupo
    pueden tener cuenta y reservar para «Los Martes»; lo que no puede repetirse
    es el email, que es con lo que se entra.
    """

    __tablename__ = "cuentas_de_jugador"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=False
    )
    #: Con lo que se entra. Se guarda en minúsculas —lo normaliza el servicio—
    #: porque nadie recuerda si se registró con mayúscula.
    email: Mapped[str] = mapped_column(String(120), nullable=False)
    #: El mismo formato que `libraauth`: se hashea con su `hash_password` para
    #: no tener dos esquemas de contraseña en el mismo producto.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    cliente: Mapped[Cliente] = relationship()

    __table_args__ = (
        # Citext no: se normaliza a minúsculas al escribir. Un UNIQUE sobre
        # texto crudo dejaría entrar `Juan@x.com` y `juan@x.com` como dos
        # cuentas, y la segunda no podría entrar nunca.
        UniqueConstraint("email", name="uq_cuentas_jugador_email"),
        Index("ix_cuentas_jugador_cliente", "cliente_id"),
    )
