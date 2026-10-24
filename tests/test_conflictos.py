"""Las reservas en conflicto: listarlas y resolverlas por la API (ADR-022).

El conflicto se arma como lo deja el aplicador del central (una reserva `en_conflicto` con la que le ganó y el estado
al que vuelve), sin pasar por él: el aplicador tiene sus tests en `test_reservas_aplicador_central.py` y necesita
`libraedge`; los endpoints, no. Se recorren por HTTP: lo que ve el mostrador y lo que puede hacer. Resolver es sólo del
central.
"""

# Los fixtures (`nodo`, `central`, `api_staff`) se importan de otro módulo y se piden por nombre en cada test: ruff
# lo lee como «redefinición de un import sin usar» (F811). La suite pone un `noqa` por test; acá, uno por archivo.
# ruff: noqa: F811

from __future__ import annotations

from datetime import datetime, time

import pytest
from sqlalchemy import text

from app.models.enums import EstadoReserva
from app.models.reservas import Reserva
from app.servicios import reservas as servicio
from tests.reservas_nodo_apoyo import a_las, nodo  # noqa: F401  (fixture)
from tests.test_api import api, api_staff  # noqa: F401  (fixtures)

URL = "/api/reservas-en-conflicto"


def _en_conflicto(sesion, cancha, cliente, ganadora, *, estado_previo: str = "confirmada") -> int:
    """Una reserva `en_conflicto` como la deja el central: el mismo horario que `ganadora`, contra ella."""
    return sesion.execute(
        text(
            "INSERT INTO reservas (cancha_id, cliente_id, estado, estado_previo, conflicto_con_id, origen, "
            "comienza_at, termina_at, precio, motivo) "
            "VALUES (:cancha, :cliente, 'en_conflicto', CAST(:previo AS estado_reserva), :ganadora, 'mostrador', "
            ":desde, :hasta, 10000, 'Chocó con otra reserva que llegó antes al central.') RETURNING id"
        ),
        {
            "cancha": cancha.id, "cliente": cliente.id, "previo": estado_previo, "ganadora": ganadora.id,
            "desde": ganadora.comienza_at, "hasta": ganadora.termina_at,
        },
    ).scalar_one()


@pytest.fixture
def conflicto(sesion, cancha, cliente, tarifa_base):
    """Una reserva de la web a las 20:00 y otra del club, a la misma hora, que quedó en conflicto."""
    ganadora = servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    perdedora_id = _en_conflicto(sesion, cancha, cliente, ganadora)
    sesion.commit()
    return ganadora, perdedora_id


def test_sin_conflictos_la_lista_esta_vacia(api_staff, sesion):
    respuesta = api_staff.get(URL)
    assert respuesta.status_code == 200 and respuesta.json() == []


def test_la_lista_dice_cual_es_el_conflicto_y_quien_gano(api_staff, sesion, conflicto, cancha, cliente):
    ganadora, perdedora_id = conflicto
    respuesta = api_staff.get(URL)
    assert respuesta.status_code == 200, respuesta.text
    (item,) = respuesta.json()

    assert item["reserva"]["id"] == perdedora_id
    assert item["reserva"]["estado"] == "en_conflicto"
    assert item["reserva"]["conflicto_con_id"] == ganadora.id
    assert item["reserva"]["estado_previo"] == "confirmada"
    assert item["cancha_nombre"] == cancha.nombre and item["cliente_nombre"] == cliente.nombre
    assert item["ganadora"]["id"] == ganadora.id
    assert item["ganadora"]["estado"] == "confirmada"
    assert item["se_puede_resolver"] is True


def test_una_reserva_en_conflicto_no_aparece_en_la_grilla(api_staff, sesion, conflicto):
    """No ocupa la cancha: el listado de ocupadas (la agenda) sólo muestra la que ganó."""
    ganadora, _ = conflicto
    ocupadas = api_staff.get("/api/reservas").json()
    assert [r["id"] for r in ocupadas] == [ganadora.id]
    todas = api_staff.get("/api/reservas", params={"solo_ocupadas": "false"}).json()
    assert {r["estado"] for r in todas} == {"confirmada", "en_conflicto"}


def test_el_catalogo_de_estados_dice_que_en_conflicto_no_ocupa(api_staff, sesion):
    catalogo = api_staff.get("/api/reservas/estados/catalogo").json()
    assert "en_conflicto" in catalogo["todos"] and "en_conflicto" not in catalogo["ocupan"]


def test_hace_falta_sesion(api, sesion):
    api.cookies.clear()
    assert api.get(URL).status_code in (401, 403)


# ── Mover ────────────────────────────────────────────────────────────────────


def test_mover_a_un_horario_libre_la_confirma(api_staff, sesion, conflicto):
    _, perdedora_id = conflicto
    respuesta = api_staff.post(
        f"{URL}/{perdedora_id}/resolver", json={"accion": "mover", "comienza_at": a_las(22).isoformat()}
    )
    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    assert datos["estado"] == "confirmada"
    assert datetime.fromisoformat(datos["comienza_at"]) == a_las(22)
    assert datos["conflicto_con_id"] is None and datos["estado_previo"] is None
    # La duración se conserva, y el precio que se le dijo al cliente también.
    assert datos["precio"] == "10000.00"
    assert api_staff.get(URL).json() == []


def test_mover_conserva_el_estado_con_que_se_dio(api_staff, sesion, cancha, cliente, tarifa_base):
    ganadora = servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    perdedora_id = _en_conflicto(sesion, cancha, cliente, ganadora, estado_previo="pendiente_pago")
    sesion.commit()

    respuesta = api_staff.post(
        f"{URL}/{perdedora_id}/resolver", json={"accion": "mover", "comienza_at": a_las(22).isoformat()}
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"] == "pendiente_pago"


def test_mover_a_otra_cancha(api_staff, sesion, conflicto, sucursal):
    from app.models.enums import Deporte
    from app.models.maestros import Cancha

    otra = Cancha(sucursal_id=sucursal.id, nombre="Cancha 2", deporte=Deporte.PADEL, duracion_turno_min=90)
    sesion.add(otra)
    sesion.commit()
    _, perdedora_id = conflicto

    respuesta = api_staff.post(f"{URL}/{perdedora_id}/resolver", json={"accion": "mover", "cancha_id": otra.id})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["cancha_id"] == otra.id and respuesta.json()["estado"] == "confirmada"


def test_mover_a_un_horario_ocupado_da_409_y_sigue_en_conflicto(api_staff, sesion, conflicto):
    ganadora, perdedora_id = conflicto
    respuesta = api_staff.post(
        f"{URL}/{perdedora_id}/resolver", json={"accion": "mover", "comienza_at": a_las(21).isoformat()}
    )
    assert respuesta.status_code == 409, respuesta.text
    assert "20:00" in respuesta.json()["detail"]
    assert sesion.get(Reserva, perdedora_id).estado is EstadoReserva.EN_CONFLICTO
    assert len(api_staff.get(URL).json()) == 1


def test_sin_datos_se_intenta_el_horario_original_y_sirve_si_la_ganadora_se_cancelo(api_staff, sesion, conflicto):
    ganadora, perdedora_id = conflicto
    todavia = api_staff.post(f"{URL}/{perdedora_id}/resolver", json={"accion": "mover"})
    assert todavia.status_code == 409, "la ganadora sigue ahí"

    api_staff.post(f"/api/reservas/{ganadora.id}/estado", json={"estado": "cancelada"})
    ahora = api_staff.post(f"{URL}/{perdedora_id}/resolver", json={"accion": "mover"})
    assert ahora.status_code == 200, ahora.text
    assert ahora.json()["estado"] == "confirmada"
    assert datetime.fromisoformat(ahora.json()["comienza_at"]) == a_las(20)


def test_mover_fuera_del_horario_de_atencion_da_422(api_staff, sesion, conflicto, cancha):
    """Las mismas reglas que una reserva nueva: si la cancha no atiende a esa hora, no entra."""
    from app.models.enums import AlcanceDia
    from app.models.maestros import FranjaDeAtencion

    sesion.add(
        FranjaDeAtencion(
            sucursal_id=cancha.sucursal_id, alcance_dia=AlcanceDia.TODOS, abre=time(9), cierra=time(23, 59)
        )
    )
    sesion.commit()
    _, perdedora_id = conflicto
    respuesta = api_staff.post(
        f"{URL}/{perdedora_id}/resolver", json={"accion": "mover", "comienza_at": a_las(4).isoformat()}
    )
    assert respuesta.status_code == 422, respuesta.text


# ── Cancelar ─────────────────────────────────────────────────────────────────


def test_cancelar_resuelve_el_conflicto(api_staff, sesion, conflicto):
    ganadora, perdedora_id = conflicto
    respuesta = api_staff.post(
        f"{URL}/{perdedora_id}/resolver", json={"accion": "cancelar", "motivo": "El cliente prefiere otro día"}
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"] == "cancelada"
    # Lo que escribió quien cancela se conserva, con el prefijo que audita por qué la seña vuelve entera.
    assert respuesta.json()["motivo"] == "Conflicto de reserva del nodo: El cliente prefiere otro día"
    assert respuesta.json()["conflicto_con_id"] is None
    assert api_staff.get(URL).json() == []
    assert sesion.get(Reserva, ganadora.id).estado is EstadoReserva.CONFIRMADA, "la ganadora no se toca"


def test_cancelar_sin_motivo_deja_uno(api_staff, sesion, conflicto):
    _, perdedora_id = conflicto
    respuesta = api_staff.post(f"{URL}/{perdedora_id}/resolver", json={"accion": "cancelar"})
    assert respuesta.status_code == 200, respuesta.text
    assert "conflicto" in respuesta.json()["motivo"]


def test_tambien_se_cancela_con_el_boton_de_siempre(api_staff, sesion, conflicto):
    """`POST /api/reservas/{id}/estado` a `cancelada` sale de un conflicto; a `confirmada` no (eso es mover)."""
    _, perdedora_id = conflicto
    a_confirmada = api_staff.post(f"/api/reservas/{perdedora_id}/estado", json={"estado": "confirmada"})
    assert a_confirmada.status_code == 409, a_confirmada.text
    a_cancelada = api_staff.post(f"/api/reservas/{perdedora_id}/estado", json={"estado": "cancelada"})
    assert a_cancelada.status_code == 200, a_cancelada.text
    assert api_staff.get(URL).json() == []


def test_nadie_pasa_una_reserva_a_en_conflicto_a_mano(api_staff, sesion, cancha, cliente, tarifa_base):
    """Sólo lo pone el aplicador del central: desde la agenda no hay transición hacia ese estado."""
    reserva = servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    sesion.commit()
    respuesta = api_staff.post(f"/api/reservas/{reserva.id}/estado", json={"estado": "en_conflicto"})
    assert respuesta.status_code == 409, respuesta.text


# ── Lo que no es un conflicto ────────────────────────────────────────────────


def test_resolver_algo_que_no_esta_en_conflicto_da_409(api_staff, sesion, cancha, cliente, tarifa_base):
    reserva = servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    sesion.commit()
    for accion in ("mover", "cancelar"):
        respuesta = api_staff.post(f"{URL}/{reserva.id}/resolver", json={"accion": accion})
        assert respuesta.status_code == 409, respuesta.text
        assert "no está en conflicto" in respuesta.json()["detail"]
    assert sesion.get(Reserva, reserva.id).estado is EstadoReserva.CONFIRMADA


def test_resolver_una_que_no_existe_da_400(api_staff, sesion):
    respuesta = api_staff.post(f"{URL}/99999/resolver", json={"accion": "cancelar"})
    assert respuesta.status_code == 400, respuesta.text


def test_una_accion_desconocida_da_422(api_staff, sesion, conflicto):
    _, perdedora_id = conflicto
    assert api_staff.post(f"{URL}/{perdedora_id}/resolver", json={"accion": "borrar"}).status_code == 422


# ── En un nodo ───────────────────────────────────────────────────────────────


def test_el_nodo_ve_el_conflicto_pero_no_lo_resuelve(api_staff, sesion, conflicto, nodo):
    """El conflicto baja por el espejo y se lista; resolverlo es del central (409 `solo_en_el_central`)."""
    ganadora, perdedora_id = conflicto
    (item,) = api_staff.get(URL).json()
    assert item["reserva"]["id"] == perdedora_id and item["se_puede_resolver"] is False

    for cuerpo in ({"accion": "cancelar"}, {"accion": "mover", "comienza_at": a_las(22).isoformat()}):
        respuesta = api_staff.post(f"{URL}/{perdedora_id}/resolver", json=cuerpo)
        assert respuesta.status_code == 409, respuesta.text
        assert respuesta.json()["detail"]["codigo"] == "solo_en_el_central"
    assert sesion.get(Reserva, perdedora_id).estado is EstadoReserva.EN_CONFLICTO
