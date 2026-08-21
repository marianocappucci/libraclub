"""El bloque `agenda` del resumen: lo que el dueño mira de un complejo.

Es lo que este producto le aporta al panel del cliente
(`wiki/analyses/panel-del-dueno-multisucursal.md`), además del núcleo que trae
LibraCore y del comercio que trae LibraCommerce.

🔑 **La ocupación es EL número del negocio de canchas.** Facturado y cobrado los
tiene cualquier rubro; lo que un dueño de complejo mira para decidir —si sube la
tarifa del viernes, si le conviene una cancha más, si el horario de la mañana da
pérdida— es qué porcentaje de las horas que tiene abiertas realmente vendió.

🔴 **Y recién ahora se puede calcular.** Hasta el 2026-08-21 el horario de
atención estaba hardcodeado en 8:00–00:00 para todo complejo y todo día, así que
"horas disponibles" era un número inventado: un club que abre a las 16 habría
mostrado una ocupación de la mitad de la real. El denominador sale de
`servicios/horarios.py`.

## Por qué no va en LibraGenda

El wiki lo listaba como pendiente **de ese motor**, y no corresponde: LibraClub
consume de LibraGenda **dominio puro y no persistencia** (DECISIONS.md ADR-004),
así que el motor no conoce estas tablas ni podría consultarlas. Subirlo allá
sería inventar un acoplamiento para un solo consumidor.

Se escribe acá, como hizo Contalibra con la Fase 0, y **se sube al motor cuando
aparezca el segundo producto que lo necesite** — que es el criterio de
`auditoria-duplicacion-familia-libra`: se sube lo duplicado, no lo que podría
duplicarse.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import EstadoReserva
from app.models.maestros import Cancha
from app.models.reservas import Reserva
from app.servicios import horarios
from app.tiempo import TZ

#: Los estados que cuentan como una reserva vendida. `BLOQUEO` queda afuera —no
#: es una venta, es la cancha sacada de circulación— y `CANCELADA` también.
#: `AUSENTE` **sí** entra: el cliente no vino pero el turno se ocupó y en general
#: se cobra; contarlo como no vendido escondería la plata.
VENDIDAS: tuple[EstadoReserva, ...] = (
    EstadoReserva.PROVISORIA,
    EstadoReserva.PENDIENTE_PAGO,
    EstadoReserva.CONFIRMADA,
    EstadoReserva.JUGADA,
    EstadoReserva.AUSENTE,
)


def _minutos(desde_dt: datetime, hasta_dt: datetime) -> float:
    return (hasta_dt - desde_dt).total_seconds() / 60


def horas_disponibles(sesion: Session, desde: date, hasta: date) -> float:
    """Las horas que el complejo tuvo abiertas en el período, sumando canchas.

    Es el denominador de la ocupación. Se recorre día por día y cancha por
    cancha porque el horario **es por cancha y por día**: la que tiene luces
    cierra más tarde, y el sábado abre distinto del martes.

    Sólo cuentan las canchas **activas**: una dada de baja no está disponible
    para vender, y meterla en el denominador bajaría la ocupación de todas las
    demás sin que nadie entienda por qué.
    """
    canchas = list(sesion.scalars(select(Cancha).where(Cancha.activa.is_(True))))
    total = 0.0
    dia = desde
    while dia <= hasta:
        for cancha in canchas:
            for inicio, fin in horarios.franjas_del_dia(sesion, cancha, dia):
                total += _minutos(inicio, fin)
        dia += timedelta(days=1)
    return round(total / 60, 2)


def resumen_agenda(sesion: Session, desde: str, hasta: str) -> dict:
    """Reservas, ocupación y cancelaciones del período.

    ⚠️ **El rango se interpreta en hora local del complejo y es inclusivo en los
    dos extremos**, igual que el resto del resumen: `desde=2026-09-01` y
    `hasta=2026-09-01` es *ese día entero*, de 00:00 a 24:00. Tomarlo como
    instantes UTC correría la frontera tres horas y movería a otro mes las
    reservas de las últimas noches.
    """
    desde_d = date.fromisoformat(desde)
    hasta_d = date.fromisoformat(hasta)
    inicio = datetime.combine(desde_d, datetime.min.time(), tzinfo=TZ)
    fin = datetime.combine(hasta_d + timedelta(days=1), datetime.min.time(), tzinfo=TZ)

    def _contar(estados):
        filas = sesion.execute(
            select(
                func.count(Reserva.id),
                func.coalesce(func.sum(Reserva.precio), 0),
                func.coalesce(
                    func.sum(
                        func.extract("epoch", Reserva.termina_at - Reserva.comienza_at)
                    ),
                    0,
                ),
            ).where(
                Reserva.estado.in_(estados),
                Reserva.comienza_at >= inicio,
                Reserva.comienza_at < fin,
            )
        ).one()
        return int(filas[0]), Decimal(str(filas[1] or 0)), float(filas[2] or 0) / 3600

    cantidad, monto, horas_vendidas = _contar(VENDIDAS)
    canceladas, _, _ = _contar((EstadoReserva.CANCELADA,))
    ausentes, _, _ = _contar((EstadoReserva.AUSENTE,))
    disponibles = horas_disponibles(sesion, desde_d, hasta_d)

    return {
        "reservas": {"cantidad": cantidad, "monto": float(monto)},
        "horas_vendidas": round(horas_vendidas, 2),
        "horas_disponibles": disponibles,
        # 🔑 `null` y no `0` cuando el complejo no abrió un solo minuto en el
        # período. Dividir daría ZeroDivisionError, y mandar 0 diría "no
        # vendieron nada" cuando lo cierto es "no hubo nada que vender" — la
        # misma distinción entre ausente y cero que el resumen ya hace con los
        # bloques enteros, un nivel más abajo.
        "ocupacion_pct": (
            round(horas_vendidas / disponibles * 100, 1) if disponibles > 0 else None
        ),
        "canceladas": canceladas,
        # Se separa de `canceladas` porque miden cosas distintas: cancelar avisa
        # y libera la cancha a tiempo, no venir la quema. Es el número que dice
        # si conviene exigir seña.
        "ausentes": ausentes,
    }
