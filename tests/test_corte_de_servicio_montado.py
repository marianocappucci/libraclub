"""Sin el middleware, suspender esta instancia no corta nada: el backoffice dice «Suspendida» y el cliente sigue entrando
(ADR-096 de libracore). Lo que hace el corte se prueba en el motor; acá, que este producto lo monte y en el orden correcto."""
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent / "app" / "main.py"


def test_el_corte_de_servicio_esta_montado_antes_de_las_cabeceras():
    fuente = MAIN.read_text(encoding="utf-8")
    assert "app.add_middleware(CorteDeServicioMiddleware)" in fuente
    assert fuente.index("app.add_middleware(CorteDeServicioMiddleware)") < fuente.index(
        "app.add_middleware(SecurityHeadersMiddleware"
    )
