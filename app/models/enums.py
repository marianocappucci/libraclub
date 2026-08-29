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


class TipoAviso(enum.Enum):
    """Qué le estamos diciendo al cliente.

    No hay `RECORDATORIO_24H` y `RECORDATORIO_2H` separados: la anticipación es
    un número —`avisos.horas_antes`— y no parte del nombre. Con el nombre, el
    día que el complejo quiera avisar con 48 h el enum miente o hay que agregar
    un valor y migrar el tipo de PostgreSQL para cambiar una constante.
    """

    CONFIRMACION = "confirmacion"
    RECORDATORIO = "recordatorio"
    CANCELACION = "cancelacion"


class CanalAviso(enum.Enum):
    """Por dónde sale.

    `WHATSAPP` ya está en el vocabulario aunque todavía no haya transporte que
    lo mande: el barrido lo filtra por transporte disponible, no por enum. Es
    barato ahora y es un `ALTER TYPE` sobre una tabla con datos después.
    """

    EMAIL = "email"
    WHATSAPP = "whatsapp"


class EstadoAviso(enum.Enum):
    """En qué terminó el intento.

    No existe `PENDIENTE`, y es la decisión de diseño de la tabla: `avisos` es
    el **registro de lo que se intentó**, no una cola de lo que falta. Lo que
    falta se deduce de las reservas en cada barrida (ver `servicios/avisos.py`).
    """

    ENVIADO = "enviado"
    FALLIDO = "fallido"
    #: El cliente no tiene por dónde recibirlo, o pidió no recibir. Se anota
    #: igual: sin la fila, la barrida siguiente vuelve a evaluarlo y el operador
    #: que pregunta *"¿por qué no le llegó?"* no tiene dónde mirar.
    OMITIDO = "omitido"


class AlcanceDia(enum.Enum):
    """A qué días aplica una tarifa.

    Se modela explícito y no con un `dia_semana` nullable más un booleano
    `es_feriado`, porque esa combinación admite estados sin sentido —feriado
    *y* martes— y no hay forma de que la base los rechace.
    """

    TODOS = "todos"
    DIA_SEMANA = "dia_semana"
    FERIADO = "feriado"


# 🔴 Aca habia un `MedioPago(enum.Enum)` con un vocabulario propio --`debito`,
# `credito`, `otro`-- **distinto del que este producto realmente usa**
# (`servicios/caja.MEDIOS_PAGO`) y distinto del de la familia. Tres
# vocabularios para lo mismo, en el mismo repo.
#
# Era codigo muerto: se exportaba desde `models/__init__.py` y **nadie lo
# importaba**. No es columna de ninguna tabla ni aparece en ninguna migracion --
# verificado con un grep sobre todo el repo, no de memoria. O sea que no hay
# `ALTER TYPE` que hacer ni filas que migrar.
#
# Se saca en vez de dejarse: un enum publico con un tercer vocabulario es una
# invitacion a que el proximo cobro lo use, y ahi si habria datos que migrar.
# El vocabulario vive en `libracore.medios_pago`.


class FormatoTorneo(enum.Enum):
    """Cómo se define el campeón. Se elige al crear el torneo y no cambia.

    🔴 **No cambia porque el fixture ya está sorteado.** Pasar de liga a llaves a
    mitad de camino no es editar un campo: es tirar los partidos jugados. Lo
    impide el servicio, que sólo deja sortear una vez.
    """

    #: Llaves directas: el que pierde se va.
    ELIMINACION = "eliminacion"
    #: Todos contra todos y la tabla decide. Sin playoff y **sin zonas** — sus
    #: partidos van con `zona_id` en `NULL`.
    LIGA = "liga"
    #: Grupos y después playoff entre los que clasifican.
    ZONAS = "zonas"


class EstadoTorneo(enum.Enum):
    """Dónde está parado el torneo.

    🔑 **No hay `EN_CURSO`, y es a propósito.** "Empezó" es lo mismo que "tiene
    algún partido con resultado", y eso ya está en la base: agregar un estado
    obligaría a acordarse de moverlo en cada carga de resultado, y el día que
    alguien se olvide el torneo diría "sorteado" con media llave jugada. Se
    deriva al leer, que no puede desincronizarse.
    """

    #: Inscribiendo. Es el único estado en el que se puede sortear.
    ARMADO = "armado"
    #: Ya tiene fixture. Los competidores no se tocan más.
    SORTEADO = "sorteado"
    #: Se jugó todo. El campeón queda congelado.
    FINALIZADO = "finalizado"
    CANCELADO = "cancelado"


class EtapaTorneo(enum.Enum):
    """De qué parte del torneo es un partido.

    Separa las dos formas de jugar que conviven en un torneo por zonas: la fase
    de grupos, donde se suman puntos, y el playoff, donde el que pierde se va.
    Un torneo de liga tiene sólo `GRUPOS`; uno de eliminación, sólo `LLAVES`.
    """

    GRUPOS = "grupos"
    LLAVES = "llaves"
