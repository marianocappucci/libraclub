"""El mapa de etiquetas del frontend cubre todos los deportes del enum.

🔴 **Cruza los dos lados a propósito.** El valor lo define `Deporte` en Python y
lo escribe en pantalla un `Record` de TypeScript; nada del lenguaje ata una cosa
con la otra. Agregar un deporte al enum es una línea, y sin este test el
deporte nuevo aparece **crudo** en cuatro pantallas —minúscula y sin tilde, al
lado de nombres propios— sin que nada falle.

Es la misma idea que `titulos-con-icono.test.ts` del frontend: leer el fuente del
otro lado en vez de esperar que alguien se acuerde de cruzarlos.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.enums import Deporte

MAPA = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "api.ts"


def _claves_del_mapa() -> set[str]:
    texto = MAPA.read_text(encoding="utf-8")
    bloque = re.search(
        r"export const NOMBRE_DE_DEPORTE: Record<string, string> = \{(.*?)\}",
        texto,
        re.S,
    )
    assert bloque, "no se encontró NOMBRE_DE_DEPORTE en frontend/src/lib/api.ts"
    return set(re.findall(r"^\s*(\w+):", bloque.group(1), re.M))


def test_todos_los_deportes_tienen_etiqueta():
    faltan = {d.value for d in Deporte} - _claves_del_mapa()
    assert not faltan, (
        f"estos deportes se verían crudos en pantalla: {sorted(faltan)}. "
        "Agregalos a NOMBRE_DE_DEPORTE en frontend/src/lib/api.ts"
    )


def test_el_mapa_no_inventa_deportes():
    """El control inverso: una etiqueta para un valor que el enum no tiene es
    una que nadie va a ver, y suele ser un valor viejo que ya se sacó."""
    de_mas = _claves_del_mapa() - {d.value for d in Deporte}
    assert not de_mas, f"NOMBRE_DE_DEPORTE tiene claves que el enum no define: {sorted(de_mas)}"


def test_el_control_de_que_el_guard_LEE_algo():
    """Sin esto, los dos de arriba pasarían en verde el día que el regex deje de
    matchear el bloque: dos conjuntos vacíos comparados dan vacío."""
    claves = _claves_del_mapa()
    assert len(claves) >= 5, f"el lector encontró sólo {claves}"
    assert "padel" in claves
