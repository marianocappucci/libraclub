# ruff: noqa: F811  -- las fixtures importadas se piden por nombre en cada test
"""La matriz de roles de lo que el nodo suma, lo que el aprovisionamiento publica y lo que el nodo no hace (ADR-023).

LibraClub no tiene un archivo de matriz de roles como VentaLibra (`test_roles_matriz.py`): sus rutas declaran el rol
en cada router. Lo que este PR monta se fija acá, **escrito a mano** (no se deriva del código, o no se pondría rojo
nunca):

| Rutas | Quién entra |
|---|---|
| `libraedge.sync.api.RUTAS_AUTENTICADAS_POR_NODO` (push, pull, ticket-arca, carga-inicial, estado-operaciones) |
PÚBLICA, secreto del nodo: ni sesión ni rol | | `POST /sync/v1/vinculacion` (el canje del código) | PÚBLICA: la llama
el instalador | | `/api/nodos-offline*` («Sucursal sin internet») | ADMIN |
| `GET /api/nodo/conexion`, `GET /api/nodo/cola` y `POST /api/nodo/cola/emitir` | STAFF (mostrador) |
| `POST /api/nodo/cola/{id}/reintentar`, `/descartar`, `/emitido` | ADMIN: deciden sobre un documento fiscal |
"""

from __future__ import annotations

import gc

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libracore.db import core as libracore_core
from libraedge.aprovisionamiento import plan_de_publicacion, registrar
from libraedge.sync.api import RUTAS_AUTENTICADAS_POR_NODO

from app import offline
from tests.nodo_apoyo import (
    NODO,
    armar_app,
    cliente_logueado,
    filas,
    nodo,  # noqa: F401  (fixture)
    nodo_apagado,  # noqa: F401  (fixture)
)


@pytest.fixture
def app_con_roles(engine, sesion, monkeypatch, base_de_libracore):
    app = armar_app(engine, monkeypatch, base_de_libracore, con_staff=True)
    yield app
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def clientes(app_con_roles):
    anonimo = TestClient(app_con_roles, base_url="https://testserver")
    return {"anonimo": anonimo, "staff": cliente_logueado(app_con_roles, "encargado"),
            "admin": cliente_logueado(app_con_roles)}


def _llamar(cliente, metodo, ruta):
    return cliente.request(metodo, ruta, json={} if metodo != "GET" else None)


# ── PÚBLICA, secreto del nodo ───────────────────────────────────────────────────────────────────────────────────────


#: Un pedido bien formado para cada ruta del nodo: el 422 de un cuerpo mal armado llega antes que el 401 del secreto.
PEDIDOS_DEL_NODO = {
    ("POST", "/sync/v1/push"): {"json": {
        "operation_id": "x:1", "node_id": "x", "sequence": 1, "operation_type": "venta.registrada",
        "aggregate_type": "venta", "aggregate_id": "x:venta:1", "occurred_at": "2026-10-24T00:00:00+00:00",
        "schema_version": 1, "payload": {}}},
    ("GET", "/sync/v1/pull"): {"params": {"node_id": "x"}},
    ("POST", "/sync/v1/ticket-arca"): {"json": {"node_id": "x"}},
    ("GET", "/sync/v1/carga-inicial"): {"params": {"node_id": "x"}},
    ("POST", "/sync/v1/estado-operaciones"): {"json": {"node_id": "x", "operation_ids": ["x:1"]}},
}


def test_los_pedidos_de_la_matriz_son_las_rutas_del_nodo():
    assert set(PEDIDOS_DEL_NODO) == set(RUTAS_AUTENTICADAS_POR_NODO)


@pytest.mark.parametrize(("metodo", "ruta"), RUTAS_AUTENTICADAS_POR_NODO)
def test_las_rutas_del_nodo_piden_el_secreto_y_no_la_sesion(clientes, metodo, ruta):
    """Sin un nodo registrado no existe ningún secreto válido: 401 a todos, también al admin con sesión. Si alguien las
    montara detrás de un rol, el nodo (que no tiene sesión) no podría sincronizar; si las abriera, cualquiera
    empujaría
    operaciones al central."""
    for quien, cliente in clientes.items():
        r = cliente.request(metodo, ruta, **PEDIDOS_DEL_NODO[(metodo, ruta)])
        assert r.status_code == 401, (quien, metodo, ruta, r.status_code, r.text)


def test_el_canje_del_codigo_es_publico(clientes, monkeypatch):
    """Lo llama el instalador, sin sesión: lo protegen el código (un solo uso) y el límite de intentos. Un código que
    no sirve es 404, y no un 401/403 de rol."""
    monkeypatch.setenv("LIBRAEDGE_CENTRAL_URL", "https://club.example.com")
    for quien, cliente in clientes.items():
        r = cliente.post("/sync/v1/vinculacion", json={"codigo": "AAAA-BBBB", "producto": "libraclub"})
        assert r.status_code == 404, (quien, r.status_code, r.text)


# ── ADMIN ───────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("metodo", "ruta"), [
    ("GET", "/api/nodos-offline"),
    ("GET", "/api/nodos-offline/menu"),
    ("POST", "/api/nodos-offline"),
    ("POST", "/api/nodos-offline/vinculacion"),
    ("POST", "/api/nodos-offline/inexistente/vinculacion"),
    ("DELETE", "/api/nodos-offline/inexistente/vinculacion"),
    ("POST", "/api/nodos-offline/inexistente/carga"),
    ("DELETE", "/api/nodos-offline/inexistente"),
    ("POST", "/api/nodo/cola/999999/reintentar"),
    ("POST", "/api/nodo/cola/999999/descartar"),
    ("POST", "/api/nodo/cola/999999/emitido"),
])
def test_alta_y_baja_de_nodos_y_resolver_la_cola_son_del_admin(clientes, metodo, ruta):
    assert _llamar(clientes["anonimo"], metodo, ruta).status_code == 401, ruta
    assert _llamar(clientes["staff"], metodo, ruta).status_code == 403, ruta
    assert _llamar(clientes["admin"], metodo, ruta).status_code not in (401, 403), ruta


def test_el_admin_ve_la_pantalla_de_sucursal_sin_internet(clientes, sucursal):
    r = clientes["admin"].get("/api/nodos-offline")
    assert r.status_code == 200, r.text


# ── STAFF ───────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("metodo", "ruta"), [
    ("GET", "/api/nodo/conexion"), ("GET", "/api/nodo/cola"), ("POST", "/api/nodo/cola/emitir"),
])
def test_ver_la_conexion_la_cola_y_pedir_que_se_emita_es_del_mostrador(clientes, metodo, ruta):
    assert _llamar(clientes["anonimo"], metodo, ruta).status_code == 401, ruta
    assert _llamar(clientes["staff"], metodo, ruta).status_code == 200, ruta
    assert _llamar(clientes["admin"], metodo, ruta).status_code == 200, ruta


def test_toda_ruta_del_nodo_tiene_una_fila_en_esta_matriz(app_con_roles):
    """Una ruta nueva de sincronización o de nodo que nadie decidió quién entra, falla acá."""
    decididas = {ruta for _, ruta in RUTAS_AUTENTICADAS_POR_NODO} | {
        "/sync/v1/vinculacion", "/sync/v1/salud", "/sync/v1/salud/{node_id}",
        "/api/nodos-offline", "/api/nodos-offline/menu", "/api/nodos-offline/vinculacion",
        "/api/nodos-offline/{node_id}/vinculacion", "/api/nodos-offline/{node_id}/carga",
        "/api/nodos-offline/{node_id}",
        "/api/nodo/conexion", "/api/nodo/cola", "/api/nodo/cola/emitir", "/api/nodo/cola/{pedido_id}/reintentar",
        "/api/nodo/cola/{pedido_id}/descartar", "/api/nodo/cola/{pedido_id}/emitido",
    }
    montadas = {
        ruta for ruta in app_con_roles.openapi()["paths"]
        if ruta.startswith(("/sync/", "/api/nodos-offline", "/api/nodo/"))
    }
    assert montadas - decididas == set(), f"rutas del nodo sin decidir: {sorted(montadas - decididas)}"
    assert decididas - montadas == set(), f"filas de la matriz que ya no existen: {sorted(decididas - montadas)}"


def test_las_de_salud_piden_el_token_de_monitoreo(clientes):
    """`/sync/v1/salud` no es del secreto del nodo ni de la sesión: es del token de monitoreo (uptime-kuma)."""
    for quien, cliente in clientes.items():
        assert cliente.get("/sync/v1/salud").status_code in (401, 403, 404, 503), quien


# ── Lo que el nodo no hace: 409 `solo_en_el_central` ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), [
    ("POST", "/api/sucursales", {"nombre": "Otra"}),
    ("POST", "/api/buffet/productos?sucursal_id=1", {"nombre": "x", "precio": "1"}),
    ("POST", "/api/buffet/ventas/qr?sucursal_id=1", {"lineas": [{"item_id": 1, "cantidad": "1"}]}),
    ("POST", "/api/reservas/1/mp-qr", {}),
    ("POST", "/api/cajas", {"nombre": "Otra", "sucursal_id": 1}),
    ("POST", "/api/facturas", {}),
])
def test_en_un_nodo_lo_que_manda_el_central_se_contesta_409(clientes, nodo, metodo, ruta, cuerpo):
    """El catálogo, los maestros, las cajas, el cobro con QR y la facturación manual no se escriben en el nodo: sus ids
    saldrían de la secuencia del nodo y chocarían con los del central (o numerarían local, ADR-074)."""
    r = clientes["admin"].request(metodo, ruta, json=cuerpo)
    assert r.status_code == 409, (ruta, r.status_code, r.text)
    assert r.json()["detail"]["codigo"] == "solo_en_el_central"


def test_en_un_nodo_los_maestros_se_leen(clientes, nodo, sucursal, cancha):
    """Las lecturas pasan: el nodo muestra lo que el espejo le trajo."""
    assert clientes["admin"].get("/api/sucursales").status_code == 200
    assert clientes["admin"].get("/api/canchas").status_code == 200
    assert clientes["admin"].get("/api/facturas").status_code != 409


def test_fuera_de_un_nodo_esos_mismos_pedidos_andan(clientes, nodo_apagado):
    """«Fuera de un nodo nada cambia»: la guarda no hace nada en el central."""
    assert clientes["admin"].post("/api/sucursales", json={"nombre": "Otra"}).status_code == 201
    assert clientes["admin"].post("/api/clientes", json={"nombre": "Alguien"}).status_code == 201


def test_en_un_nodo_sin_el_deposito_del_buffet_se_avisa_que_viene_del_central(clientes, nodo, sucursal):
    """El depósito del buffet se crea en el central y baja por el espejo: crearlo en el nodo chocaría con sus ids."""
    r = clientes["staff"].get(f"/api/buffet/productos?sucursal_id={sucursal.id}")
    assert r.status_code == 409 and "central" in r.json()["detail"]
    assert filas("SELECT count(*) FROM locations") == [(0,)]
    # La conexión del repositorio queda colgada de la excepción hasta que el recolector la junte, y con ella un lock
    # que frena el `TRUNCATE` del test siguiente.
    gc.collect()


def test_en_el_central_el_deposito_del_buffet_se_crea_solo(clientes, nodo_apagado, sucursal):
    r = clientes["staff"].get(f"/api/buffet/productos?sucursal_id={sucursal.id}")
    assert r.status_code == 200
    assert filas("SELECT count(*) FROM locations") == [(1,)]


# ── El aprovisionamiento ────────────────────────────────────────────────────────────────────────────────────────────

#: Lo que el nodo genera o no debe tener: no se espeja. Cada una con su motivo.
PROHIBIDAS = {
    "arca_credenciales_servicio": "el ticket de ARCA lo presta el central; la clave no sale del VPS",
    "secretos_instancia": "el almacén de claves cifradas (MercadoPago, SMTP) es del central",
    "cola_arca": "la cola de comprobantes es del nodo; sube como cola.pedido",
    "facturas": "las facturas del nodo suben como club.factura_conjunta; el central numera las suyas",
    "caja_movimientos": "la caja del nodo sube como operaciones",
    "turnos_caja": "idem",
    "cierres_diarios": "idem",
    "sales": "las ventas del buffet suben como venta.registrada",
    "sale_items": "idem",
    "stock_movements": "el stock de la sucursal lo mueve el nodo; suben stock.movimiento",
    "venta_origen_nodo": "es del central",
    "pagos_de_reserva": "el pago de una reserva dada en el nodo sube como caja.movimiento; el reapuntado de la reserva "
                        "provisoria borraría estas filas si se espejaran",
    "cc_asientos": "la cuenta corriente no se opera en el nodo",
    "avisos_envios": "el nodo no manda avisos: los deduce y los manda el barrido del central (libracore ADR-090, "
                     "LibraClub ADR-030); espejarla bajaría a cada club los teléfonos y los textos de los demás",
    "avisos": "legado: el registro viejo de avisos (ADR-030), sin uso; tampoco se espeja",
    "config_avisos": "qué tipos de aviso salen lo decide el central, que es el que los manda",
    "sync_outbox": "es del nodo",
    "sync_inbox": "es del central",
    "node_identity": "es del central",
}


def test_la_cadena_de_migraciones_crea_las_tablas_de_libraedge_y_tiene_una_sola_cabeza(engine):
    """El central las necesita aunque no tenga nodos (`node_identity` para autenticarlos, `sync_inbox` para deduplicar,
    `libraedge_mapeo` para las reservas). Y una sola cabeza: dos PR que agregan una revisión a la misma cadena se
    pisan."""
    import os

    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = AlembicConfig(os.path.join(raiz, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(raiz, "migrations"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1
    for tabla in ("node_identity", "sync_inbox", "sync_outbox", "libraedge_mapeo", "sync_changelog"):
        assert filas("SELECT to_regclass(%s)", (f"public.{tabla}",)) == [(tabla,)], tabla


def test_el_aprovisionamiento_no_espeja_lo_prohibido():
    espejadas = offline.aprovisionamiento.nombres
    assert espejadas & set(PROHIBIDAS) == set(), {
        t: PROHIBIDAS[t] for t in espejadas & set(PROHIBIDAS)}


def test_el_aprovisionamiento_espeja_lo_que_el_nodo_necesita():
    necesarias = {"sucursales", "canchas", "clientes", "tarifas", "reservas", "usuarios", "cajas", "arca_config",
                  "locations", "catalog_items", "item_prices", "units"}
    assert necesarias <= offline.aprovisionamiento.nombres


def test_las_reservas_y_los_clientes_se_dan_en_el_nodo():
    """`clientes` (ADR-022, addendum) se da de alta en el nodo con id provisorio; sus referencias tienen FK y las lee
    LibraEdge del catálogo, así que no declara ninguna."""
    cliente, reserva = offline.aprovisionamiento.altas
    assert cliente.tabla == "clientes" and cliente.referencias == ()
    assert [reserva.tabla] == ["reservas"]


def test_las_reservas_se_dan_en_el_nodo_y_se_reapunta_el_vinculo_del_buffet():
    _, alta = offline.aprovisionamiento.altas
    assert alta.tabla == "reservas"
    assert [(r.tabla, r.columna, r.donde) for r in alta.referencias] == [
        ("sales", "source_id", (("source_type", "reserva"),))]


def test_los_maestros_son_de_solo_lectura_en_el_nodo():
    solo_lectura = offline.aprovisionamiento.solo_lectura
    assert {"sucursales", "canchas", "tarifas", "catalog_items", "locations"} <= solo_lectura
    # Lo que el nodo sí escribe: las reservas y los clientes que da, y el espejo del usuario del cajero.
    assert not ({"reservas", "clientes", "usuarios", "cajas"} & solo_lectura)


def test_toda_tabla_de_referencia_existe_y_se_puede_publicar(engine, base_de_libracore):
    """Un nombre mal escrito, o una tabla sin clave primaria, deja un agujero en el espejo que recién se ve en el
    club."""
    with libracore_core.get_connection() as conn:
        plan = plan_de_publicacion(conn, offline.aprovisionamiento)
    assert plan.faltantes == () and plan.salteadas == ()
    assert "libraedge_mapeo" in dict(plan.publicables)


def test_se_puede_registrar_un_nodo_de_una_sucursal(engine, base_de_libracore, sucursal, nodo_apagado):
    """El alta de punta a punta: las sucursales salen de `sucursales` (no de `branches`, vacía), el depósito del
    buffet tiene sucursal y las altas en el nodo se publican."""
    with libracore_core.get_connection() as conn:
        alta = registrar(conn, offline.aprovisionamiento, NODO, str(sucursal.id), salida=lambda *_: None)
    assert alta.sucursal.nombre == "Complejo Centro"
    assert "reservas" in alta.espejo and "libraedge_mapeo" in alta.espejo
    assert "clientes" in alta.espejo and "clientes" not in alta.solo_lectura
    assert set(alta.solo_lectura) >= {"sucursales", "canchas"}


def test_las_sucursales_de_un_nodo_son_las_del_dominio(sucursal, engine, base_de_libracore):
    with libracore_core.get_connection() as conn:
        assert offline.listar_sucursales(conn) == [{"id": sucursal.id, "nombre": "Complejo Centro", "activa": True}]

