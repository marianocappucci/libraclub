"""Dar de alta un cliente en el club sin conexión: id provisorio, operación encolada y lo que el nodo no deja (ADR-022).

Se simula un nodo con `clientes_nodo.configurar(...)` (y las tablas de LibraEdge sobre la base de la suite cuando se
mide el outbox de verdad). Lo que se mide: el id provisorio, la operación `cliente_club.alta` encolada en la misma
transacción, las guardas 409 y que **fuera de un nodo el alta sigue igual**.
"""

# Los fixtures se importan de otros módulos y se piden por nombre en cada test: ruff lo lee como «redefinición de un
# import sin usar» (F811). La suite pone un `noqa` por test; acá, uno por archivo.
# ruff: noqa: F811

from __future__ import annotations

import json

import pytest
from libracommerce.erp.offline import NodoLocal, Outbox
from libracore.nodo_offline import SinConexion, SoloEnElCentral
from sqlalchemy import text

from app.models import Base
from app.models.maestros import Cliente
from app.servicios import clientes_nodo, portal, reservas_nodo
from app.servicios import reservas as servicio_reservas
from tests.clientes_nodo_apoyo import NODO, nodo_clientes  # noqa: F401  (fixture)
from tests.reservas_nodo_apoyo import a_las, nodo, preparar_tablas_de_libraedge  # noqa: F401  (fixture)
from tests.test_api import api_staff  # noqa: F401  (fixture)

NUEVO = {"nombre": "Juan Pérez", "telefono": "11 5555 1234", "email": "juan@example.com", "documento": "30.123.456"}


def _ids(sesion) -> list[int]:
    return list(sesion.execute(text("SELECT id FROM clientes ORDER BY id")).scalars())


# ── Fuera de un nodo, el alta sigue igual ────────────────────────────────────


def test_fuera_de_un_nodo_el_cliente_nace_con_el_id_de_la_base(sesion):
    """Sin `configurar()` (el central, una instalación común, la web) `agregar` es `sesion.add`."""
    cliente = clientes_nodo.agregar(sesion, Cliente(nombre="Ana"))
    assert cliente.id is None, "todavía sin flush: es el `add` de siempre"
    sesion.commit()
    assert cliente.id > 0


def test_configurado_pero_sin_nodo_tampoco_cambia_nada(sesion):
    llamadas = []
    clientes_nodo.configurar(
        clientes_nodo.ClientesEnNodo(
            nodo=lambda: None, id_provisorio=lambda conn: llamadas.append("id") or -1,
            al_crear_cliente=lambda conn, datos: llamadas.append("alta"),
        )
    )
    try:
        cliente = clientes_nodo.agregar(sesion, Cliente(nombre="Ana"))
        sesion.commit()
    finally:
        clientes_nodo.configurar(None)
    assert cliente.id > 0 and llamadas == [], "ni id provisorio ni gancho"


def test_por_http_fuera_de_un_nodo_el_alta_sigue_igual(api_staff, sesion):
    creado = api_staff.post("/api/clientes", json=NUEVO)
    assert creado.status_code == 201, creado.text
    assert creado.json()["id"] > 0 and creado.json()["nombre"] == "Juan Pérez"
    # Editar y borrar tampoco cambian.
    editado = api_staff.put(f"/api/clientes/{creado.json()['id']}", json={**NUEVO, "nombre": "Juan P."})
    assert editado.status_code == 200 and editado.json()["nombre"] == "Juan P."
    assert api_staff.delete(f"/api/clientes/{creado.json()['id']}").status_code == 204


def test_fuera_de_un_nodo_el_portal_registra_como_siempre(sesion):
    cuenta = portal.registrar(sesion, email="ana@example.com", password="una-clave-larga", nombre="Ana")
    sesion.commit()
    assert cuenta.cliente_id > 0


# ── En un nodo: id provisorio y operación ────────────────────────────────────


def test_en_un_nodo_el_cliente_nace_con_id_negativo_y_se_encola_el_alta(sesion, nodo_clientes):
    nuevo = Cliente(nombre="Juan Pérez", email="juan@example.com", documento="30123456")
    cliente = clientes_nodo.agregar(sesion, nuevo)
    sesion.commit()

    assert cliente.id == -1
    assert _ids(sesion) == [-1]
    (datos,) = nodo_clientes.altas
    assert datos["version"] == 1 and datos["cliente_id"] == -1
    assert (datos["nombre"], datos["email"], datos["documento"]) == ("Juan Pérez", "juan@example.com", "30123456")
    assert datos["activo"] is True and datos["acepta_avisos"] is True and datos["creada_at"]


def test_los_ids_provisorios_no_se_repiten(sesion, nodo_clientes):
    uno = clientes_nodo.agregar(sesion, Cliente(nombre="Uno"))
    dos = clientes_nodo.agregar(sesion, Cliente(nombre="Dos"))
    sesion.commit()
    assert (uno.id, dos.id) == (-1, -2)
    assert [d["cliente_id"] for d in nodo_clientes.altas] == [-1, -2]


def test_por_http_el_alta_en_el_nodo_da_id_negativo_y_encola(api_staff, sesion, nodo_clientes):
    datos = {**NUEVO, "acepta_avisos": False, "observaciones": "Juega los martes"}
    creado = api_staff.post("/api/clientes", json=datos)
    assert creado.status_code == 201, creado.text
    assert creado.json()["id"] == -1

    (datos,) = nodo_clientes.altas
    assert datos["acepta_avisos"] is False and datos["observaciones"] == "Juega los martes"
    # Y se lo ve en el listado y por id, como cualquiera.
    assert [c["id"] for c in api_staff.get("/api/clientes").json()] == [-1]
    assert api_staff.get("/api/clientes/-1").json()["nombre"] == "Juan Pérez"


def test_si_el_encolado_falla_el_cliente_no_queda(sesion):
    """Un cliente que se da de alta en el nodo y no sube no es «a medias»: la reserva a su nombre se rechazaría."""
    def falla(conn, datos):
        raise RuntimeError("el outbox no anda")

    clientes_nodo.configurar(
        clientes_nodo.ClientesEnNodo(nodo=lambda: NODO, id_provisorio=lambda conn: -1, al_crear_cliente=falla)
    )
    try:
        with pytest.raises(RuntimeError, match="el outbox no anda"):
            clientes_nodo.agregar(sesion, Cliente(nombre="Juan"))
        sesion.rollback()
    finally:
        clientes_nodo.configurar(None)
    assert _ids(sesion) == []


def test_un_id_provisorio_que_no_es_negativo_se_rechaza(sesion):
    clientes_nodo.configurar(clientes_nodo.ClientesEnNodo(nodo=lambda: NODO, id_provisorio=lambda conn: 7))
    try:
        with pytest.raises(ValueError, match="negativo"):
            clientes_nodo.agregar(sesion, Cliente(nombre="Juan"))
    finally:
        clientes_nodo.configurar(None)


def test_el_cliente_provisorio_sirve_para_tomar_una_reserva(sesion, cancha, tarifa_base, nodo_clientes, nodo):
    """El caso de uso: llama alguien nuevo, se lo da de alta y se le toma el turno, todo sin conexión."""
    cliente = clientes_nodo.agregar(sesion, Cliente(nombre="Juan Pérez"))
    sesion.commit()

    reserva = servicio_reservas.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20))
    sesion.commit()

    assert cliente.id == -1 and reserva.id < 0 and reserva.cliente_id == -1
    assert nodo.creadas[0]["cliente_id"] == -1, "la operación de la reserva lleva el id provisorio del cliente"


# ── En un nodo: las guardas ──────────────────────────────────────────────────


def _cliente_del_central(sesion) -> int:
    cliente = Cliente(nombre="Del central")
    sesion.add(cliente)
    sesion.commit()
    return cliente.id


def test_sin_conexion_editar_o_borrar_un_cliente_del_central_da_409_sin_conexion(api_staff, sesion, nodo_clientes):
    cliente_id = _cliente_del_central(sesion)
    for respuesta in (
        api_staff.put(f"/api/clientes/{cliente_id}", json={"nombre": "Otro"}),
        api_staff.delete(f"/api/clientes/{cliente_id}"),
    ):
        assert respuesta.status_code == 409, respuesta.text
        assert respuesta.json()["detail"]["codigo"] == "sin_conexion"
        assert "conexión" in respuesta.json()["detail"]["mensaje"]


def test_con_conexion_el_nodo_tampoco_cambia_un_cliente_del_central(api_staff, sesion, nodo_clientes):
    cliente_id = _cliente_del_central(sesion)
    nodo_clientes.en_linea = True
    respuesta = api_staff.put(f"/api/clientes/{cliente_id}", json={"nombre": "Otro"})
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"]["codigo"] == "solo_en_el_central"
    assert sesion.get(Cliente, cliente_id).nombre == "Del central", "no se tocó"


def test_un_cliente_provisorio_tampoco_se_edita_porque_ya_subio_con_sus_datos(api_staff, sesion, nodo_clientes):
    creado = api_staff.post("/api/clientes", json=NUEVO).json()
    for respuesta in (
        api_staff.put(f"/api/clientes/{creado['id']}", json={**NUEVO, "nombre": "Juan Perez"}),
        api_staff.delete(f"/api/clientes/{creado['id']}"),
    ):
        assert respuesta.status_code == 409, respuesta.text
        assert respuesta.json()["detail"]["codigo"] == "solo_en_el_central"
    assert api_staff.get(f"/api/clientes/{creado['id']}").json()["nombre"] == "Juan Pérez"


def test_un_nodo_cuyo_estado_no_se_puede_leer_se_toma_sin_conexion(sesion):
    def roto():
        raise RuntimeError("no sé")

    clientes_nodo.configurar(
        clientes_nodo.ClientesEnNodo(nodo=lambda: NODO, id_provisorio=lambda conn: -1, en_linea=roto)
    )
    try:
        with pytest.raises(SinConexion):
            clientes_nodo.exigir_cliente_modificable(5)
    finally:
        clientes_nodo.configurar(None)


def test_fuera_de_un_nodo_la_guarda_no_hace_nada():
    clientes_nodo.exigir_cliente_modificable(5)
    clientes_nodo.exigir_cliente_modificable(-5)
    clientes_nodo.exigir_central_para_el_portal()


def test_en_un_nodo_el_portal_no_registra_cuentas(sesion, nodo_clientes):
    with pytest.raises(SoloEnElCentral):
        portal.registrar(sesion, email="ana@example.com", password="una-clave-larga", nombre="Ana")
    assert _ids(sesion) == [], "ni siquiera el cliente"


# ── Con el outbox de verdad ──────────────────────────────────────────────────


@pytest.fixture
def nodo_con_outbox(sesion):
    """El `Outbox` de libracommerce armado como lo va a armar el producto (PR 11), sin el proceso del nodo."""
    preparar_tablas_de_libraedge(sesion)
    outbox = Outbox(nodo=lambda: NodoLocal(node_id=NODO, prefijo="S01"), en_linea=lambda: False)
    clientes_nodo.configurar(clientes_nodo.desde_el_outbox(outbox))
    reservas_nodo.configurar(reservas_nodo.desde_el_outbox(outbox))
    yield outbox
    clientes_nodo.configurar(None)
    reservas_nodo.configurar(None)


def _outbox(sesion) -> list[tuple]:
    return list(
        sesion.execute(
            text("SELECT operation_type, aggregate_type, aggregate_id, payload_json FROM sync_outbox ORDER BY sequence")
        ).all()
    )


def test_la_operacion_entra_en_el_outbox_en_la_misma_transaccion(api_staff, sesion, nodo_con_outbox):
    creado = api_staff.post("/api/clientes", json=NUEVO)
    assert creado.status_code == 201, creado.text

    ((tipo, agregado, agregado_id, payload),) = _outbox(sesion)
    assert (tipo, agregado, agregado_id) == ("cliente_club.alta", "cliente_club", f"{NODO}:cliente_club:-1")
    datos = json.loads(payload)
    assert datos["cliente_id"] == -1 and datos["nombre"] == "Juan Pérez" and datos["documento"] == "30.123.456"


def test_si_el_alta_se_deshace_la_operacion_tambien(sesion, nodo_con_outbox):
    """El cliente y su operación viven o mueren juntos: es lo que justifica `conexion_de_la_sesion`."""
    clientes_nodo.agregar(sesion, Cliente(nombre="Juan"))
    assert len(_outbox(sesion)) == 1
    sesion.rollback()
    assert _outbox(sesion) == [] and _ids(sesion) == []


def test_el_alta_sube_antes_que_la_reserva_que_la_usa(api_staff, sesion, cancha, tarifa_base, nodo_con_outbox):
    """Causalidad del outbox (ADR-020 de libraedge): el nodo sube por `(node_id, sequence)`, así que el alta —que se
    encoló primero— llega antes que la `reserva.creada` que lleva su id provisorio."""
    cliente_id = api_staff.post("/api/clientes", json=NUEVO).json()["id"]
    reserva = api_staff.post(
        "/api/reservas",
        json={"cancha_id": cancha.id, "cliente_id": cliente_id, "comienza_at": a_las(20).isoformat()},
    )
    assert reserva.status_code == 201, reserva.text

    filas = _outbox(sesion)
    assert [f[0] for f in filas] == ["cliente_club.alta", "reserva.creada"]
    assert json.loads(filas[1][3])["cliente_id"] == cliente_id == -1


def test_fuera_de_un_nodo_el_outbox_no_se_toca(sesion):
    """El mismo `desde_el_outbox` armado en el central (`nodo()` devuelve `None`): ni id provisorio ni operación, y no
    hace falta que libraedge esté instalado."""
    clientes_nodo.configurar(clientes_nodo.desde_el_outbox(Outbox(nodo=lambda: None)))
    try:
        cliente = clientes_nodo.agregar(sesion, Cliente(nombre="Ana"))
        sesion.commit()
    finally:
        clientes_nodo.configurar(None)
    assert cliente.id > 0


# ── El contrato con el aprovisionamiento ─────────────────────────────────────


def test_las_altas_en_nodo_que_el_pr_11_suma_al_aprovisionamiento():
    assert clientes_nodo.ALTAS_EN_NODO == ("clientes",)
    pytest.importorskip("libraedge", reason="libraedge todavía no es dependencia de LibraClub (lo suma el PR 11)")
    from libraedge.altas import AltaEnNodo, normalizar_altas

    assert clientes_nodo.altas_en_nodo() == [AltaEnNodo("clientes")]
    assert normalizar_altas([*clientes_nodo.ALTAS_EN_NODO]) == (AltaEnNodo("clientes"),)


def test_todo_lo_que_guarda_un_cliente_tiene_clave_foranea_y_se_reapunta_solo():
    """`AltaEnNodo("clientes")` no declara referencias: `libraedge` reapunta las FK que lee del catálogo. Una columna
    que guarde el id de un cliente **sin** FK quedaría apuntando a un provisorio que ya no existe. Este test falla
    antes."""
    sin_fk = []
    for tabla in Base.metadata.tables.values():
        for columna in tabla.columns:
            apunta = any(fk.column.table.name == "clientes" for fk in columna.foreign_keys)
            if (columna.name == "cliente_id" or columna.name.endswith("_cliente_id")) and not apunta:
                sin_fk.append(f"{tabla.name}.{columna.name}")
    assert sin_fk == []

    con_fk = sorted(
        f"{tabla.name}.{columna.name}"
        for tabla in Base.metadata.tables.values()
        for columna in tabla.columns
        if any(fk.column.table.name == "clientes" for fk in columna.foreign_keys)
    )
    assert con_fk == ["cuentas_de_jugador.cliente_id", "reservas.cliente_id", "series.cliente_id"]
