"""La caja por turno: abrir, cobrar, cerrar.

Todo bajo `/api/caja`, la convención de este producto.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from libracore import medios_pago
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_admin, require_staff
from app.servicios import caja as servicio

router = APIRouter(prefix="/api/caja", tags=["caja"])


class AperturaEntrada(BaseModel):
    #: Con cuánto efectivo arranca el cajón. Cero es un valor legítimo.
    monto_inicial: Decimal = Field(ge=0, default=Decimal("0"))
    notas: str = ""
    #: Sobre qué mostrador. Obligatorio en este producto: acá siempre se está
    #: parado en una sucursal, y el arqueo del cierre es el de ESE cajón.
    caja_id: int


class EgresoEntrada(BaseModel):
    monto: Decimal = Field(gt=0)
    #: De la lista de `servicios/caja.MOTIVOS_DE_EGRESO`. Cerrada a propósito.
    motivo: str
    detalle: str = ""
    medio_pago: str


class CierreEntrada(BaseModel):
    #: Lo que el operador **contó**, no lo que el sistema esperaba.
    monto_declarado: Decimal = Field(ge=0)
    notas: str = ""


class CobroEntrada(BaseModel):
    monto: Decimal = Field(gt=0)
    concepto: str = Field(min_length=1, max_length=200)
    medio_pago: str
    referencia: str = ""
    factura_id: int | None = None


class TurnoSalida(BaseModel):
    id: int
    usuario_id: int
    #: El mostrador sobre el que se abrió. `null` en los turnos anteriores al
    #: 2026-08-28, que nacieron sin caja y quedaron en la de por defecto.
    caja_id: int | None = None
    caja_nombre: str = ""
    apertura: str
    cierre: str | None = None
    monto_inicial: float
    monto_declarado_cierre: float | None = None
    monto_esperado_cierre: float | None = None
    estado: str
    notas: str = ""

    @property
    def diferencia(self) -> float | None:
        if self.monto_declarado_cierre is None or self.monto_esperado_cierre is None:
            return None
        return round(self.monto_declarado_cierre - self.monto_esperado_cierre, 2)


class CierreSalida(TurnoSalida):
    #: 🔑 Se manda calculada y no se deja que la arme la pantalla: es el número
    #: que se mira, y dos pantallas restando por su cuenta terminan mostrando
    #: cosas distintas por un redondeo.
    diferencia_de_caja: float


def _a_salida(turno: dict) -> TurnoSalida:
    caja = servicio.caja_de(turno["caja_id"]) if turno.get("caja_id") else None
    return TurnoSalida(
        id=turno["id"], usuario_id=turno["usuario_id"], apertura=str(turno["apertura"]),
        caja_id=turno.get("caja_id"), caja_nombre=(caja or {}).get("nombre", ""),
        cierre=str(turno["cierre"]) if turno.get("cierre") else None,
        monto_inicial=float(turno["monto_inicial"]),
        monto_declarado_cierre=(
            float(turno["monto_declarado_cierre"])
            if turno.get("monto_declarado_cierre") is not None else None
        ),
        monto_esperado_cierre=(
            float(turno["monto_esperado_cierre"])
            if turno.get("monto_esperado_cierre") is not None else None
        ),
        estado=turno["estado"], notas=turno.get("notas") or "",
    )


@router.post("/turnos", response_model=TurnoSalida, status_code=201)
def abrir(
    datos: AperturaEntrada,
    usuario: dict = Depends(require_staff),
):
    """Abre la caja de quien lo pide, **sobre un mostrador**.

    El mostrador abre su propia caja: el turno es de la persona. Lo que la caja
    agrega es **dónde** — sin eso, dos personas en dos sedes distintas arquean
    contra el mismo montón.
    """
    caja = servicio.caja_de(datos.caja_id)
    if caja is None:
        raise HTTPException(404, "no existe esa caja")
    if not caja.get("activo", 1):
        raise HTTPException(422, "esa caja está dada de baja")
    try:
        return _a_salida(servicio.abrir_turno(
            usuario, datos.monto_inicial, datos.notas, caja_id=datos.caja_id,
        ))
    except servicio.TurnoYaAbierto as e:
        raise HTTPException(409, str(e)) from e


@router.get("/medios-pago")
def medios_de_pago(usuario: dict = Depends(require_staff)) -> list[dict]:
    """`[{valor, etiqueta}]` para los selectores de cobro.

    🔴 **La lista es del backend.** `frontend/src/lib/api.ts` tenía su copia —con
    un comentario que decía *"tiene que coincidir con `MEDIOS_PAGO` del backend
    — si se agrega uno de un lado y no del otro, el cobro da 422"*—, o sea que la
    divergencia estaba **prevista y aceptada** en vez de cerrada. Y ya había
    ocurrido: las dos decían `tarjeta`, que no existe en el vocabulario de la
    familia.

    El subconjunto sigue siendo de este producto (`servicios/caja.MEDIOS_PAGO`);
    lo que se va es la segunda declaración.
    """
    return [
        {"valor": m, "etiqueta": medios_pago.label(m)}
        for m in servicio.MEDIOS_PAGO
    ]


@router.get("/turnos/actual")
def actual(usuario: dict = Depends(require_staff)):
    """El turno abierto de quien pregunta, con su resumen. `null` si no hay.

    🔑 Devuelve el resumen junto con el turno para que la pantalla no tenga que
    hacer dos llamadas: lo que el operador quiere ver es cuánto lleva.
    """
    turno = servicio.turno_abierto(usuario)
    if turno is None:
        return None
    return {"turno": _a_salida(turno), "resumen": servicio.resumen(turno["id"])}


@router.post("/cobros")
def cobrar(datos: CobroEntrada, usuario: dict = Depends(require_staff)):
    """Registra un ingreso en el turno abierto. Devuelve el resumen al momento."""
    try:
        return servicio.cobrar(
            usuario, datos.monto, datos.concepto, datos.medio_pago,
            datos.referencia, datos.factura_id,
        )
    except servicio.SinTurnoAbierto as e:
        raise HTTPException(409, str(e)) from e
    except servicio.MedioDePagoInvalido as e:
        raise HTTPException(422, str(e)) from e


@router.get("/motivos-de-egreso")
def motivos_de_egreso(_: object = Depends(require_staff)) -> list[str]:
    """Por qué puede salir plata del cajón. Lista cerrada: un motivo libre
    convierte el arqueo en algo que no se puede sumar por categoría."""
    return list(servicio.MOTIVOS_DE_EGRESO)


@router.post("/egresos")
def registrar_egreso(datos: EgresoEntrada, usuario: dict = Depends(require_staff)):
    """Plata que **sale** del cajón. Devuelve el resumen al momento.

    🔴 **Sin esto el arqueo sólo podía subir.** El resumen del motor ya netea los
    egresos y este producto no tenía forma de registrar uno: sacar plata dejaba
    el cierre con un faltante sin explicación, indistinguible de un error de
    conteo.
    """
    try:
        return servicio.registrar_egreso(
            usuario, datos.monto, datos.motivo, datos.detalle, datos.medio_pago,
        )
    except servicio.SinTurnoAbierto as e:
        raise HTTPException(409, str(e)) from e
    except servicio.MotivoInvalido as e:
        raise HTTPException(422, str(e)) from e
    except servicio.MedioDePagoInvalido as e:
        raise HTTPException(422, str(e)) from e


@router.delete("/movimientos/{movimiento_id}")
def anular_movimiento(movimiento_id: int, usuario: dict = Depends(require_staff)):
    """Anula un movimiento **del turno abierto de quien lo pide**.

    Es el caso del monto tipeado mal hace treinta segundos. Un arqueo ya cerrado
    no se toca: esa diferencia la firmó alguien.
    """
    try:
        return servicio.anular_movimiento(usuario, movimiento_id)
    except servicio.SinTurnoAbierto as e:
        raise HTTPException(409, str(e)) from e
    except servicio.MovimientoAjeno as e:
        raise HTTPException(404, str(e)) from e


@router.post("/turnos/{turno_id}/cerrar", response_model=CierreSalida)
def cerrar(
    turno_id: int,
    datos: CierreEntrada,
    usuario: dict = Depends(get_current_user),
):
    """Cierra el turno y devuelve el arqueo.

    🔴 **Sólo el dueño del turno o un admin.** Un operador cerrándole la caja a
    otro deja un arqueo con el nombre equivocado, y el que contó la plata no fue
    el que figura. El rol se chequea acá y no con una dependencia porque depende
    del turno que se está cerrando, no sólo de quién pide.
    """
    turno = servicio.turno_por_id(turno_id)
    if turno is None:
        raise HTTPException(404, "no existe ese turno")
    if turno["estado"] != "abierto":
        raise HTTPException(409, "ese turno ya está cerrado")
    if int(turno["usuario_id"]) != int(usuario["id"]) and usuario.get("role") != "admin":
        raise HTTPException(403, "sólo podés cerrar tu propia caja")

    cerrado = servicio.cerrar_turno(turno_id, datos.monto_declarado, datos.notas)
    salida = _a_salida(cerrado)
    return CierreSalida(
        **salida.model_dump(),
        diferencia_de_caja=round(
            (salida.monto_declarado_cierre or 0) - (salida.monto_esperado_cierre or 0), 2
        ),
    )


@router.get("/turnos", response_model=list[TurnoSalida])
def listar(_: object = Depends(require_admin), limite: int = 50):
    """El historial. De admin: es la pantalla donde se miran los cierres ajenos."""
    return [_a_salida(t) for t in servicio.historial(limite)]
