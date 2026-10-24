"""Cancelar una reserva `en_conflicto` devuelve SIEMPRE la seña entera (ADR-022, addendum del 2026-10-24).

El conflicto no es culpa del jugador: la cancha la tenía otra reserva que llegó antes al central. Por eso la
devolución **no mira la política de la sucursal** (la ventana de horas), y sale por el camino de siempre:
MercadoPago si la seña se pagó por el portal, la caja si se cobró en el mostrador. Queda auditada con el motivo
`Conflicto de reserva del nodo`.

Cada test trae su **control**: la misma reserva fuera de un conflicto, con la misma política, no devuelve nada. Sin
el control un test verde podría estar midiendo una política que devuelve de todos modos.

El conflicto se arma como lo deja el aplicador del central (una reserva `en_conflicto`), sin pasar por él: el
aplicador tiene sus tests en `test_reservas_aplicador_central.py` y necesita `libraedge`; esto, no.
"""

# Los fixtures se importan de otros módulos y se piden por nombre: ruff lo lee como «redefinición de un import sin
# usar» (F811). La suite pone un `noqa` por test; acá, uno por archivo.
# ruff: noqa: F811

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row
from sqlalchemy import text

from app.models.enums import EstadoReserva
from app.models.reservas import CanalDePago, EstadoPago, Reserva
from app.servicios import cancelacion, conflictos
from tests.test_cancelacion import (  # noqa: F401  (fixtures)
    PasarelaFalsa,
    _reserva_pagada,
    abierto,
    con_politica,
    vendible,
)
from tests.test_devolucion_por_caja import (  # noqa: F401  (fixtures)
    _cobrada_por_qr,
    _recargado,
    api,
    complejo,
)


def _en_conflicto(sesion, reserva: Reserva) -> None:
    """Deja la reserva como la deja el central cuando le gana otra: `en_conflicto`, sin ocupar la cancha."""
    sesion.execute(
        text(
            "UPDATE reservas SET estado = 'en_conflicto', estado_previo = 'confirmada', "
            "motivo = 'Chocó con otra reserva que llegó antes al central.' WHERE id = :id"
        ),
        {"id": reserva.id},
    )
    sesion.commit()
    sesion.expire_all()


# ── MercadoPago: el pago del portal ──────────────────────────────────────────


def test_cancelar_un_conflicto_devuelve_la_sena_entera_aunque_la_politica_diga_que_no(
    sesion, cancha, cliente, vendible, con_politica
):
    """A 3 horas del turno y con política de 24: una reserva común pierde la seña. Una en conflicto, no."""
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=3)
    _en_conflicto(sesion, reserva)
    pasarela = PasarelaFalsa()

    resultado = conflictos.cancelar(sesion, reserva.id, motivo=None, pasarela=pasarela)
    sesion.commit()

    assert resultado.politica.hay_politica and not resultado.politica.a_tiempo, "el control: la política dice que no"
    assert resultado.reserva.estado is EstadoReserva.CANCELADA
    assert resultado.devolucion is EstadoPago.DEVUELTO
    assert pago.estado is EstadoPago.DEVUELTO
    assert pago.refund_id == "refund-mp-123" and pago.devuelto_at is not None
    assert len(pasarela.llamadas) == 1, "se le pidió a MercadoPago, por el payment_id del pago"
    assert pasarela.llamadas[0][0] == "mp-123"
    assert float(pago.monto) == 5000.0, "la seña entera"


def test_el_control_la_misma_reserva_sin_conflicto_no_devuelve_nada(
    sesion, cancha, cliente, vendible, con_politica
):
    """Sin esto el test de arriba podría pasar con una política que devuelve de todos modos."""
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=3)
    pasarela = PasarelaFalsa()

    resultado = cancelacion.cancelar(sesion, reserva.id, motivo="Llueve", pasarela=pasarela)
    sesion.commit()

    assert resultado.devolucion is None
    assert pago.estado is EstadoPago.APROBADO
    assert pasarela.llamadas == []


def test_un_conflicto_devuelve_tambien_sin_politica_cargada(sesion, cancha, cliente, vendible):
    """La sucursal que no cargó política no devuelve nada (el default es el de antes); un conflicto, sí."""
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=48)
    _en_conflicto(sesion, reserva)
    pasarela = PasarelaFalsa()

    resultado = conflictos.cancelar(sesion, reserva.id, motivo=None, pasarela=pasarela)
    sesion.commit()

    assert resultado.politica.hay_politica is False
    assert pago.estado is EstadoPago.DEVUELTO
    assert len(pasarela.llamadas) == 1


def test_queda_auditado_con_el_motivo_del_conflicto(sesion, cancha, cliente, vendible, con_politica):
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=3)
    _en_conflicto(sesion, reserva)

    resultado = conflictos.cancelar(sesion, reserva.id, motivo=None, pasarela=PasarelaFalsa())
    sesion.commit()

    assert reserva.motivo.startswith(cancelacion.MOTIVO_CONFLICTO_DEL_NODO)
    assert cancelacion.MOTIVO_CONFLICTO_DEL_NODO == "Conflicto de reserva del nodo"
    assert cancelacion.es_de_conflicto(reserva)
    # El texto para el mostrador dice por qué se devolvió sin mirar la política.
    assert "Conflicto de reserva del nodo" in resultado.detalle
    assert "sin mirar la política" in resultado.detalle
    # Lo que escribió quien cancela no se pierde.
    otra, _ = _reserva_pagada(sesion, cancha, cliente, en_horas=3)
    _en_conflicto(sesion, otra)
    conflictos.cancelar(sesion, otra.id, motivo="Llamé al cliente", pasarela=PasarelaFalsa())
    sesion.commit()
    assert otra.motivo == "Conflicto de reserva del nodo: Llamé al cliente"


def test_el_motivo_no_pasa_de_los_200_caracteres_de_la_columna(sesion, cancha, cliente, vendible, con_politica):
    reserva, _ = _reserva_pagada(sesion, cancha, cliente, en_horas=3)
    _en_conflicto(sesion, reserva)

    conflictos.cancelar(sesion, reserva.id, motivo="x" * 200, pasarela=PasarelaFalsa())
    sesion.commit()

    assert len(reserva.motivo) == 200 and cancelacion.es_de_conflicto(reserva)


def test_si_mercadopago_rechaza_la_devolucion_queda_pendiente_y_se_cancela_igual(
    sesion, cancha, cliente, vendible, con_politica
):
    """Mismo contrato de siempre: la cancelación no se cae porque falle la devolución."""
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=3)
    _en_conflicto(sesion, reserva)

    resultado = conflictos.cancelar(sesion, reserva.id, motivo=None, pasarela=PasarelaFalsa(falla="no se puede"))
    sesion.commit()

    assert resultado.reserva.estado is EstadoReserva.CANCELADA
    assert pago.estado is EstadoPago.DEVOLUCION_PENDIENTE
    assert pago.detalle_devolucion == "no se puede"
    assert cancelacion.pendientes(sesion) == [pago]


def test_cancelar_una_reserva_que_no_esta_en_conflicto_no_toca_la_regla(
    sesion, cancha, cliente, vendible, con_politica
):
    """`cancelacion.cancelar` sobre una confirmada sigue por la ventana: la regla nueva es sólo del conflicto."""
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=48)

    resultado = cancelacion.cancelar(sesion, reserva.id, motivo="Se lesionó", pasarela=PasarelaFalsa())
    sesion.commit()

    assert resultado.devolucion is EstadoPago.DEVUELTO
    assert reserva.motivo == "Se lesionó", "sin el prefijo del conflicto"
    assert not cancelacion.es_de_conflicto(reserva)


# ── La caja: el cobro del mostrador ──────────────────────────────────────────


def _egresos(url_core: str) -> list[dict]:
    with psycopg.connect(url_core) as c:
        c.row_factory = dict_row
        return c.execute(
            "SELECT id, tipo, monto, concepto, referencia, medio_pago, turno_id FROM caja_movimientos "
            "WHERE tipo = 'egreso' ORDER BY id"
        ).fetchall()


def test_cancelar_un_conflicto_devuelve_en_efectivo_por_la_caja_aunque_la_politica_diga_que_no(
    api, sesion, cancha, cliente, complejo, abrir_caja, base_de_libracore
):
    """A 3 horas del turno y con política de 24 (`complejo`): la seña cobrada en el mostrador sale de la caja igual."""
    abrir_caja(api, complejo)
    pago = _cobrada_por_qr(api, sesion, cancha, cliente, en_horas=3)
    _en_conflicto(sesion, sesion.get(Reserva, pago.reserva_id))
    turno_id = api.get("/api/caja/turnos/actual").json()["turno"]["id"]

    r = api.post(f"/api/reservas-en-conflicto/{pago.reserva_id}/resolver", json={"accion": "cancelar"})

    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "cancelada"
    guardado = _recargado(sesion, pago)
    assert guardado.estado is EstadoPago.DEVUELTO and guardado.devuelto_at is not None
    (egreso,) = _egresos(base_de_libracore)
    assert egreso["referencia"] == f"devolucion-{pago.referencia}"
    assert float(egreso["monto"]) == float(pago.monto), "la seña entera"
    assert egreso["medio_pago"] == "efectivo" and egreso["turno_id"] == turno_id
    # Auditado en la caja: el concepto del egreso dice por qué salió esa plata.
    assert "Conflicto de reserva del nodo" in egreso["concepto"]
    assert sesion.get(Reserva, pago.reserva_id).motivo.startswith("Conflicto de reserva del nodo")


def test_el_control_de_la_caja_sin_conflicto_y_tarde_no_saca_nada(
    api, sesion, cancha, cliente, complejo, abrir_caja, base_de_libracore
):
    abrir_caja(api, complejo)
    pago = _cobrada_por_qr(api, sesion, cancha, cliente, en_horas=3)

    r = api.post(f"/api/reservas/{pago.reserva_id}/estado", json={"estado": "cancelada", "motivo": "No viene"})

    assert r.status_code == 200, r.text
    assert _recargado(sesion, pago).estado is EstadoPago.APROBADO
    assert _egresos(base_de_libracore) == []


def test_cancelar_un_conflicto_desde_la_agenda_tambien_devuelve_entera(
    api, sesion, cancha, cliente, complejo, abrir_caja, base_de_libracore
):
    """`POST /api/reservas/{id}/estado` a `cancelada` también sirve para un conflicto: misma regla, un solo lugar."""
    abrir_caja(api, complejo)
    pago = _cobrada_por_qr(api, sesion, cancha, cliente, en_horas=3)
    _en_conflicto(sesion, sesion.get(Reserva, pago.reserva_id))

    r = api.post(f"/api/reservas/{pago.reserva_id}/estado", json={"estado": "cancelada"})

    assert r.status_code == 200, r.text
    assert _recargado(sesion, pago).estado is EstadoPago.DEVUELTO
    assert len(_egresos(base_de_libracore)) == 1


def test_sin_caja_abierta_el_conflicto_queda_pendiente_y_el_reintento_lo_completa_con_el_motivo(
    api, sesion, cancha, cliente, complejo, abrir_caja, base_de_libracore
):
    """Sin turno de caja no hay de dónde sacarla: queda anotada. El reintento corre con la reserva ya `cancelada`
    (ya no está en conflicto) y el egreso lleva igual el motivo, que sale del motivo de la reserva."""
    abrir_caja(api, complejo)
    pago = _cobrada_por_qr(api, sesion, cancha, cliente, en_horas=3)
    _en_conflicto(sesion, sesion.get(Reserva, pago.reserva_id))
    turno_id = api.get("/api/caja/turnos/actual").json()["turno"]["id"]
    assert api.post(f"/api/caja/turnos/{turno_id}/cerrar", json={"monto_declarado": "0"}).status_code == 200

    r = api.post(f"/api/reservas-en-conflicto/{pago.reserva_id}/resolver", json={"accion": "cancelar"})
    assert r.status_code == 200, r.text
    assert _recargado(sesion, pago).estado is EstadoPago.DEVOLUCION_PENDIENTE
    assert _egresos(base_de_libracore) == []

    abrir_caja(api, complejo)
    reintento = api.post(f"/api/devoluciones/{pago.id}/reintentar")
    assert reintento.status_code == 200, reintento.text
    assert _recargado(sesion, pago).estado is EstadoPago.DEVUELTO
    (egreso,) = _egresos(base_de_libracore)
    assert "Conflicto de reserva del nodo" in egreso["concepto"]


def test_las_reservas_de_mostrador_y_de_portal_se_distinguen_por_el_canal_del_pago(
    sesion, cancha, cliente, vendible, con_politica
):
    """Por donde entró vuelve: un cobro de mostrador cancelado desde un camino sin caja (`usuario=None`) no se manda a
    MercadoPago aunque sea un conflicto; queda pendiente."""
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=3, canal=CanalDePago.MOSTRADOR)
    pago.caja_movimiento_id = 999
    sesion.commit()
    _en_conflicto(sesion, reserva)
    pasarela = PasarelaFalsa()

    cancelacion.cancelar(sesion, reserva.id, motivo="X", pasarela=pasarela, usuario=None)
    sesion.commit()

    assert pasarela.llamadas == [], "ni se le pidió a MercadoPago"
    assert pago.estado is EstadoPago.DEVOLUCION_PENDIENTE
    assert pago.detalle_devolucion == cancelacion.SIN_CAJA_ABIERTA


def test_mover_un_conflicto_no_toca_la_plata(sesion, cancha, cliente, vendible, con_politica):
    """Sólo cancelar devuelve. Mover conserva la seña que se le dijo al cliente: ni la devuelve ni la cobra otra vez."""
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=48)
    _en_conflicto(sesion, reserva)

    conflictos.mover(sesion, reserva.id)
    sesion.commit()

    assert reserva.estado is EstadoReserva.CONFIRMADA
    assert pago.estado is EstadoPago.APROBADO and pago.refund_id is None
