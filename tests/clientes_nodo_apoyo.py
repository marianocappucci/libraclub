"""Lo que comparten los tests de los clientes que se dan de alta en un nodo de LibraEdge (ADR-022, addendum).

Igual que `reservas_nodo_apoyo`: ninguno levanta el nodo real, se ejercitan las piezas con las tablas de LibraEdge
(`local_sequences`, `sync_outbox`, `libraedge_mapeo`) creadas sobre la base de la suite.

🔑 `libraedge` no es dependencia de este producto todavía (la suma el PR 11): este módulo no lo importa al cargarse.
Los tests que lo necesitan se saltean donde no está; el resto (la guarda, el id provisorio y el encolado con un doble)
corre en cualquier entorno.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.servicios import clientes_nodo
from tests.reservas_nodo_apoyo import NODO

__all__ = ["NODO", "alta", "nodo_clientes", "operacion_alta"]


@pytest.fixture
def nodo_clientes():
    """Esta instancia es el nodo `club-1`. `.en_linea` se cambia a mano; `.altas` junta lo que el gancho recibió (sin
    outbox real: ese camino lo miden los tests con `nodo_clientes_con_outbox`). El id provisorio sale de un contador
    que arranca en -1, como el de `libraedge.mapeo.siguiente_id_provisorio`."""
    estado = SimpleNamespace(en_linea=False, altas=[], ultimo_id=0)

    def id_provisorio(conn) -> int:
        estado.ultimo_id -= 1
        return estado.ultimo_id

    clientes_nodo.configurar(
        clientes_nodo.ClientesEnNodo(
            nodo=lambda: NODO,
            id_provisorio=id_provisorio,
            al_crear_cliente=lambda conn, datos: estado.altas.append(datos),
            en_linea=lambda: estado.en_linea,
        )
    )
    yield estado
    clientes_nodo.configurar(None)


def alta(cliente_id: int = -1, nombre: str = "Juan Pérez", **resto) -> dict:
    """El payload de `cliente_club.alta` como lo arma el nodo."""
    return {
        "version": 1, "cliente_id": cliente_id, "nombre": nombre, "telefono": None, "email": None, "documento": None,
        "cuit": None, "activo": True, "acepta_avisos": True, "observaciones": None,
        "creada_at": "2026-09-01T10:00:00+00:00", **resto,
    }


def operacion_alta(payload: dict, *, node_id: str = NODO, secuencia: int = 1, schema_version: int = 1,
                   tipo: str = clientes_nodo.TIPO_CLIENTE_ALTA):
    """La `OutboxOperation` que el central recibe del nodo."""
    from libraedge.domain.sync import OutboxOperation

    return OutboxOperation(
        operation_id=f"{node_id}:{secuencia}", node_id=node_id, sequence=secuencia, operation_type=tipo,
        aggregate_type=clientes_nodo.AGREGADO_CLIENTE,
        aggregate_id=f"{node_id}:{clientes_nodo.AGREGADO_CLIENTE}:{payload.get('cliente_id')}",
        occurred_at="2026-09-01T10:00:00+00:00", schema_version=schema_version, payload=payload,
    )
