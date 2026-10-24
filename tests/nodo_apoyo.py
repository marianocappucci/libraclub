"""Lo que comparten los tests del nodo sin conexión (ADR-023).

Ninguno levanta el proceso real del nodo (`libraedge-nodo`) ni el transporte: se ejercitan las piezas de LibraClub con
las tablas de LibraEdge creadas sobre la base de la suite, que es exactamente lo que el producto ve en un nodo. La
misma base hace de nodo y de central **en momentos distintos** (`SyncReceiver` aplica en el central lo que el nodo
encoló):

1. *Fase del nodo*: la variable `LIBRAEDGE_NODE_ID` prendida; se opera (buffet, caja, cobros, factura) y el outbox junta
   las operaciones.
2. `vaciar_lo_del_nodo()` borra lo que el nodo generó (ventas, caja, stock, facturas, cola): lo que en la vida real no
   existe en el central hasta que sube. Los maestros y las reservas espejadas se quedan, como el espejo los deja.
3. *Fase del central*: sin la variable, `aplicar_en_el_central(operaciones)` pasa cada operación por el receptor real.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from libracore.db import core as libracore_core
from libraedge.db.repository import NodeRepository
from libraedge.db.schema import init_schema
from libraedge.sync.receiver import SyncReceiver

from app.config import Config
from app.main import crear_app
from tests.conftest import url_del_core

NODO = "club-1"
USUARIO, CLAVE = "admin", "clave-de-prueba"

#: Lo que el nodo genera y sube: en el central no existe hasta que llega.
TABLAS_DEL_NODO = (
    "sales", "stock_movements", "caja_movimientos", "turnos_caja", "cierres_diarios", "facturas", "cola_arca",
    "sync_outbox", "sync_inbox", "venta_origen_nodo",
)


def config(url_core: str) -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos", libracore_database_url=url_core,
    )


def armar_app(engine, monkeypatch, url_core: str, *, con_staff: bool = False):
    """La app de LibraClub con un admin (y, si se pide, un encargado), para los tests del nodo."""
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    app = crear_app(config(url_core))
    if con_staff:
        app.state.users.create(username="encargado", name="Encargado", password=CLAVE, role="staff")
    return app


def cliente_logueado(app, usuario: str = USUARIO) -> TestClient:
    cliente = TestClient(app, base_url="https://testserver")
    assert cliente.post("/auth/login", json={"username": usuario, "password": CLAVE}).status_code == 200
    return cliente


def crear_tablas_de_libraedge() -> None:
    """Las tablas que LibraEdge pone en un nodo (y en el central): outbox, inbox, secuencias, mapeo, `node_identity`."""
    with libracore_core.get_connection() as conn:
        init_schema(conn)
        # La revisión `0010` de libracommerce (`libracommerce-migrar`): el central la necesita para recibir una venta
        # con vínculo (la del buffet colgada de una reserva). La suite no corre la cadena de LibraCommerce; es la
        # misma tabla.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS venta_origen_nodo (node_id TEXT NOT NULL, venta_id_nodo BIGINT NOT NULL, "
            "venta_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE, PRIMARY KEY (node_id, venta_id_nodo))"
        )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_venta_origen_nodo_venta ON venta_origen_nodo(venta_id)")
        conn.commit()


def escribir_estado(ruta, en_linea: bool) -> None:
    ruta.write_text(json.dumps({
        "en_linea": en_linea, "ultima_sincronizacion_ok": datetime.now(UTC).isoformat(),
    }), encoding="utf-8")


@pytest.fixture
def nodo_apagado(monkeypatch, tmp_path):
    """Un nodo todavía apagado: las tablas de LibraEdge creadas y las variables puestas, sin `LIBRAEDGE_NODE_ID`.

    Sirve para preparar lo que el central manda (productos, depósito, reservas) antes de `prender()`: en un nodo el
    catálogo no se escribe. Devuelve un objeto con `prender()`, `apagar()` y `en_linea(bool)`."""
    crear_tablas_de_libraedge()
    estado = tmp_path / "estado-del-nodo.json"
    escribir_estado(estado, False)
    monkeypatch.setenv("LIBRAEDGE_ESTADO", str(estado))
    monkeypatch.setenv("LIBRAEDGE_PREFIJO", "S02")
    control = SimpleNamespace(nodo=NODO)

    def prender() -> None:
        monkeypatch.setenv("LIBRAEDGE_NODE_ID", NODO)

    def apagar() -> None:
        monkeypatch.delenv("LIBRAEDGE_NODE_ID", raising=False)

    def en_linea(valor: bool) -> None:
        escribir_estado(estado, valor)

    control.prender, control.apagar, control.en_linea = prender, apagar, en_linea
    return control


@pytest.fixture
def nodo(nodo_apagado):
    """Este proceso es el nodo `club-1`, sin conexión. `nodo.en_linea(True)` la devuelve."""
    nodo_apagado.prender()
    return nodo_apagado


def operaciones() -> list:
    """Las operaciones del outbox del nodo, en el orden en que ocurrieron (una sola secuencia por nodo)."""
    with libracore_core.get_connection() as conn:
        return list(NodeRepository(conn).list_pending_operations(limit=1000))


def tipos_encolados() -> list[str]:
    return [op.operation_type for op in operaciones()]


def vaciar_lo_del_nodo() -> None:
    """Borra lo que el nodo generó, como si el central fuera otra base que todavía no lo recibió."""
    with libracore_core.get_connection() as conn:
        conn.execute("TRUNCATE " + ", ".join(TABLAS_DEL_NODO) + " RESTART IDENTITY CASCADE")
        conn.commit()


def aplicar_en_el_central(ops: list) -> list[str]:
    """Pasa cada operación por el receptor real del central (con su `sync_inbox`) y devuelve el resultado de cada una:
    `accepted`, `duplicate` o `rejected: <motivo>`."""
    from app.routers.sincronizacion_offline import despachador

    resultados = []
    for op in ops:
        with libracore_core.get_connection() as conn:
            r = SyncReceiver(conn, despachador=despachador).accept(op)
            conn.commit()
        resultados.append(r.result if r.error is None else f"{r.result}: {r.error}")
    return resultados


def filas(sql: str, params: tuple = ()) -> list[tuple]:
    import psycopg

    with psycopg.connect(url_del_core()) as con:
        return con.execute(sql, params).fetchall()
