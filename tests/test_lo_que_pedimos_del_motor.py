"""Lo que este producto necesita del motor, medido sobre el motor INSTALADO.

🔴 **Un pin no se verifica leyendo el pin.** Que `pyproject.toml` diga
`libracore.git@v1.57.1` prueba lo que yo escribi, no lo que la instancia va a
correr: el venv puede estar atras, el CI puede resolver otra cosa, y una bajada
de version en un merge no rompe nada visible. Lo unico que ata este producto a
la conducta que necesita es un test que **ejercite el motor de verdad**.

Lo que se mide aca es el relleno de `caja_id` de v1.57.1. LibraClub lo necesita
porque su pantalla de Caja muestra el mostrador del turno, y sin relleno los
turnos anteriores al 2026-08-28 salen con *"sin caja asignada"* --- que es
exactamente lo que el humano reporto ese dia.
"""

from __future__ import annotations

import sqlite3

import pytest
from libracore.db.schema import init_core_schema


@pytest.fixture
def core(tmp_path):
    """Una base de LibraCore de juguete, en SQLite.

    ⚠️ SQLite y no PostgreSQL **a proposito**, y es la excepcion que el contrato
    admite: esto no es la base de un producto sino un calculo descartable para
    mirar como se comporta `init_core_schema`. Es el mismo criterio que
    `libradesk/app/schema.py`, que corre la baseline en memoria para averiguar la
    forma del schema.
    """
    conn = sqlite3.connect(str(tmp_path / "core.db"))
    conn.row_factory = sqlite3.Row
    init_core_schema(conn)
    conn.commit()
    yield conn
    conn.close()


def test_el_motor_rellena_la_caja_de_un_turno_viejo(core):
    """El guard del pin: si el motor baja de v1.57.1, esto se pone rojo.

    Sin el relleno, la pantalla de Caja dice *"sin caja asignada"* sobre los
    turnos que ya estaban --- que es el reporte que lo motivo.
    """
    core.execute(
        "INSERT INTO usuarios (username, nombre, password_hash, role)"
        " VALUES ('ana', 'Ana', 'x', 'admin')"
    )
    core.execute(
        "INSERT INTO turnos_caja (usuario_id, apertura, monto_inicial, estado, caja_id)"
        " VALUES (1, '2026-08-21 22:16:21', 1000, 'abierto', NULL)"
    )
    core.commit()

    # El control: **antes** esta en NULL. Sin esto, un INSERT que ya trajera la
    # caja haria pasar el test sin que el motor rellene nada.
    assert core.execute(
        "SELECT caja_id FROM turnos_caja"
    ).fetchone()[0] is None

    init_core_schema(core)
    core.commit()

    caja_id = core.execute("SELECT caja_id FROM turnos_caja").fetchone()[0]
    assert caja_id is not None, (
        "el motor instalado no rellena `caja_id`: el pin de libracore quedo "
        "atras de v1.57.1, y la Caja va a mostrar «sin caja asignada»"
    )
    por_defecto = core.execute(
        "SELECT id FROM cajas WHERE es_default=1 LIMIT 1"
    ).fetchone()[0]
    assert caja_id == por_defecto
