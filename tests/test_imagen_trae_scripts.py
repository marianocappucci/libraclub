"""La imagen trae `scripts/`, que es de donde el restore lee las migraciones.

El motor de restore de LibraCore corre `import scripts.panel_admin` adentro del
contenedor para leer `get_config().migraciones` del mismo commit que el codigo.
Sin `COPY scripts` en el Dockerfile, eso da `ModuleNotFoundError` y el restore
aborta (falla cerrado). Se fija leyendo el Dockerfile y el `.dockerignore`.
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def test_el_dockerfile_copia_scripts():
    lineas = [l.strip() for l in (RAIZ / "Dockerfile").read_text(encoding="utf-8").splitlines()]
    assert "COPY scripts ./scripts" in lineas


def test_el_dockerignore_no_excluye_scripts():
    ignore = RAIZ / ".dockerignore"
    if not ignore.exists():
        return
    patrones = [l.strip().rstrip("/") for l in ignore.read_text(encoding="utf-8").splitlines()]
    assert not {"scripts", "scripts/panel_admin.py", "scripts/*"} & set(patrones)


def test_panel_admin_existe_y_declara_migraciones():
    fuente = (RAIZ / "scripts" / "panel_admin.py").read_text(encoding="utf-8")
    assert "migraciones=(" in fuente
