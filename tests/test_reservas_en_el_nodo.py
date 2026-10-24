"""Dar reservas en el club sin conexión, y lo que el nodo no deja hacer (ADR-022).

Se simula un nodo con `reservas_nodo.configurar(...)` y las tablas de LibraEdge sobre la base de la suite. Lo que se
mide: el id provisorio, la operación encolada en la misma transacción, que el nodo se vea el espejo, las guardas 409 y
que **fuera de un nodo no cambie nada**.
"""

# Los fixtures (`nodo`, `central`, `api_staff`) se importan de otro módulo y se piden por nombre en cada test: ruff
# lo lee como «redefinición de un import sin usar» (F811). La suite pone un `noqa` por test; acá, uno por archivo.
# ruff: noqa: F811

from __future__ import annotations

import pytest
from libracommerce.erp.offline import NodoLocal, Outbox
from libracore.nodo_offline import SinConexion, SoloEnElCentral
from sqlalchemy import text

from app.models.enums import EstadoReserva, OrigenReserva
from app.models.reservas import Reserva
from app.servicios import reservas as servicio
from app.servicios import reservas_nodo
from tests.reservas_nodo_apoyo import NODO, a_las, nodo, preparar_tablas_de_libraedge  # noqa: F401  (fixture)
from tests.test_api import _config, api, api_staff  # noqa: F401  (fixtures)

# ── Fuera de un nodo, nada cambia ────────────────────────────────────────────


def test_fuera_de_un_nodo_la_reserva_nace_con_el_id_de_la_base(sesion, cancha, cliente, tarifa_base):
    """Sin `configurar()` (el central, una instalación común, la web) el servicio es el de siempre."""
    assert reservas_nodo.configuracion() is None
    reserva = servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    sesion.commit()
    assert reserva.id > 0
    assert servicio.crear_bloqueo(
        sesion, cancha_id=cancha.id, comienza_at=a_las(10), termina_at=a_las(11), motivo="Lluvia"
    ).id > 0


def test_configurada_pero_sin_nodo_tampoco_cambia_nada(sesion, cancha, cliente, tarifa_base):
    """El central arma la misma configuración (`nodo()` devuelve `None`): no pide ids ni encola."""
    llamadas = []
    reservas_nodo.configurar(
        reservas_nodo.ReservasEnNodo(
            nodo=lambda: None,
            id_provisorio=lambda conn: llamadas.append("id") or -1,
            al_crear_reserva=lambda conn, datos: llamadas.append("creada"),
            al_cambiar_estado=lambda conn, datos: llamadas.append("estado"),
        )
    )
    try:
        reserva = servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
        servicio.cambiar_estado(sesion, reserva.id, EstadoReserva.CANCELADA)
        servicio.crear_bloqueo(sesion, cancha_id=cancha.id, comienza_at=a_las(10), termina_at=a_las(11), motivo="x")
    finally:
        reservas_nodo.configurar(None)
    assert reserva.id > 0
    assert llamadas == []


# ── En un nodo: el id provisorio y la operación ──────────────────────────────


def test_en_un_nodo_la_reserva_nace_con_id_negativo_y_encola_reserva_creada(sesion, cancha, cliente, tarifa_base, nodo):
    reserva = servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20), observaciones="Trae pelotas"
    )
    sesion.commit()

    assert reserva.id == -1
    assert reserva.estado is EstadoReserva.CONFIRMADA
    assert len(nodo.creadas) == 1
    datos = nodo.creadas[0]
    assert datos["version"] == 1
    assert datos["reserva_id"] == -1
    assert (datos["cancha_id"], datos["cliente_id"]) == (cancha.id, cliente.id)
    assert datos["estado"] == "confirmada" and datos["origen"] == "mostrador"
    assert datos["comienza_at"] == a_las(20).isoformat()
    assert datos["precio"] == "10000.00" and datos["sena"] == "5000.00"
    assert datos["observaciones"] == "Trae pelotas"


def test_los_ids_provisorios_no_se_repiten(sesion, cancha, cliente, tarifa_base, nodo):
    primera = servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(18))
    segunda = servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    assert (primera.id, segunda.id) == (-1, -2)


def test_en_un_nodo_no_se_da_una_reserva_provisoria_del_portal(sesion, cancha, cliente, tarifa_base, nodo):
    """`EstadoReserva.PROVISORIA` es el turno retenido esperando el pago del portal: no se da en el club."""
    with pytest.raises(servicio.ReservaInvalida):
        servicio.crear(
            sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20),
            estado=EstadoReserva.PROVISORIA, origen=OrigenReserva.PORTAL,
        )
    assert nodo.creadas == []


def test_el_nodo_ve_el_espejo_y_no_da_una_cancha_que_ya_sabe_tomada(sesion, cancha, cliente, tarifa_base, nodo):
    """Lo que el nodo ya sabe lo respeta, con el mensaje de siempre: la exclusión partida deja entrar lo que el nodo
    *no* sabe (la web la tomó después de la última sincronización), no lo que está a la vista."""
    sesion.execute(
        text(
            "INSERT INTO reservas (id, cancha_id, cliente_id, estado, origen, comienza_at, termina_at) "
            "VALUES (57, :cancha, :cliente, 'confirmada', 'portal', :desde, :hasta)"
        ),
        {"cancha": cancha.id, "cliente": cliente.id, "desde": a_las(20), "hasta": a_las(21, 30)},
    )
    sesion.commit()
    with pytest.raises(servicio.Superpuesta) as error:
        servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(21))
    assert "20:00" in str(error.value)
    assert nodo.creadas == []


def test_dos_reservas_del_nodo_en_el_mismo_horario_chocan(sesion, cancha, cliente, tarifa_base, nodo):
    servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    with pytest.raises(servicio.Superpuesta):
        servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(21))
    assert len(nodo.creadas) == 1


def test_si_el_encolado_falla_la_reserva_no_queda(sesion, cancha, cliente, tarifa_base, nodo):
    """Una reserva que se da en el nodo y no sube no es «a medias»: el central no la ve y la cancha se vende dos
    veces. El gancho corre dentro de la transacción de la reserva, así que si levanta, todo se deshace."""
    def fallar(conn, datos):
        raise RuntimeError("outbox roto")

    # La configuración es inmutable: se arma otra con el gancho roto.
    reservas_nodo.configurar(
        reservas_nodo.ReservasEnNodo(
            nodo=lambda: NODO, id_provisorio=reservas_nodo.configuracion().id_provisorio, al_crear_reserva=fallar
        )
    )
    with pytest.raises(RuntimeError):
        servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    sesion.rollback()
    assert sesion.execute(text("SELECT count(*) FROM reservas")).scalar_one() == 0


# ── Cancelar y marcar jugada ─────────────────────────────────────────────────


def test_una_reserva_del_nodo_se_cancela_en_el_nodo_y_sube_el_cambio(sesion, cancha, cliente, tarifa_base, nodo):
    reserva = servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    servicio.cambiar_estado(sesion, reserva.id, EstadoReserva.CANCELADA, motivo="No viene")
    sesion.commit()

    assert reserva.estado is EstadoReserva.CANCELADA
    assert nodo.estados == [{"version": 1, "reserva_id": -1, "estado": "cancelada", "motivo": "No viene"}]


def test_una_reserva_del_nodo_se_marca_jugada_en_el_nodo(sesion, cancha, cliente, tarifa_base, nodo):
    reserva = servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    servicio.cambiar_estado(sesion, reserva.id, EstadoReserva.JUGADA)
    assert reserva.estado is EstadoReserva.JUGADA
    assert nodo.estados[0]["estado"] == "jugada"


def _reserva_del_central(sesion, cancha, cliente) -> int:
    """Una reserva con id positivo, como la que baja del central por el espejo."""
    sesion.execute(
        text(
            "INSERT INTO reservas (id, cancha_id, cliente_id, estado, origen, comienza_at, termina_at) "
            "VALUES (57, :cancha, :cliente, 'confirmada', 'portal', :desde, :hasta)"
        ),
        {"cancha": cancha.id, "cliente": cliente.id, "desde": a_las(20), "hasta": a_las(21, 30)},
    )
    sesion.commit()
    return 57


@pytest.mark.parametrize("nuevo", [EstadoReserva.CANCELADA, EstadoReserva.JUGADA])
def test_sin_conexion_cancelar_o_marcar_jugada_una_de_la_web_da_409_sin_conexion(
    sesion, cancha, cliente, nodo, nuevo
):
    """Decisión del humano (2026-10-22): cancelar o marcar jugada una reserva de la web espera a la conexión."""
    reserva_id = _reserva_del_central(sesion, cancha, cliente)
    nodo.en_linea = False
    with pytest.raises(SinConexion) as error:
        servicio.cambiar_estado(sesion, reserva_id, nuevo)
    assert error.value.detalle()["codigo"] == "sin_conexion"
    assert sesion.get(Reserva, reserva_id).estado is EstadoReserva.CONFIRMADA
    assert nodo.estados == []


def test_con_conexion_el_nodo_tampoco_cambia_una_reserva_del_central(sesion, cancha, cliente, nodo):
    """El nodo no tiene cómo subir ese cambio y su base rechaza escribir una fila del central: se dice claro, con
    otro código (`solo_en_el_central`), y no con un 500."""
    reserva_id = _reserva_del_central(sesion, cancha, cliente)
    nodo.en_linea = True
    with pytest.raises(SoloEnElCentral) as error:
        servicio.cambiar_estado(sesion, reserva_id, EstadoReserva.CANCELADA)
    assert error.value.detalle()["codigo"] == "solo_en_el_central"


def test_un_nodo_cuyo_estado_no_se_puede_leer_se_toma_sin_conexion(sesion, cancha, cliente, nodo):
    reserva_id = _reserva_del_central(sesion, cancha, cliente)

    def estado_roto() -> bool:
        raise OSError("sin archivo de estado")

    config = reservas_nodo.configuracion()
    reservas_nodo.configurar(
        reservas_nodo.ReservasEnNodo(nodo=config.nodo, id_provisorio=config.id_provisorio, en_linea=estado_roto)
    )
    with pytest.raises(SinConexion):
        servicio.cambiar_estado(sesion, reserva_id, EstadoReserva.CANCELADA)


def test_en_un_nodo_no_se_cargan_bloqueos_ni_series(sesion, cancha, cliente, nodo):
    """Su id saldría de la secuencia del nodo y chocaría con los del central."""
    with pytest.raises(SoloEnElCentral):
        servicio.crear_bloqueo(sesion, cancha_id=cancha.id, comienza_at=a_las(10), termina_at=a_las(11), motivo="x")


# ── Por HTTP: lo que ve el mostrador ─────────────────────────────────────────


def test_por_http_cancelar_una_de_la_web_sin_conexion_contesta_409_con_codigo(
    api_staff, sesion, cancha, cliente, nodo  # noqa: F811
):
    reserva_id = _reserva_del_central(sesion, cancha, cliente)
    respuesta = api_staff.post(f"/api/reservas/{reserva_id}/estado", json={"estado": "cancelada"})
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"]["codigo"] == "sin_conexion"
    assert "conexión" in respuesta.json()["detail"]["mensaje"]


def test_por_http_marcar_jugada_una_de_la_web_sin_conexion_contesta_409(api_staff, sesion, cancha, cliente, nodo):
    reserva_id = _reserva_del_central(sesion, cancha, cliente)
    respuesta = api_staff.post(f"/api/reservas/{reserva_id}/estado", json={"estado": "jugada"})
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"]["codigo"] == "sin_conexion"


def test_por_http_se_da_y_se_cancela_una_reserva_en_el_nodo(api_staff, sesion, cancha, cliente, tarifa_base, nodo):
    creada = api_staff.post(
        "/api/reservas",
        json={"cancha_id": cancha.id, "cliente_id": cliente.id, "comienza_at": a_las(20).isoformat()},
    )
    assert creada.status_code == 201, creada.text
    assert creada.json()["id"] < 0

    cancelada = api_staff.post(f"/api/reservas/{creada.json()['id']}/estado", json={"estado": "cancelada"})
    assert cancelada.status_code == 200, cancelada.text
    assert cancelada.json()["estado"] == "cancelada"
    assert [d["estado"] for d in nodo.estados] == ["cancelada"]


def test_por_http_las_series_y_los_bloqueos_son_del_central(api_staff, sesion, cancha, cliente, nodo):
    serie = api_staff.post(
        "/api/reservas/series",
        json={"cancha_id": cancha.id, "cliente_id": cliente.id, "dia_semana": 1, "hora": "20:00:00",
              "duracion_min": 90, "desde": "2026-09-01"},
    )
    assert serie.status_code == 409, serie.text
    assert serie.json()["detail"]["codigo"] == "solo_en_el_central"

    bloqueo = api_staff.post(
        "/api/reservas/bloqueos",
        json={"cancha_id": cancha.id, "comienza_at": a_las(10).isoformat(), "termina_at": a_las(11).isoformat(),
              "motivo": "Lluvia"},
    )
    assert bloqueo.status_code == 409, bloqueo.text
    assert bloqueo.json()["detail"]["codigo"] == "solo_en_el_central"


def test_por_http_en_el_central_todo_sigue_igual(api_staff, sesion, cancha, cliente, tarifa_base):
    """La web y el portal: sin nodo, cancelar una reserva con id positivo funciona como siempre."""
    creada = api_staff.post(
        "/api/reservas",
        json={"cancha_id": cancha.id, "cliente_id": cliente.id, "comienza_at": a_las(20).isoformat()},
    )
    assert creada.status_code == 201 and creada.json()["id"] > 0
    cancelada = api_staff.post(f"/api/reservas/{creada.json()['id']}/estado", json={"estado": "cancelada"})
    assert cancelada.status_code == 200, cancelada.text


# ── Con el outbox de verdad ──────────────────────────────────────────────────


@pytest.fixture
def nodo_con_outbox(sesion):
    """El `Outbox` de libracommerce armado como lo va a armar el producto (PR 11), sin el proceso del nodo."""
    preparar_tablas_de_libraedge(sesion)
    outbox = Outbox(nodo=lambda: NodoLocal(node_id=NODO, prefijo="S01"), en_linea=lambda: False)
    reservas_nodo.configurar(reservas_nodo.desde_el_outbox(outbox))
    yield outbox
    reservas_nodo.configurar(None)


def _outbox(sesion) -> list[tuple]:
    return list(
        sesion.execute(
            text("SELECT operation_type, aggregate_id, payload_json FROM sync_outbox ORDER BY sequence")
        ).all()
    )


def test_la_operacion_entra_en_el_outbox_en_la_misma_transaccion(sesion, cancha, cliente, tarifa_base, nodo_con_outbox):
    import json

    reserva = servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    servicio.cambiar_estado(sesion, reserva.id, EstadoReserva.CANCELADA, motivo="No viene")
    sesion.commit()

    filas = _outbox(sesion)
    assert [(f[0], f[1]) for f in filas] == [
        ("reserva.creada", f"{NODO}:reserva:-1"),
        ("reserva.estado", f"{NODO}:reserva:-1"),
    ]
    creada, estado = (json.loads(f[2]) for f in filas)
    assert creada["reserva_id"] == -1 and creada["estado"] == "confirmada"
    assert estado == {"version": 1, "reserva_id": -1, "estado": "cancelada", "motivo": "No viene"}


def test_si_la_reserva_se_deshace_la_operacion_tambien(sesion, cancha, cliente, tarifa_base, nodo_con_outbox):
    """La reserva y su operación viven o mueren juntas: es lo que justifica `conexion_de_la_sesion`."""
    servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    assert len(_outbox(sesion)) == 1
    sesion.rollback()
    assert _outbox(sesion) == []
    assert sesion.execute(text("SELECT count(*) FROM reservas")).scalar_one() == 0


def test_fuera_de_un_nodo_el_outbox_no_se_toca(sesion, cancha, cliente, tarifa_base):
    """El mismo `desde_el_outbox` armado en el central (`nodo()` devuelve `None`): ni id provisorio ni operación, y no
    hace falta que libraedge esté instalado."""
    reservas_nodo.configurar(reservas_nodo.desde_el_outbox(Outbox(nodo=lambda: None)))
    try:
        reserva = servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
        servicio.cambiar_estado(sesion, reserva.id, EstadoReserva.CANCELADA)
        sesion.commit()
    finally:
        reservas_nodo.configurar(None)
    assert reserva.id > 0
