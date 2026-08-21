"""La caja por turno: abrir, cobrar, cerrar.

Todo bajo `/api/caja`, la convención de este producto.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_admin, require_staff
from app.servicios import caja as servicio

router = APIRouter(prefix="/api/caja", tags=["caja"])


class AperturaEntrada(BaseModel):
    #: Con cuánto efectivo arranca el cajón. Cero es un valor legítimo.
    monto_inicial: Decimal = Field(ge=0, default=Decimal("0"))
    notas: str = ""


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
    return TurnoSalida(
        id=turno["id"], usuario_id=turno["usuario_id"], apertura=str(turno["apertura"]),
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
    """Abre la caja de quien lo pide. **El mostrador abre su propia caja.**"""
    try:
        return _a_salida(servicio.abrir_turno(usuario, datos.monto_inicial, datos.notas))
    except servicio.TurnoYaAbierto as e:
        raise HTTPException(409, str(e)) from e


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
