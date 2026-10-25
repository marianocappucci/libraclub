"""Los clientes dados de alta en el nodo, con el armado real de la app (ADR-022, addendum; cableado sobre el PR 11).

`tests/test_clientes_en_el_nodo.py` y `tests/test_clientes_aplicador_central.py` miden las piezas con un nodo simulado;
acá corre lo que cablea `app/offline.py`, `app/main.py` y `app/routers/sincronizacion_offline.py`: el alta por HTTP en
un nodo (que antes era 409 por ser `clientes` de sólo lectura), la operación en el outbox real y el receptor real del
central.
"""

# Los fixtures se importan de otros módulos y se piden por nombre en cada test: ruff lo lee como «redefinición de un
# import sin usar» (F811). La suite pone un `noqa` por test; acá, uno por archivo.
# ruff: noqa: F811

from __future__ import annotations

import pytest
from libraauth.models import Base as AuthBase
from libracore.db import core as libracore_core

from app import offline
from tests.nodo_apoyo import (
    aplicar_en_el_central,
    armar_app,
    cliente_logueado,
    filas,
    nodo,  # noqa: F401  (fixture)
    nodo_apagado,  # noqa: F401  (fixture)
    operaciones,
    tipos_encolados,
    vaciar_lo_del_nodo,
)
from tests.reservas_nodo_apoyo import a_las


@pytest.fixture
def staff(engine, sesion, monkeypatch, base_de_libracore):
    app = armar_app(engine, monkeypatch, base_de_libracore, con_staff=True)
    yield cliente_logueado(app, "encargado")
    AuthBase.metadata.drop_all(engine)


def test_el_central_registra_el_alta_de_clientes_sin_pisar_la_de_libracommerce():
    from app.routers.sincronizacion_offline import despachador

    assert {"cliente_club.alta", "cliente_club.edicion", "cliente.alta", "reserva.creada", "reserva.estado"} <= set(
        despachador.tipos()
    )
    assert despachador.versiones("cliente_club.alta") == (1,)
    assert despachador.versiones("cliente_club.edicion") == (1,)


def test_clientes_se_espeja_y_se_escribe_en_el_nodo_pero_no_es_de_solo_lectura():
    assert "clientes" in offline.TABLAS_DE_REFERENCIA
    assert "clientes" not in offline.TABLAS_SOLO_LECTURA
    assert [a.tabla for a in offline.aprovisionamiento.altas] == ["clientes", "reservas"]


def test_en_un_nodo_el_alta_de_un_cliente_se_acepta_con_id_provisorio_y_sube(staff, nodo):
    r = staff.post("/api/clientes", json={"nombre": "Juan Pérez", "documento": "30123456"})

    assert r.status_code == 201, r.text
    assert r.json()["id"] < 0
    assert tipos_encolados() == ["cliente_club.alta"]
    (op,) = operaciones()
    assert op.payload["cliente_id"] == r.json()["id"] and op.payload["nombre"] == "Juan Pérez"
    assert op.aggregate_id == f"club-1:cliente_club:{r.json()['id']}"


def test_en_un_nodo_editar_un_cliente_sigue_siendo_del_central(staff, nodo, sesion):
    nodo.apagar()
    id_ = staff.post("/api/clientes", json={"nombre": "Del central"}).json()["id"]
    nodo.prender()

    r = staff.put(f"/api/clientes/{id_}", json={"nombre": "Otro"})

    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "sin_conexion"


def test_en_el_central_el_alta_de_un_cliente_es_la_de_siempre(staff, nodo_apagado):
    r = staff.post("/api/clientes", json={"nombre": "Alguien"})
    assert r.status_code == 201 and r.json()["id"] > 0
    assert tipos_encolados() == []


def test_de_punta_a_punta_el_alta_y_la_reserva_suben_y_el_central_las_enlaza(
    staff, sesion, cancha, tarifa_base, nodo_apagado
):
    """Sin conexión: se da de alta a quien llama y se le toma el turno. Al llegar al central, por el receptor real y en
    el orden del outbox, el cliente tiene su id definitivo y la reserva queda a su nombre."""
    nodo_apagado.prender()
    cliente = staff.post("/api/clientes", json={"nombre": "Juan Pérez", "documento": "30123456"}).json()
    reserva = staff.post(
        "/api/reservas",
        json={"cancha_id": cancha.id, "cliente_id": cliente["id"], "comienza_at": a_las(20).isoformat()},
    )
    assert reserva.status_code == 201, reserva.text
    assert tipos_encolados() == ["cliente_club.alta", "reserva.creada"]
    capturadas = operaciones()

    vaciar_lo_del_nodo()
    nodo_apagado.apagar()
    assert aplicar_en_el_central(capturadas) == ["accepted", "accepted"]

    ((cliente_id, nombre, reserva_id),) = filas(
        "SELECT c.id, c.nombre, r.id FROM reservas r JOIN clientes c ON c.id = r.cliente_id WHERE r.id > 0"
    )
    assert cliente_id > 0 and reserva_id > 0 and nombre == "Juan Pérez"
    # Y se aplican una sola vez: el reenvío es un duplicado, no un segundo cliente.
    assert aplicar_en_el_central(capturadas) == ["duplicate", "duplicate"]
    assert filas("SELECT count(*) FROM clientes WHERE id > 0") == [(1,)]


def test_si_el_alta_se_rechaza_la_reserva_tambien_y_no_queda_a_nombre_de_nadie(
    staff, sesion, cancha, tarifa_base, nodo_apagado
):
    """Una reserva que llega sin su alta aplicada va a revisión manual (`VinculoNoSincronizado`)."""
    nodo_apagado.prender()
    cliente = staff.post("/api/clientes", json={"nombre": "Juan Pérez"}).json()
    staff.post(
        "/api/reservas",
        json={"cancha_id": cancha.id, "cliente_id": cliente["id"], "comienza_at": a_las(20).isoformat()},
    )
    _alta, reserva = operaciones()
    vaciar_lo_del_nodo()
    nodo_apagado.apagar()

    resultado = aplicar_en_el_central([reserva])

    assert resultado[0].startswith("rejected")
    assert filas("SELECT count(*) FROM reservas WHERE id > 0") == [(0,)]


# ── Editar un cliente provisorio, de punta a punta (ADR-022, segundo addendum) ─


def _dar_de_alta_y_corregir(staff, nodo_apagado, *, corregir: dict | None = None):
    """Sin conexión: alta de «Juan Pérez» y una corrección de su teléfono. Devuelve las operaciones del outbox."""
    nodo_apagado.prender()
    cliente = staff.post(
        "/api/clientes", json={"nombre": "Juan Pérez", "documento": "30123456", "telefono": "11 5555 1234"}
    ).json()
    cuerpo = {"nombre": "Juan Pérez", "documento": "30123456", "telefono": "11 5555 9999", **(corregir or {})}
    editado = staff.put(f"/api/clientes/{cliente['id']}", json=cuerpo)
    assert editado.status_code == 200, editado.text
    assert tipos_encolados() == ["cliente_club.alta", "cliente_club.edicion"]
    capturadas = operaciones()
    vaciar_lo_del_nodo()
    nodo_apagado.apagar()
    return capturadas


def test_el_alta_y_su_correccion_suben_en_orden_y_el_central_queda_con_lo_corregido(staff, sesion, nodo_apagado):
    capturadas = _dar_de_alta_y_corregir(staff, nodo_apagado)

    assert aplicar_en_el_central(capturadas) == ["accepted", "accepted"]

    assert filas("SELECT nombre, telefono, documento FROM clientes WHERE id > 0") == [
        ("Juan Pérez", "11 5555 9999", "30123456")
    ]
    # El reenvío es un duplicado: ni un segundo cliente ni una segunda edición.
    assert aplicar_en_el_central(capturadas) == ["duplicate", "duplicate"]
    assert filas("SELECT count(*) FROM clientes WHERE id > 0") == [(1,)]


def test_la_correccion_que_llega_sola_espera_al_alta_y_se_reintenta_en_orden(staff, sesion, nodo_apagado):
    """Si el alta no está aplicada, la edición queda en revisión (sin mapeo) y no escribe nada; con el alta resuelta, el
    reintento la aplica."""
    from libraedge.sync.revision import reintentar

    from app.routers.sincronizacion_offline import despachador

    alta, edicion = _dar_de_alta_y_corregir(staff, nodo_apagado)

    (resultado,) = aplicar_en_el_central([edicion])
    assert resultado.startswith("rejected") and "no esta mapeado" in resultado
    assert filas("SELECT count(*) FROM clientes WHERE id > 0") == [(0,)]

    assert aplicar_en_el_central([alta]) == ["accepted"]
    with libracore_core.get_connection() as conn:
        assert reintentar(conn, edicion.operation_id, despachador, "pruebas").result == "accepted"
        conn.commit()
    assert filas("SELECT telefono FROM clientes WHERE id > 0") == [("11 5555 9999",)]


def test_si_en_el_central_cambiaron_lo_mismo_la_correccion_va_a_revision_y_no_pisa_nada(staff, sesion, nodo_apagado):
    from libraedge.sync.revision import listar_en_revision, reintentar

    from app.routers.sincronizacion_offline import despachador

    alta, edicion = _dar_de_alta_y_corregir(staff, nodo_apagado)
    assert aplicar_en_el_central([alta]) == ["accepted"]
    # En el central alguien corrigió el mismo teléfono mientras tanto.
    with libracore_core.get_connection() as conn:
        conn.execute("UPDATE clientes SET telefono = '11 0000 0000' WHERE id > 0")
        conn.commit()

    (resultado,) = aplicar_en_el_central([edicion])

    assert resultado.startswith("rejected") and "telefono" in resultado and "11 0000 0000" in resultado
    assert filas("SELECT telefono FROM clientes WHERE id > 0") == [("11 0000 0000",)], "gana lo del central"
    with libracore_core.get_connection() as conn:
        (en_revision,) = listar_en_revision(conn, "club-1")
        assert en_revision.operation_type == "cliente_club.edicion" and "telefono" in en_revision.motivo
        # Quien opera el central lo acuerda a mano y reintenta.
        conn.execute("UPDATE clientes SET telefono = '11 5555 1234' WHERE id > 0")
        conn.commit()
        assert reintentar(conn, edicion.operation_id, despachador, "pruebas").result == "accepted"
        conn.commit()
    assert filas("SELECT telefono FROM clientes WHERE id > 0") == [("11 5555 9999",)]


def test_en_un_nodo_la_correccion_de_un_provisorio_va_por_http_aun_con_conexion(staff, nodo, sesion):
    cliente = staff.post("/api/clientes", json={"nombre": "Juan Pérez"}).json()
    nodo.en_linea(True)

    editado = staff.put(f"/api/clientes/{cliente['id']}", json={"nombre": "Juan Pérez", "telefono": "11 1"})
    borrado = staff.delete(f"/api/clientes/{cliente['id']}")

    assert editado.status_code == 200 and editado.json()["telefono"] == "11 1"
    assert borrado.status_code == 409 and borrado.json()["detail"]["codigo"] == "solo_en_el_central"
    assert tipos_encolados() == ["cliente_club.alta", "cliente_club.edicion"]
