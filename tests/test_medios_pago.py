"""Con qué cobra un complejo.

🔴 **Este producto elige un subconjunto, y eso está bien.** Un complejo de
canchas no cobra con cheque ni lleva cuenta corriente de mostrador. Lo que
estaba mal era **inventar las claves**: la tupla decía `tarjeta`, que no existe
en el vocabulario de la familia — ARCA parte la tarjeta en débito y crédito.

Y estaba declarada **tres veces** en este repo:

1. `servicios/caja.MEDIOS_PAGO`, la que se usa;
2. `frontend/src/lib/api.MEDIOS_DE_PAGO`, su espejo — con un comentario que
   decía que *"tiene que coincidir... si se agrega uno de un lado y no del otro,
   el cobro da 422"*, o sea que la divergencia estaba **prevista y aceptada** en
   vez de cerrada;
3. `models/enums.MedioPago`, un enum con un **tercer** vocabulario (`debito`,
   `credito`, `otro`) que **nadie importaba** — código muerto que invitaba a
   usarlo.
"""
import pytest
from libracore import medios_pago

from app.servicios import caja


def test_cada_medio_existe_en_el_vocabulario_de_la_familia():
    """🔴 **El test que manda.** El subconjunto se elige; las claves no se
    inventan. `caja.py` lo valida al importar, así que si esto falla es porque
    el módulo ni siquiera cargó — pero queda explícito por qué."""
    for medio in caja.MEDIOS_PAGO:
        assert medios_pago.es_elegible(medio), medio
    # Control positivo: una tupla vacía pasaría el bucle sin medir nada.
    assert len(caja.MEDIOS_PAGO) >= 4, f"quedaron {len(caja.MEDIOS_PAGO)} medios"


def test_la_tarjeta_viene_partida_y_la_vieja_ya_no_se_escribe():
    """`tarjeta` a secas se **lee** —hay cobros registrados con ese medio— pero
    no se escribe. Es la mitad que hace que la normalización avance."""
    assert "tarjeta_debito" in caja.MEDIOS_PAGO
    assert "tarjeta_credito" in caja.MEDIOS_PAGO
    assert "tarjeta" not in caja.MEDIOS_PAGO
    # Pero se sigue sabiendo nombrar, que es lo que los cobros viejos necesitan.
    assert medios_pago.label("tarjeta") == "Tarjeta"


def test_sigue_siendo_un_subconjunto_y_no_la_lista_entera():
    """🔴 El control por el otro lado. Adoptar la canónica **completa** le daría
    a un complejo de canchas cheque y cuenta corriente, que no usa. La decisión
    de producto no se pierde al normalizar el vocabulario."""
    assert "cheque" not in caja.MEDIOS_PAGO
    assert "cuenta_corriente" not in caja.MEDIOS_PAGO
    assert set(caja.MEDIOS_PAGO) < set(medios_pago.ELEGIBLES)


def test_un_medio_inventado_reventaria_al_importar():
    """La validación corre **al cargar el módulo**, no al cobrar: un medio
    inventado tumba el arranque en vez de llegar a la caja y aparecer en el
    cierre como un bucket con la clave cruda."""
    with pytest.raises(medios_pago.MedioDePagoInvalido):
        medios_pago.validar("tarjeta")


# El test del endpoint (`GET /api/caja/medios-pago`) vive en `test_caja.py`,
# donde ya está el fixture `api` con su PostgreSQL y su login. Duplicar acá esa
# maquinaria para una sola aserción sería una segunda forma de levantar la app.


def test_el_enum_muerto_no_vuelve():
    """🔴 `models.MedioPago` era un **tercer** vocabulario en el mismo repo, sin
    un solo import. Se sacó porque un enum público con claves propias es una
    invitación a que el próximo cobro lo use — y ahí sí habría datos que
    migrar."""
    import app.models as modelos

    assert not hasattr(modelos, "MedioPago")
