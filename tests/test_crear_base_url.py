"""`_crear_base_si_falta` recibe la URL como la escribe la plantilla del alta de
LibraCore (`postgresql+psycopg://`, la forma que SQLAlchemy necesita) y se la
pasa a psycopg, que sólo entiende la forma libpq (`postgresql://`).

Hasta el 2026-09-06 la pasaba cruda: una instancia dada de alta por el
backoffice moría al arrancar con `ProgrammingError: missing "="`. La demo no lo
sufría porque su compose está escrito a mano con la forma plana. Lo encontró el
smoke de navegador, que construye la instancia como el alta.
"""
import pytest

from app.servicios import facturacion


@pytest.fixture
def conexiones(monkeypatch):
    """Captura la cadena que llega a `psycopg.connect` sin conectar a nada."""
    import psycopg

    capturadas: list[str] = []

    class _Conexion:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *a, **kw):
            class _R:
                def fetchone(self):
                    return (1,)  # la base "existe": no se intenta crear nada
            return _R()

    def connect(conninfo, **kw):
        capturadas.append(conninfo)
        return _Conexion()

    monkeypatch.setattr(psycopg, "connect", connect)
    return capturadas


def test_la_forma_de_sqlalchemy_llega_a_psycopg_en_forma_libpq(conexiones):
    facturacion._crear_base_si_falta("postgresql+psycopg://u:p@servidor:5432/libraclub_core")
    assert conexiones == ["postgresql://u:p@servidor:5432/postgres"]


def test_la_forma_plana_sigue_igual(conexiones):
    """Control: la forma que usa la demo hoy no cambia ni un carácter."""
    facturacion._crear_base_si_falta("postgresql://u:p@servidor:5432/libraclub_core")
    assert conexiones == ["postgresql://u:p@servidor:5432/postgres"]


def test_sin_nombre_de_base_no_conecta(conexiones):
    facturacion._crear_base_si_falta("postgresql+psycopg://u:p@servidor:5432/")
    assert conexiones == []
