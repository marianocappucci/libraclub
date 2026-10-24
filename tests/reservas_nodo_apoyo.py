"""Lo que comparten los tests de las reservas en un nodo de LibraEdge (ADR-022).

Ninguno levanta el nodo real (ni el proceso `libraedge-nodo`, ni el transporte): se ejercitan las piezas con las
tablas de LibraEdge (`local_sequences`, `sync_outbox`, `libraedge_mapeo`) creadas sobre la base de la suite, que es
exactamente lo que ve el producto en un nodo.

🔑 **`libraedge` no es dependencia de este producto todavía** (la suma el PR 11, con la deploy key del CI): este módulo
no lo importa al cargarse. Los tests que lo necesitan (el aplicador del central y el outbox real) piden
`libraedge` con `pytest.importorskip` y se saltean —con su motivo en `-rs`— donde no está; el resto (la exclusión
partida, el servicio, las guardas y los endpoints de conflictos) corre en cualquier entorno.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from libracore.db import core as libracore_core

from app.servicios import reservas_nodo
from app.tiempo import TZ
from tests.conftest import url_del_core

NODO = "club-1"


def a_las(hora: int, minuto: int = 0, dia: date | None = None) -> datetime:
    dia = dia or date(2026, 9, 1)
    return datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=TZ)


def preparar_tablas_de_libraedge(sesion) -> None:
    """Crea en la base de la suite las tablas que LibraEdge pone en un nodo (y en el central, `libraedge_mapeo`)."""
    pytest.importorskip("libraedge", reason="libraedge todavía no es dependencia de LibraClub (lo suma el PR 11)")
    from libraedge.db.schema import init_schema
    from libraedge.mapeo import init_mapeo_schema

    conn = reservas_nodo.conexion_de_la_sesion(sesion)
    init_schema(conn)
    init_mapeo_schema(conn)
    sesion.commit()


@pytest.fixture
def nodo():
    """Esta instancia es el nodo `club-1`. `.en_linea` se cambia a mano; `.creadas` y `.estados` juntan lo que los
    ganchos recibieron (sin outbox real: ese camino lo miden los tests con `nodo_con_outbox`).

    El id provisorio sale de un contador que arranca en -1, como el de `libraedge.mapeo.siguiente_id_provisorio`: lo
    que se mide acá es el servicio, no la secuencia de LibraEdge."""
    estado = SimpleNamespace(en_linea=False, creadas=[], estados=[], ultimo_id=0)

    def id_provisorio(conn) -> int:
        estado.ultimo_id -= 1
        return estado.ultimo_id

    reservas_nodo.configurar(
        reservas_nodo.ReservasEnNodo(
            nodo=lambda: NODO,
            id_provisorio=id_provisorio,
            al_crear_reserva=lambda conn, datos: estado.creadas.append(datos),
            al_cambiar_estado=lambda conn, datos: estado.estados.append(datos),
            en_linea=lambda: estado.en_linea,
        )
    )
    yield estado
    reservas_nodo.configurar(None)


@pytest.fixture
def central(engine, sesion):
    """Una conexión del motor (la del receptor de LibraEdge en el central), con las tablas de LibraEdge creadas."""
    preparar_tablas_de_libraedge(sesion)
    conn = libracore_core.conectar(url_del_core())
    yield conn
    conn.rollback()
    conn.close()


def operacion(tipo: str, payload: dict, *, node_id: str = NODO, secuencia: int = 1, schema_version: int = 1):
    """La `OutboxOperation` que el central recibe del nodo."""
    from libraedge.domain.sync import OutboxOperation

    return OutboxOperation(
        operation_id=f"{node_id}:{secuencia}", node_id=node_id, sequence=secuencia, operation_type=tipo,
        aggregate_type="reserva", aggregate_id=f"{node_id}:reserva:{payload.get('reserva_id')}",
        occurred_at="2026-09-01T10:00:00+00:00", schema_version=schema_version, payload=payload,
    )


def payload_creada(cancha_id: int, cliente_id: int, *, reserva_id: int = -1, desde: datetime | None = None,
                   hasta: datetime | None = None, **resto) -> dict:
    desde = desde or a_las(20)
    hasta = hasta or a_las(21, 30)
    return {
        "version": 1, "reserva_id": reserva_id, "cancha_id": cancha_id, "cliente_id": cliente_id,
        "estado": "confirmada", "origen": "mostrador", "comienza_at": desde.isoformat(),
        "termina_at": hasta.isoformat(), "precio": "10000.00", "sena": "5000.00", "observaciones": None,
        "creada_at": "2026-09-01T10:00:00+00:00", **resto,
    }


def payload_estado(reserva_id: int, estado: str, motivo: str | None = None) -> dict:
    return {"version": 1, "reserva_id": reserva_id, "estado": estado, "motivo": motivo}


def aplicar(conn, tipo: str, payload: dict, **kw) -> None:
    """Aplica una operación como el receptor: en la transacción de `conn`, que se confirma al final."""
    aplicador = reservas_nodo.aplicadores()[tipo]
    aplicador(conn, operacion(tipo, payload, **kw))
    conn.commit()
