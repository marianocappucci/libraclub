"""El panel del dueño: lo que un complejo ocupó, cobró y perdió, abierto por sucursal.

Es la F5 del ROADMAP y el ADR-027. Lo consumen dos lugares con **el mismo bloque**:
`GET /api/resumen` (clave `club`, que es lo que lee `libra-panel` para sumar entre
instancias) y `GET /api/admin/panel-del-dueno` (la pantalla de LibraClub, que le
suma el top de ausentes y el total consolidado).

🔑 **Extiende `resumen_agenda`, no lo reemplaza.** Aquél es el bloque `agenda` de
la instancia entera (un número por todo el complejo); éste lo abre **por
sucursal** y le agrega lo que un dueño con cinco sucursales necesita para
compararlas: la ocupación por día y hora, los ingresos contra el período
anterior y el origen de las reservas. Comparten los estados que cuentan como
vendidos (`VENDIDAS`), el rango en hora local (`rango_local`) y, sobre todo, el
horario de atención (`horarios.franjas_del_dia`): el denominador de la ocupación
sigue saliendo de un solo lugar.

## Cómo se mide cada cosa

**Ocupación.** Horas reservadas sobre horas abiertas, por celda *día de la
semana × hora local de inicio*. El horario es el real de cada cancha y cada día
(feriados cerrados incluidos) y sólo cuentan las canchas **activas**. Lo
reservado se recorta contra lo abierto **cancha por cancha y hora por hora**:

- una reserva fuera de horario (la cargó un admin a las 3 de la mañana) no
  suma, porque no hay horas abiertas a las que dividir — la ocupación no puede
  pasar de 100 %;
- un ausente puede solaparse con otra reserva de la misma cancha (no ocupa, ver
  `ESTADOS_QUE_OCUPAN`) y recortar contra lo abierto evita contar dos veces la
  misma hora.

Una franja que cruza la medianoche (abre 16, cierra 02) se reparte en el día en
que **realmente** cae cada hora: las 00:30 del sábado son sábado, aunque el
horario sea el del viernes. Y el período se mira como una ventana de pared
`[desde 00:00, hasta+1 00:00)`: las horas abiertas del día anterior que caen
después de la medianoche entran, y las del último día que se pasan de la
medianoche no, igual que las reservas (que se cuentan por su inicio).

**Ingresos.** Tres partes que no se pisan, para que `total` sea una suma honesta:

- `reservas`: lo **cobrado** de los turnos del período que ya se jugaron;
- `senas`: lo cobrado de los turnos que todavía no se jugaron (la plata a
  cuenta) y lo que quedó retenido de los cancelados — siempre **neto de las
  devoluciones**;
- `buffet`: lo **vendido** (confirmado) en el buffet de la sucursal en el período.

Lo cobrado contra un turno se recorta en el **precio del turno**: lo que lo
supera son consumos que el cliente pagó contra la reserva, y ésos ya están en
`buffet`. Contarlos dos veces inflaría el ingreso de las sucursales con más
buffet, que es justo lo que el dueño quiere comparar.

Se mide **por el turno y no por el día del cobro** porque es la misma vara que
reservas, canceladas y ausentes: el panel no puede decir 120 reservas y cobrar
las de otro mes. La contracara es que un turno del período anterior cobrado hoy
suma al anterior. El período anterior es el de igual largo, inmediatamente antes.

Sin la base de LibraCore (la caja y el buffet viven ahí) los ingresos son `None`:
un producto que no puede medir no informa cero (`routers/resumen.py`).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import EstadoReserva, OrigenReserva
from app.models.maestros import Cancha, Cliente, Sucursal
from app.models.reservas import Reserva
from app.servicios import buffet, caja, facturacion, horarios
from app.servicios.resumen_agenda import VENDIDAS, rango_local
from app.tiempo import TZ, ahora

#: El período más largo que se acepta. Cada día de cada cancha cuesta una
#: consulta de horario (`horarios.franjas_del_dia`, que es la única que sabe
#: resolver feriados y franjas), así que un rango sin tope es una forma de
#: tumbar la instancia con un `?desde=2000-01-01`.
MAX_DIAS = 366

#: Cuántos días antes del período se leen los movimientos de caja. Un turno se
#: señó antes de jugarse; esto es lo más anticipada que puede ser esa seña para
#: que se la cuente. Existe para no leer toda la historia de la caja en cada
#: pedido del panel.
ANTICIPO_MAXIMO_DE_SENA_DIAS = 90

#: Cuántos ausentes reincidentes se muestran.
TOP_AUSENTES = 10

#: Estados que no son una reserva y no entran en ningún número de acá: un bloqueo
#: es la cancha sacada de circulación y una en conflicto no ocupa (ADR-022).
_AJENAS = (EstadoReserva.BLOQUEO, EstadoReserva.EN_CONFLICTO)

_CERO = Decimal("0")


class PeriodoInvalido(ValueError):
    """El rango pedido no se puede calcular. El router lo traduce a 422."""


def periodo_anterior(desde: date, hasta: date) -> tuple[date, date]:
    """El período de igual largo que termina el día antes de `desde`."""
    dias = (hasta - desde).days + 1
    return desde - timedelta(days=dias), desde - timedelta(days=1)


def validar_periodo(desde: date, hasta: date) -> None:
    if desde > hasta:
        raise PeriodoInvalido("`desde` no puede ser posterior a `hasta`")
    if (hasta - desde).days + 1 > MAX_DIAS:
        raise PeriodoInvalido(f"El período no puede pasar de {MAX_DIAS} días")


@dataclass(frozen=True, slots=True)
class _Fila:
    """Una reserva del período o del anterior, con lo único que hace falta de ella."""

    id: int
    cancha_id: int
    sucursal_id: int
    cliente_id: int | None
    estado: EstadoReserva
    origen: OrigenReserva
    comienza_at: datetime
    termina_at: datetime
    precio: Decimal


def _trocear_por_hora(inicio: datetime, fin: datetime):
    """`[inicio, fin)` partido en las horas de pared que toca: `(inicio_de_la_hora, minutos)`.

    Con hora local fija (Argentina no tiene horario de verano) sumar a un
    datetime de pared es exacto; por eso se trabaja en `TZ` y no en UTC, donde
    las horas caerían corridas tres lugares en la grilla.
    """
    cursor = inicio.astimezone(TZ)
    fin = fin.astimezone(TZ)
    while cursor < fin:
        hora = cursor.replace(minute=0, second=0, microsecond=0)
        corte = min(fin, hora + timedelta(hours=1))
        yield hora, (corte - cursor).total_seconds() / 60
        cursor = corte


def _filas(
    sesion: Session, inicio: datetime, fin: datetime, sucursal_id: int | None
) -> list[_Fila]:
    consulta = (
        select(
            Reserva.id, Reserva.cancha_id, Cancha.sucursal_id, Reserva.cliente_id,
            Reserva.estado, Reserva.origen, Reserva.comienza_at, Reserva.termina_at,
            Reserva.precio,
        )
        .join(Cancha, Reserva.cancha_id == Cancha.id)
        .where(
            Reserva.comienza_at >= inicio,
            Reserva.comienza_at < fin,
            Reserva.estado.not_in(_AJENAS),
        )
    )
    if sucursal_id is not None:
        consulta = consulta.where(Cancha.sucursal_id == sucursal_id)
    return [
        _Fila(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], Decimal(str(r[8] or 0)))
        for r in sesion.execute(consulta)
    ]


def _celdas(
    sesion: Session,
    canchas: list[Cancha],
    desde: date,
    hasta: date,
    vendidas: list[_Fila],
) -> dict[int, dict[tuple[int, int], list[float]]]:
    """`{sucursal: {(dia, hora): [minutos_abiertos, minutos_reservados]}}`."""
    inicio, fin = rango_local(desde, hasta)

    # Minutos abiertos por (cancha, hora de pared). Se arranca un día antes para
    # alcanzar la franja que abrió ayer y sigue abierta después de la medianoche.
    abierto: dict[tuple[int, datetime], float] = defaultdict(float)
    dia = desde - timedelta(days=1)
    while dia <= hasta:
        for cancha in canchas:
            for abre, cierra in horarios.franjas_del_dia(sesion, cancha, dia):
                for hora, minutos in _trocear_por_hora(max(abre, inicio), min(cierra, fin)):
                    abierto[(cancha.id, hora)] += minutos
        dia += timedelta(days=1)

    reservado: dict[tuple[int, datetime], float] = defaultdict(float)
    ids = {c.id for c in canchas}
    for fila in vendidas:
        if fila.cancha_id not in ids:
            continue
        for hora, minutos in _trocear_por_hora(fila.comienza_at, fila.termina_at):
            reservado[(fila.cancha_id, hora)] += minutos

    sucursal_de = {c.id: c.sucursal_id for c in canchas}
    celdas: dict[int, dict[tuple[int, int], list[float]]] = defaultdict(
        lambda: defaultdict(lambda: [0.0, 0.0])
    )
    for (cancha_id, hora), abiertos in abierto.items():
        celda = celdas[sucursal_de[cancha_id]][(hora.weekday(), hora.hour)]
        celda[0] += abiertos
        celda[1] += min(reservado.get((cancha_id, hora), 0.0), abiertos)
    return celdas


def _pct(parte: float, todo: float) -> float | None:
    """`None` y no `0` si no hubo horas abiertas: ver `resumen_agenda`."""
    return round(parte / todo * 100, 1) if todo > 0 else None


def _franjas(celdas: dict[tuple[int, int], list[float]]) -> list[dict]:
    return [
        {"dia": dia, "hora": hora, "ocupacion_pct": _pct(reservados, abiertos)}
        for (dia, hora), (abiertos, reservados) in sorted(celdas.items())
        if abiertos > 0
    ]


def _ingresos_de_reservas(
    filas: list[_Fila], cobros: dict[int, Decimal], momento: datetime
) -> tuple[dict[int, Decimal], dict[int, Decimal]]:
    """`(reservas, senas)` por sucursal: lo cobrado de los turnos, ver el docstring del módulo."""
    reservas: dict[int, Decimal] = defaultdict(Decimal)
    senas: dict[int, Decimal] = defaultdict(Decimal)
    for fila in filas:
        neto = cobros.get(fila.id, _CERO)
        # Lo que supera el precio son consumos, que ya cuenta el buffet.
        cobrado = min(neto, fila.precio)
        if cobrado <= 0:
            continue
        ya_se_jugo = fila.estado is not EstadoReserva.CANCELADA and fila.termina_at <= momento
        (reservas if ya_se_jugo else senas)[fila.sucursal_id] += cobrado
    return reservas, senas


def _ingresos(
    filas: list[_Fila],
    anteriores: list[_Fila],
    cobros: dict[int, Decimal],
    buffet_actual: dict[int, Decimal],
    buffet_anterior: dict[int, Decimal],
    momento: datetime,
) -> dict[int, dict]:
    reservas, senas = _ingresos_de_reservas(filas, cobros, momento)
    reservas_ant, senas_ant = _ingresos_de_reservas(anteriores, cobros, momento)
    sucursales = (
        set(reservas) | set(senas) | set(buffet_actual)
        | set(reservas_ant) | set(senas_ant) | set(buffet_anterior)
    )
    salida: dict[int, dict] = {}
    for sid in sucursales:
        total = reservas[sid] + senas[sid] + buffet_actual.get(sid, _CERO)
        anterior = reservas_ant[sid] + senas_ant[sid] + buffet_anterior.get(sid, _CERO)
        salida[sid] = {
            "reservas": float(reservas[sid]),
            "senas": float(senas[sid]),
            "buffet": float(buffet_actual.get(sid, _CERO)),
            "total": float(total),
            "total_periodo_anterior": float(anterior),
        }
    return salida


def _sin_ingresos() -> dict:
    return {"reservas": 0.0, "senas": 0.0, "buffet": 0.0, "total": 0.0, "total_periodo_anterior": 0.0}


def _top_de_ausentes(sesion: Session, ausentes: list[_Fila]) -> list[dict]:
    por_cliente: dict[int, int] = defaultdict(int)
    for fila in ausentes:
        if fila.cliente_id is not None:
            por_cliente[fila.cliente_id] += 1
    if not por_cliente:
        return []
    nombres = dict(
        sesion.execute(select(Cliente.id, Cliente.nombre).where(Cliente.id.in_(por_cliente))).all()
    )
    ordenados = sorted(por_cliente.items(), key=lambda kv: (-kv[1], nombres.get(kv[0], ""), kv[0]))
    return [
        {"cliente_id": cid, "nombre": nombres.get(cid, ""), "ausentes": n}
        for cid, n in ordenados[:TOP_AUSENTES]
    ]


def calcular(
    sesion: Session,
    desde: date,
    hasta: date,
    *,
    sucursal_id: int | None = None,
    cancha_id: int | None = None,
    detallado: bool = False,
) -> dict:
    """El bloque `club` del resumen. Con `detallado`, además el top de ausentes y el total.

    `sucursal_id` acota todo el panel a una sucursal. `cancha_id` acota **sólo la
    ocupación** (las franjas y los porcentajes): las reservas, los ingresos y los
    ausentes son del complejo, no de una cancha, y el buffet ni siquiera tiene
    cancha.
    """
    validar_periodo(desde, hasta)
    anterior_desde, anterior_hasta = periodo_anterior(desde, hasta)
    inicio, fin = rango_local(desde, hasta)
    inicio_anterior, _ = rango_local(anterior_desde, anterior_hasta)

    todas = _filas(sesion, inicio_anterior, fin, sucursal_id)
    filas = [f for f in todas if f.comienza_at >= inicio]
    anteriores = [f for f in todas if f.comienza_at < inicio]
    vendidas = [f for f in filas if f.estado in VENDIDAS]

    # Las sucursales activas, más las dadas de baja que vendieron en el período:
    # una sucursal cerrada a mitad de mes no puede desaparecer de su historia.
    consulta = select(Sucursal)
    if sucursal_id is not None:
        consulta = consulta.where(Sucursal.id == sucursal_id)
    sucursales = [
        s for s in sesion.scalars(consulta)
        if s.activa or any(f.sucursal_id == s.id for f in filas)
    ]

    consulta = select(Cancha).where(Cancha.activa.is_(True))
    if sucursal_id is not None:
        consulta = consulta.where(Cancha.sucursal_id == sucursal_id)
    if cancha_id is not None:
        consulta = consulta.where(Cancha.id == cancha_id)
    celdas = _celdas(sesion, list(sesion.scalars(consulta)), desde, hasta, vendidas)

    ingresos = None
    if facturacion.hay_base():
        corte = (inicio_anterior.date() - timedelta(days=ANTICIPO_MAXIMO_DE_SENA_DIAS)).isoformat()
        ingresos = _ingresos(
            filas, anteriores, caja.cobros_netos_por_reserva(corte),
            buffet.vendido_por_sucursal(desde.isoformat(), hasta.isoformat()),
            buffet.vendido_por_sucursal(anterior_desde.isoformat(), anterior_hasta.isoformat()),
            ahora(),
        )

    por_sucursal = []
    for sucursal in sorted(sucursales, key=lambda s: (s.nombre, s.id)):
        propias = [f for f in filas if f.sucursal_id == sucursal.id]
        suyas = celdas.get(sucursal.id, {})
        abiertos = sum(c[0] for c in suyas.values())
        reservados = sum(c[1] for c in suyas.values())
        origen = {o.value: 0 for o in OrigenReserva}
        for f in propias:
            if f.estado in VENDIDAS:
                origen[f.origen.value] += 1
        por_sucursal.append({
            "sucursal_id": sucursal.id,
            "sucursal": sucursal.nombre,
            "ocupacion_pct": _pct(reservados, abiertos),
            "franjas": _franjas(suyas),
            # Las horas detrás del porcentaje: sin ellas nadie puede promediar
            # sucursales (el 50 % de una cancha no pesa como el de diez) y el
            # consolidado entre instancias saldría de un promedio de promedios.
            "horas_abiertas": round(abiertos / 60, 2),
            "horas_reservadas": round(reservados / 60, 2),
            # `None` si esta instancia no puede medir la plata (ver el módulo).
            "ingresos": None if ingresos is None else ingresos.get(sucursal.id, _sin_ingresos()),
            "canceladas": sum(1 for f in propias if f.estado is EstadoReserva.CANCELADA),
            "ausentes": sum(1 for f in propias if f.estado is EstadoReserva.AUSENTE),
            "reservas": sum(1 for f in propias if f.estado in VENDIDAS),
            "origen": origen,
        })

    bloque = {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "por_sucursal": por_sucursal,
    }
    if detallado:
        ids = {s.id for s in sucursales}
        todas_las_celdas: dict[tuple[int, int], list[float]] = defaultdict(lambda: [0.0, 0.0])
        for sid, suyas in celdas.items():
            if sid not in ids:
                continue
            for clave, (abiertos, reservados) in suyas.items():
                todas_las_celdas[clave][0] += abiertos
                todas_las_celdas[clave][1] += reservados
        bloque["top_ausentes"] = _top_de_ausentes(
            sesion, [f for f in filas if f.estado is EstadoReserva.AUSENTE]
        )
        bloque["total"] = {
            "ocupacion_pct": _pct(
                sum(c[1] for c in todas_las_celdas.values()),
                sum(c[0] for c in todas_las_celdas.values()),
            ),
            "franjas": _franjas(todas_las_celdas),
        }
    return bloque
