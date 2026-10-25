"""Lo que comparten los tests de los clientes que se dan de alta en un nodo de LibraEdge (ADR-022, addendum).

Igual que `reservas_nodo_apoyo`: ninguno levanta el nodo real, se ejercitan las piezas con las tablas de LibraEdge
(`local_sequences`, `sync_outbox`, `libraedge_mapeo`) creadas sobre la base de la suite.

`libraedge` es dependencia desde el PR 11 (ADR-023): este módulo igual lo importa recién al armar una operación.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.servicios import clientes_nodo
from tests.reservas_nodo_apoyo import NODO

__all__ = ["NODO", "alta", "edicion", "nodo_clientes", "operacion_alta", "operacion_edicion"]


@pytest.fixture
def nodo_clientes():
    """Esta instancia es el nodo `club-1`. `.en_linea` se cambia a mano; `.altas` junta lo que el gancho recibió (sin
    outbox real: ese camino lo miden los tests con `nodo_con_outbox`); `.ediciones`,
    lo mismo para `cliente_club.edicion`. El id provisorio sale de un contador
    que arranca en -1, como el de `libraedge.mapeo.siguiente_id_provisorio`."""
    estado = SimpleNamespace(en_linea=False, altas=[], ediciones=[], ultimo_id=0)

    def id_provisorio(conn) -> int:
        estado.ultimo_id -= 1
        return estado.ultimo_id

    clientes_nodo.configurar(
        clientes_nodo.ClientesEnNodo(
            nodo=lambda: NODO,
            id_provisorio=id_provisorio,
            al_crear_cliente=lambda conn, datos: estado.altas.append(datos),
            en_linea=lambda: estado.en_linea,
            al_editar_cliente=lambda conn, datos: estado.ediciones.append(datos),
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


def edicion(cliente_id: int = -1, *, antes: dict, despues: dict, **resto) -> dict:
    """El payload de `cliente_club.edicion` como lo arma el nodo: sólo los campos que cambiaron."""
    return {
        "version": 1, "cliente_id": cliente_id, "antes": antes, "despues": despues,
        "editada_at": "2026-09-02T10:00:00+00:00", **resto,
    }


def operacion_edicion(payload: dict, *, node_id: str = NODO, secuencia: int = 2, schema_version: int = 1,
                      tipo: str = clientes_nodo.TIPO_CLIENTE_EDICION):
    """La `OutboxOperation` de `cliente_club.edicion` que el central recibe del nodo (por defecto, la que sigue al
    alta)."""
    return operacion_alta(
        payload, node_id=node_id, secuencia=secuencia, schema_version=schema_version,
        tipo=tipo,
    )
