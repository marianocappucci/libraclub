"""La fecha de negocio sale del reloj de Argentina del motor, no del proceso.

`libracore.fechas.hoy()` (ADR-070) es la fuente única, y `app.tiempo.hoy()/ahora()`
delegan en ella. La factura de una reserva y el movimiento de caja de su cobro
tienen que llevar el día de Argentina aunque el proceso corra en UTC —como los
contenedores que no tienen `TZ`— y sea de noche allá.

🔴 Con `date.today()` el día salía de la `TZ` del proceso: entre las 21:00 y la
medianoche de Argentina la factura y el cobro quedaban fechados **mañana**, del
lado equivocado del arqueo. Estos tests vuelven el proceso a UTC y pisan el
instante del motor (`_ahora_utc`).
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import pytest
from libracore import fechas
from libracore.db import caja as db_caja
from libracore.db import facturas as db_facturas

from app import tiempo

# 🔑 Fixtures declaradas en ese archivo y no en el conftest: importarlas es como
# las comparte el resto de la suite (ver `test_la_factura_declara_su_ambiente.py`).
from tests.test_cobro_del_turno import (  # noqa: F401  (fixtures)
    _reserva,
    api,
)

#: 02:30 UTC del 1 de abril de 2031 = 23:30 del 31 de marzo en Argentina. Una fecha
#: lejana a propósito: así `date.today()` nunca puede coincidir con la esperada.
INSTANTE = datetime(2031, 4, 1, 2, 30, tzinfo=UTC)
DIA_EN_ARGENTINA = "2031-03-31"


@pytest.fixture
def _proceso_en_utc_a_las_23_30_de_argentina(monkeypatch):
    """El proceso en UTC y el reloj del motor clavado en `INSTANTE`."""
    antes = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    monkeypatch.setattr(fechas, "_ahora_utc", lambda: INSTANTE)
    try:
        yield
    finally:
        if antes is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = antes
        time.tzset()


def test_el_tiempo_del_producto_es_el_del_motor(_proceso_en_utc_a_las_23_30_de_argentina):
    assert tiempo.hoy().isoformat() == DIA_EN_ARGENTINA
    assert tiempo.ahora() == INSTANTE
    assert tiempo.ahora().utcoffset() == timedelta(hours=-3)


def test_la_factura_y_el_cobro_llevan_el_dia_de_argentina(
    api, cancha, cliente, tarifa_base, abrir_caja, sucursal,  # noqa: F811
    _proceso_en_utc_a_las_23_30_de_argentina,
):
    reserva = _reserva(api, cancha, cliente)
    abrir_caja(api, sucursal)
    cobro = api.post(
        f"/api/reservas/{reserva['id']}/cobros",
        json={"monto": "5000", "medio_pago": "efectivo"},
    )
    assert cobro.status_code == 201, cobro.text
    emitida = api.post(f"/api/reservas/{reserva['id']}/facturar")
    assert emitida.status_code == 201, emitida.text

    factura = db_facturas.get_factura(emitida.json()["id"])
    assert factura["fecha"] == DIA_EN_ARGENTINA
    assert [m["fecha"] for m in db_caja.get_caja_movimientos(limit=500)] == [DIA_EN_ARGENTINA]
