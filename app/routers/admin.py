"""El resumen que consume el panel del dueño — DECISIONS.md ADR-009.

El panel le pregunta a cada instancia por HTTP y suma. **No abre bases**: los
secretos son por instancia, y un panel que administra N instancias no puede
tener N secretos en un solo entorno. Es la decisión que `libra-backoffice` ya
tomó, después de descartar el camino de abrir las bases a mitad de camino.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin_o_servicio
from app.db import obtener_sesion
from app.models.enums import ESTADOS_QUE_OCUPAN, EstadoReserva
from app.models.maestros import Cancha, Sucursal
from app.models.reservas import Reserva
from app.servicios import panel_del_dueno
from app.tiempo import TZ, hoy

router = APIRouter(prefix="/admin", tags=["panel del dueño"])

#: El panel del dueño de la pantalla (F5, ADR-027) cuelga de `/api/admin`, y no del
#: `/admin` de arriba: lo pide el contrato con `libra-panel` y la SPA sólo habla con
#: `/api`. Es un router aparte porque un prefijo es de todo el router.
router_api = APIRouter(prefix="/api/admin", tags=["panel del dueño"])


def _rango(desde: date, hasta: date) -> tuple[datetime, datetime]:
    """El rango en instantes, cerrado por izquierda y abierto por derecha.

    `hasta` inclusive para el que pregunta: pedir del 1 al 31 tiene que incluir
    el 31 entero. Se traduce a "hasta la medianoche del 1 del mes siguiente"
    porque comparar contra las 23:59:59 pierde el último minuto y nadie lo nota
    hasta que un turno de las 23:30 no aparece en el reporte del mes.
    """
    return (
        datetime.combine(desde, time(0, 0), tzinfo=TZ),
        datetime.combine(hasta + timedelta(days=1), time(0, 0), tzinfo=TZ),
    )


@router.get("/resumen")
def resumen(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin_o_servicio),
) -> dict[str, object]:
    """Los números de esta instancia, **abiertos por sucursal**.

    🔑 La apertura por sucursal viaja en el mismo payload y no es opcional. Si
    cada instancia devolviera un solo número agregado, un dueño con tres
    sucursales en una instancia y dos en otra vería cinco complejos aplastados
    en dos filas — y el agregado no se puede volver a abrir del otro lado.
    """
    inicio = desde or hoy().replace(day=1)
    fin = hasta or hoy()
    desde_at, hasta_at = _rango(inicio, fin)

    filas = sesion.execute(
        select(
            Sucursal.id,
            Sucursal.nombre,
            Reserva.estado,
            func.count(Reserva.id),
            func.coalesce(func.sum(Reserva.precio), 0),
        )
        .select_from(Reserva)
        .join(Cancha, Reserva.cancha_id == Cancha.id)
        .join(Sucursal, Cancha.sucursal_id == Sucursal.id)
        .where(Reserva.comienza_at >= desde_at, Reserva.comienza_at < hasta_at)
        .group_by(Sucursal.id, Sucursal.nombre, Reserva.estado)
    ).all()

    por_sucursal: dict[int, dict[str, object]] = {}
    for sucursal_id, nombre, estado, cantidad, importe in filas:
        entrada = por_sucursal.setdefault(
            sucursal_id,
            {
                "sucursal_id": sucursal_id,
                "nombre": nombre,
                "reservas": {},
                "facturable": Decimal(0),
            },
        )
        entrada["reservas"][estado.value] = int(cantidad)
        # Sólo suma lo que ocupó la cancha: una cancelada no es plata, y un
        # bloqueo no tiene precio. Sumar todo daría un número más grande y
        # equivocado, que es la peor combinación en un panel de dueño.
        if estado in ESTADOS_QUE_OCUPAN and estado is not EstadoReserva.BLOQUEO:
            entrada["facturable"] = Decimal(entrada["facturable"]) + Decimal(importe)

    # Las sucursales sin ninguna reserva en el rango **también salen, en cero**.
    # Un bloque ausente no es lo mismo que un cero: el panel que suma N
    # instancias no puede distinguir "no hubo reservas" de "esta sucursal no
    # contestó", y una sucursal cerrada desaparecería de la comparación en vez
    # de mostrar el problema.
    for sucursal_id, nombre in sesion.execute(
        select(Sucursal.id, Sucursal.nombre).where(Sucursal.activa.is_(True))
    ).all():
        por_sucursal.setdefault(
            sucursal_id,
            {
                "sucursal_id": sucursal_id,
                "nombre": nombre,
                "reservas": {},
                "facturable": Decimal(0),
            },
        )

    return {
        "producto": "libraclub",
        "desde": inicio.isoformat(),
        "hasta": fin.isoformat(),
        "sucursales": sorted(por_sucursal.values(), key=lambda s: str(s["nombre"])),
    }


#: Cuántos días mira el panel si no le piden un rango: los últimos 30, contando hoy.
DIAS_POR_DEFECTO = 30


@router_api.get("/panel-del-dueno")
def panel_del_dueno_de_la_instancia(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    sucursal_id: int | None = Query(default=None),
    cancha_id: int | None = Query(default=None),
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin_o_servicio),
) -> dict[str, object]:
    """Ocupación por franja, ingresos, cancelaciones y ausentes, **abiertos por sucursal**.

    Es el mismo bloque que `GET /api/resumen` manda como `club`, más lo que sólo
    tiene sentido en la pantalla: el top de clientes con más ausentes y el total
    de la instancia (`total`, con las franjas de todas las sucursales juntas).
    `cancha_id` acota la ocupación y nada más — ver `panel_del_dueno.calcular`.

    Mismo guard que el resto del admin: dueño o admin. **No** abre con la
    credencial del panel (`LIBRA_PANEL_TOKEN`): esa sólo sirve para `/api/resumen`.
    """
    fin = hasta or hoy()
    inicio = desde or fin - timedelta(days=DIAS_POR_DEFECTO - 1)
    if sucursal_id is not None and sesion.get(Sucursal, sucursal_id) is None:
        raise HTTPException(404, "no existe esa sucursal")
    if cancha_id is not None:
        cancha = sesion.get(Cancha, cancha_id)
        if cancha is None or (sucursal_id is not None and cancha.sucursal_id != sucursal_id):
            raise HTTPException(404, "no existe esa cancha en esa sucursal")
    try:
        return panel_del_dueno.calcular(
            sesion, inicio, fin,
            sucursal_id=sucursal_id, cancha_id=cancha_id, detallado=True,
        )
    except panel_del_dueno.PeriodoInvalido as e:
        raise HTTPException(422, str(e)) from e
