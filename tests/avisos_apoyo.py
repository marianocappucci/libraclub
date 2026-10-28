"""Lo que comparten los tests de avisos desde que el envío es del motor (ADR-030; libracore ADR-090).

- `ProveedorFalso`: un proveedor del motor (`libracore.avisos.Proveedor`) que anota en vez de mandar. Reemplaza al
  `Transporte` de antes; los tests siguen mirando `proveedor.enviados`.
- `guardados()`: lo que quedó en `avisos_envios`, con la forma que tenía la fila de `avisos` (`.tipo`, `.estado`,
  `.horas_antes`, `.reserva_id`...), para que las aserciones sigan diciendo lo mismo que antes.
"""

from __future__ import annotations

from dataclasses import dataclass

from libracore.avisos import Mensaje, Resultado
from libracore.db import avisos_envios as registro
from sqlalchemy import text

from app.models.enums import CanalAviso, EstadoAviso, TipoAviso


class ProveedorFalso:
    """Un proveedor que anota lo que se le pide mandar. `simulado` distingue un canal real de uno de prueba.

    Cumple el mismo contrato que `ProveedorSmtp`, `ProveedorEvolution` y `ProveedorRegistro` (`canal`, `nombre`,
    `simulado`, `disponible()`, `enviar() -> Resultado`) y nada más: que las clases reales lo cumplen lo miden los tests
    del motor.
    """

    nombre = "falso"

    def __init__(self, canal: str | CanalAviso = "email", *, simulado: bool = False, disponible: bool = True,
                 falla: str | None = None, rechaza: str | None = None) -> None:
        self.canal = canal.value if isinstance(canal, CanalAviso) else canal
        self.simulado = simulado
        self._disponible = disponible
        self._falla = falla
        self._rechaza = rechaza
        self.enviados: list[tuple[str, str, str]] = []

    def disponible(self) -> bool:
        return self._disponible

    def enviar(self, mensaje: Mensaje) -> Resultado:
        if self._falla:
            return Resultado.fallido(self._falla)
        if self._rechaza:
            return Resultado.rechazado(self._rechaza)
        self.enviados.append((mensaje.destino, mensaje.asunto, mensaje.cuerpo))
        if self.simulado:
            return Resultado.registrado("Registrado en modo prueba: no se mandó nada.")
        return Resultado.enviado()


@dataclass(frozen=True)
class Guardado:
    """Una fila de `avisos_envios` vista como la fila de `avisos` de antes."""

    id: int
    clave: str
    reserva_id: int
    tipo: TipoAviso
    horas_antes: int | None
    canal: CanalAviso
    #: `EstadoAviso` si el viejo registro lo conocía; el texto del motor si no (`rechazado`, `enviando`).
    estado: EstadoAviso | str
    destino: str
    asunto: str | None
    cuerpo: str | None
    detalle: str | None
    intentos: int
    enviado_at: str | None
    proveedor: str


def _estado(valor: str) -> EstadoAviso | str:
    try:
        return EstadoAviso(valor)
    except ValueError:
        return valor


def guardados() -> list[Guardado]:
    """Todo lo de `avisos_envios`, del más viejo al más nuevo."""
    salida = []
    for fila in sorted(registro.listar(limite=500), key=lambda f: f["id"]):
        _, reserva_id, tipo, horas = fila["clave"].split(":")
        salida.append(Guardado(
            id=fila["id"], clave=fila["clave"], reserva_id=int(reserva_id), tipo=TipoAviso(tipo),
            horas_antes=None if horas == "-" else int(horas), canal=CanalAviso(fila["canal"]),
            estado=_estado(fila["estado"]), destino=fila["destino"], asunto=fila["asunto"] or None,
            cuerpo=fila["cuerpo"] or None, detalle=fila["detalle"] or None, intentos=fila["intentos"],
            enviado_at=fila["enviado_at"] or None, proveedor=fila["proveedor"],
        ))
    return salida


def borrar_guardados(sesion) -> None:
    """Vacía `avisos_envios` (el registro del motor) entre dos vueltas de un mismo test."""
    sesion.execute(text("DELETE FROM avisos_envios"))
    sesion.commit()
