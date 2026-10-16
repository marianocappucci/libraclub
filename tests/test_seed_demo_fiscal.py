"""La semilla de la demo no escribe datos fiscales de forma real (ADR-061 de libracore).

LibraClub no tiene un test que corra `scripts/seed_demo.py` (habla HTTP contra una instancia y firma el captcha), así
que acá se mira el **texto**: ningún CUIT con verificador válido y fuera del rango reservado `99999xxx`, que no se puede
distinguir de uno real. Los inventados que no cierran el verificador no existen en el padrón y no cuentan.
"""
from pathlib import Path

import pytest
from libracore.demo import auditar_literales

RAIZ = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("archivo", ["scripts/seed_demo.py", "scripts/semilla_dev.py"])
def test_el_texto_de_la_semilla_no_tiene_cuit_de_forma_real(archivo):
    hallazgos = auditar_literales((RAIZ / archivo).read_text(encoding="utf-8"), archivo)
    assert hallazgos == [], "\n".join(str(h) for h in hallazgos)
