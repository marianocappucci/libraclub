"""La exclusión de `reservas` partida por el signo del id (migración `0013`, ADR-022).

Una reserva que se da en un nodo sin conexión nace con un id negativo. La base del nodo tiene, además, lo que el
espejo trae del central, y eso puede ocupar la misma cancha a la misma hora: con una sola exclusión el espejo no
podría insertarlo y se trabaría la sincronización. Partida: el central (`id > 0`) se excluye entre sí como siempre,
lo del nodo (`id < 0`) se excluye entre sí, y lo que cruza los dos lados lo resuelve el central al recibir la
operación (`test_reservas_aplicador_central.py`).
"""

from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import RAIZ
from tests.reservas_nodo_apoyo import a_las


def _insertar(sesion, *, id_, cancha, cliente, desde, hasta, estado="confirmada") -> None:
    """Un `INSERT` directo, con el id que se quiera: es la base la que se mide, no el servicio."""
    sesion.execute(
        text(
            "INSERT INTO reservas (id, cancha_id, cliente_id, estado, origen, comienza_at, termina_at) "
            "VALUES (:id, :cancha, :cliente, CAST(:estado AS estado_reserva), 'mostrador', :desde, :hasta)"
        ),
        {"id": id_, "cancha": cancha.id, "cliente": cliente.id, "estado": estado, "desde": desde, "hasta": hasta},
    )


def _constraint_violada(exc: IntegrityError) -> str:
    return exc.orig.diag.constraint_name


def test_dos_reservas_del_central_siguen_chocando(sesion, cancha, cliente):
    """Lo de siempre, con el nombre de siempre: la garantía central del producto no se tocó."""
    _insertar(sesion, id_=1, cancha=cancha, cliente=cliente, desde=a_las(20), hasta=a_las(21, 30))
    with pytest.raises(IntegrityError) as error:
        _insertar(sesion, id_=2, cancha=cancha, cliente=cliente, desde=a_las(21), hasta=a_las(22, 30))
    assert _constraint_violada(error.value) == "ex_reservas_sin_superposicion"


def test_una_provisoria_superpuesta_con_una_del_espejo_entra_en_el_nodo(sesion, cancha, cliente):
    """🔑 Lo que la partición vuelve posible: en la base del nodo conviven la que bajó del central y la que se dio
    sin conexión en el mismo horario. Sin la partición, el segundo `INSERT` era una violación de la exclusión."""
    _insertar(sesion, id_=57, cancha=cancha, cliente=cliente, desde=a_las(20), hasta=a_las(21, 30))
    _insertar(sesion, id_=-3, cancha=cancha, cliente=cliente, desde=a_las(20), hasta=a_las(21, 30))
    sesion.commit()

    ids = sesion.execute(text("SELECT id FROM reservas ORDER BY id")).scalars().all()
    assert ids == [-3, 57]


def test_la_que_baja_del_espejo_tampoco_se_traba_con_una_provisoria(sesion, cancha, cliente):
    """El otro orden: la provisoria ya estaba y es el espejo el que llega después. Es el caso que trababa el ciclo."""
    _insertar(sesion, id_=-1, cancha=cancha, cliente=cliente, desde=a_las(20), hasta=a_las(21, 30))
    _insertar(sesion, id_=9, cancha=cancha, cliente=cliente, desde=a_las(20, 30), hasta=a_las(22))
    sesion.commit()


def test_dos_provisorias_del_nodo_chocan_entre_si(sesion, cancha, cliente):
    """El club sin conexión tampoco puede dar dos veces la misma cancha: la partición no deja ese lado sin garantía."""
    _insertar(sesion, id_=-1, cancha=cancha, cliente=cliente, desde=a_las(20), hasta=a_las(21, 30))
    with pytest.raises(IntegrityError) as error:
        _insertar(sesion, id_=-2, cancha=cancha, cliente=cliente, desde=a_las(21), hasta=a_las(22, 30))
    assert _constraint_violada(error.value) == "ex_reservas_del_nodo_sin_superposicion"


def test_los_turnos_seguidos_siguen_sin_chocar_de_los_dos_lados(sesion, cancha, cliente):
    """El intervalo sigue siendo semiabierto: un turno que termina cuando empieza el otro no se pisa."""
    _insertar(sesion, id_=-1, cancha=cancha, cliente=cliente, desde=a_las(20), hasta=a_las(21, 30))
    _insertar(sesion, id_=-2, cancha=cancha, cliente=cliente, desde=a_las(21, 30), hasta=a_las(23))
    _insertar(sesion, id_=1, cancha=cancha, cliente=cliente, desde=a_las(20), hasta=a_las(21, 30))
    _insertar(sesion, id_=2, cancha=cancha, cliente=cliente, desde=a_las(21, 30), hasta=a_las(23))
    sesion.commit()


def test_una_reserva_en_conflicto_no_ocupa_la_cancha(sesion, cancha, cliente):
    """`en_conflicto` no está en el `WHERE` de ninguna de las dos: se guarda aunque la cancha esté tomada, y no impide
    que otra la tome. Es lo que le permite al central quedarse con la reserva que perdió sin bloquear nada."""
    _insertar(sesion, id_=1, cancha=cancha, cliente=cliente, desde=a_las(20), hasta=a_las(21, 30))
    _insertar(
        sesion, id_=2, cancha=cancha, cliente=cliente, desde=a_las(20), hasta=a_las(21, 30), estado="en_conflicto"
    )
    _insertar(
        sesion, id_=3, cancha=cancha, cliente=cliente, desde=a_las(20), hasta=a_las(21, 30), estado="en_conflicto"
    )
    sesion.commit()


# ── La migración se puede deshacer y rehacer ─────────────────────────────────


def _alembic() -> AlembicConfig:
    """La configuración de Alembic; la URL la lee `env.py` de `DATABASE_URL` (el test la fija con `monkeypatch`)."""
    cfg = AlembicConfig(os.path.join(RAIZ, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(RAIZ, "migrations"))
    return cfg


def _exclusiones(motor) -> set[str]:
    with motor.connect() as conexion:
        return set(
            conexion.execute(
                text("SELECT conname FROM pg_constraint WHERE conrelid = 'reservas'::regclass AND contype = 'x'")
            ).scalars()
        )


def _columnas(motor) -> set[str]:
    with motor.connect() as conexion:
        return set(
            conexion.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'reservas'")
            ).scalars()
        )


def test_la_migracion_0013_es_reversible(base_temporal, monkeypatch):
    """Subir, bajar a la `0012` y volver a subir deja el esquema como corresponde en cada punto.

    Sobre una base propia: la del worker la dan por armada los demás tests."""
    url = base_temporal("mig0013")
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _alembic()
    motor = create_engine(url, future=True)
    try:
        command.upgrade(cfg, "head")
        assert _exclusiones(motor) == {"ex_reservas_sin_superposicion", "ex_reservas_del_nodo_sin_superposicion"}
        assert {"conflicto_con_id", "estado_previo"} <= _columnas(motor)

        command.downgrade(cfg, "0012_actividad_log")
        assert _exclusiones(motor) == {"ex_reservas_sin_superposicion"}
        assert not ({"conflicto_con_id", "estado_previo"} & _columnas(motor))
        with motor.connect() as conexion:
            definicion = conexion.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ex_reservas_sin_superposicion'"
                )
            ).scalar_one()
        assert "id >" not in definicion, "al volver a la 0012 la exclusión es la única de siempre"

        command.upgrade(cfg, "head")
        assert _exclusiones(motor) == {"ex_reservas_sin_superposicion", "ex_reservas_del_nodo_sin_superposicion"}
    finally:
        motor.dispose()


def test_la_migracion_0013_no_baja_si_hay_reservas_de_un_nodo(base_temporal, monkeypatch):
    """Bajar con una reserva de id negativo perdería una reserva que todavía no subió: se niega y lo dice."""
    url = base_temporal("mig0013b")
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _alembic()
    motor = create_engine(url, future=True)
    try:
        command.upgrade(cfg, "head")
        with motor.begin() as conexion:
            conexion.execute(text("INSERT INTO sucursales (nombre, punto_venta_arca) VALUES ('S', 1)"))
            conexion.execute(text(
                "INSERT INTO canchas (sucursal_id, nombre, deporte, duracion_turno_min) "
                "VALUES (1, 'C', 'padel', 90)"
            ))
            conexion.execute(text("INSERT INTO clientes (nombre, acepta_avisos) VALUES ('J', true)"))
            conexion.execute(text(
                "INSERT INTO reservas (id, cancha_id, cliente_id, estado, origen, comienza_at, termina_at) "
                "VALUES (-1, 1, 1, 'confirmada', 'mostrador', '2026-09-01 20:00-03', '2026-09-01 21:30-03')"
            ))
        with pytest.raises(RuntimeError, match="id provisorio"):
            command.downgrade(cfg, "0012_actividad_log")
        assert _exclusiones(motor) == {"ex_reservas_sin_superposicion", "ex_reservas_del_nodo_sin_superposicion"}
    finally:
        motor.dispose()
