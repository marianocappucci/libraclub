"""El gate de F1: **cero doble reserva en concurrencia**.

Este archivo es la razón por la que las reservas viven en una tabla propia y no
en las de LibraGenda (DECISIONS.md ADR-004). Si estos tests se ponen en verde
por el motivo equivocado, el producto pierde lo único que lo distingue.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.enums import EstadoReserva, OrigenReserva
from app.models.reservas import Reserva
from app.tiempo import TZ

CONSTRAINT = "ex_reservas_sin_superposicion"

#: La definición, **igual que en la migración**. Se repite acá porque el test que
#: la saca tiene que poder reponerla exactamente; si divergieran, la suite
#: seguiría después con un constraint distinto del que hay en producción.
DEFINICION = (
    "EXCLUDE USING gist (cancha_id WITH =, periodo WITH &&) "
    "WHERE (estado IN ('provisoria', 'pendiente_pago', 'confirmada', "
    "'jugada', 'bloqueo'))"
)

#: Tope para el DDL. Un `ALTER TABLE` que pide ACCESS EXCLUSIVE y no lo consigue
#: espera **para siempre** por defecto: la suite se cuelga en vez de fallar, y un
#: CI colgado no dice qué pasó. Con el timeout, el mismo problema sale como rojo
#: con un mensaje de lock.
LOCK_TIMEOUT = "SET lock_timeout = '15s'"


def _sin_constraint(engine) -> None:
    with engine.begin() as conexion:
        conexion.execute(text(LOCK_TIMEOUT))
        conexion.execute(text(f"ALTER TABLE reservas DROP CONSTRAINT {CONSTRAINT}"))


def _con_constraint(engine) -> None:
    with engine.begin() as conexion:
        conexion.execute(text(LOCK_TIMEOUT))
        conexion.execute(text("DELETE FROM reservas"))
        conexion.execute(
            text(f"ALTER TABLE reservas ADD CONSTRAINT {CONSTRAINT} {DEFINICION}")
        )


def _reserva(cancha_id: int, cliente_id: int, momento: datetime) -> Reserva:
    return Reserva(
        cancha_id=cancha_id,
        cliente_id=cliente_id,
        estado=EstadoReserva.CONFIRMADA,
        origen=OrigenReserva.MOSTRADOR,
        comienza_at=momento,
        termina_at=momento + timedelta(minutes=90),
    )


def _pelear(engine, cancha_id, cliente_id, momento) -> list[str]:
    """Dos hilos insertando el mismo turno a la vez. Devuelve qué pasó en cada uno.

    La `Barrier` es lo que hace que sean **simultáneos de verdad**: sin ella, el
    primer hilo suele terminar antes de que el segundo arranque y el test mide el
    caso secuencial, que el constraint también rechaza pero que no prueba nada
    sobre concurrencia.

    El segundo hilo **se bloquea** dentro del `INSERT` —PostgreSQL toma un lock
    de exclusión— hasta que el primero commitea, y recién ahí falla. Eso es
    exactamente lo que un chequeo read-then-write en la aplicación no puede
    hacer: los dos leerían "está libre" y los dos escribirían.
    """
    fabrica = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    barrera = threading.Barrier(2, timeout=10)
    resultados: list[str] = []
    candado = threading.Lock()

    def intentar() -> None:
        with fabrica() as sesion:
            reserva = _reserva(cancha_id, cliente_id, momento)
            sesion.add(reserva)
            barrera.wait()
            try:
                sesion.commit()
            except IntegrityError as exc:
                sesion.rollback()
                diag = getattr(getattr(exc, "orig", None), "diag", None)
                nombre = getattr(diag, "constraint_name", None)
                with candado:
                    resultados.append(f"choque:{nombre}")
            else:
                with candado:
                    resultados.append("ok")

    hilos = [threading.Thread(target=intentar) for _ in range(2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        # Con timeout: si el constraint dejara a los dos esperándose, un `join()`
        # sin tope colgaría la suite entera en vez de dar rojo.
        hilo.join(timeout=30)
        assert not hilo.is_alive(), "un hilo quedó colgado esperando el lock"
    return resultados


def test_dos_reservas_simultaneas_solo_una_gana(engine, sesion, cancha, cliente):
    """El gate. Dos personas tomando el turno de las 20:00 al mismo tiempo."""
    momento = datetime(2026, 9, 1, 20, 0, tzinfo=TZ)
    resultados = _pelear(engine, cancha.id, cliente.id, momento)

    assert sorted(resultados) == ["choque:" + CONSTRAINT, "ok"], (
        f"esperaba un éxito y un choque del constraint, salió {resultados}"
    )

    # Y que quede **una sola fila**: que el segundo haya recibido un error no
    # prueba por sí solo que no haya escrito nada.
    cuantas = sesion.execute(
        text("SELECT count(*) FROM reservas WHERE cancha_id = :c"), {"c": cancha.id}
    ).scalar_one()
    assert cuantas == 1


def test_control_positivo_sin_el_constraint_entran_las_dos(engine, sesion, cancha, cliente):
    """🔑 El control que hace que el test de arriba signifique algo.

    Sin esto, `test_dos_reservas_simultaneas_solo_una_gana` podría estar en verde
    porque los dos hilos nunca corrieron juntos, porque la fixture no creó la
    cancha, o porque el `INSERT` falla por cualquier otra razón. Acá se **saca**
    el constraint y se comprueba que entonces sí entran las dos: eso demuestra
    que el camino se ejercita de verdad y que lo que lo impide es el constraint,
    no un accidente del arnés.

    El constraint se repone en el `finally` **y con la misma definición literal
    que la migración**: dejar la base sin él contaminaría los tests siguientes,
    que darían verde sin garantía.
    """
    momento = datetime(2026, 9, 1, 21, 30, tzinfo=TZ)
    _sin_constraint(engine)
    try:
        resultados = _pelear(engine, cancha.id, cliente.id, momento)
        assert resultados == ["ok", "ok"], (
            "sin el constraint las dos tienen que entrar; si no, el test de "
            f"concurrencia no está midiendo el constraint. Salió {resultados}"
        )
        cuantas = sesion.execute(
            text("SELECT count(*) FROM reservas WHERE cancha_id = :c"), {"c": cancha.id}
        ).scalar_one()
        assert cuantas == 2
    finally:
        # 🔴 **Primero soltar los locks de la sesión del test, después el DDL.**
        # El `SELECT count(*)` de arriba deja la sesión `idle in transaction` con
        # un ACCESS SHARE sobre `reservas`, y el `ADD CONSTRAINT` necesita ACCESS
        # EXCLUSIVE: sin este rollback los dos se esperan para siempre y **la
        # suite se cuelga sin dar rojo**, que es peor que fallar. Medido el
        # 2026-08-20: pytest quedó siete minutos trabado acá.
        sesion.rollback()
        _con_constraint(engine)


def test_el_constraint_vuelve_a_estar(engine):
    """Que el `finally` de arriba haya repuesto el constraint de verdad.

    Un test que rompe el schema y lo arregla en un `finally` es exactamente donde
    conviene no confiar: si el `ALTER` de reposición fallara, todos los tests que
    corran después darían verde sin la garantía y nadie lo notaría.
    """
    presente = engine.connect().execute(
        text(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conname = :nombre AND contype = 'x'"
        ),
        {"nombre": CONSTRAINT},
    ).scalar_one()
    assert presente == 1


@pytest.mark.parametrize(
    "offset_min, choca",
    [
        (0, True),      # el mismo turno
        (45, True),     # arranca en la mitad del anterior
        (89, True),     # un minuto de solape
        (90, False),    # arranca justo cuando termina: turnos encadenados
        (180, False),   # dos turnos después
    ],
)
def test_bordes_del_intervalo(sesion, cancha, cliente, offset_min, choca):
    """El intervalo es semiabierto `[)`: 20:00-21:30 y 21:30-23:00 conviven.

    Es el caso de uso normal —dos turnos seguidos en la misma cancha— y con un
    intervalo cerrado `[]` compartirían el instante del borde y el segundo sería
    imposible de cargar.
    """
    base = datetime(2026, 9, 1, 20, 0, tzinfo=TZ)
    sesion.add(_reserva(cancha.id, cliente.id, base))
    sesion.commit()

    sesion.add(_reserva(cancha.id, cliente.id, base + timedelta(minutes=offset_min)))
    if choca:
        with pytest.raises(IntegrityError):
            sesion.commit()
        sesion.rollback()
    else:
        sesion.commit()


def test_una_cancelada_libera_el_turno(sesion, cancha, cliente):
    """Cancelar libera porque el estado **sale del predicado del índice**.

    No porque alguien borre la fila: la reserva cancelada se conserva, y es lo
    que después permite contar cancelaciones y no-shows.
    """
    momento = datetime(2026, 9, 1, 20, 0, tzinfo=TZ)
    primera = _reserva(cancha.id, cliente.id, momento)
    sesion.add(primera)
    sesion.commit()

    primera.estado = EstadoReserva.CANCELADA
    sesion.commit()

    sesion.add(_reserva(cancha.id, cliente.id, momento))
    sesion.commit()  # no levanta: el turno quedó libre

    total = sesion.execute(text("SELECT count(*) FROM reservas")).scalar_one()
    assert total == 2, "la cancelada tiene que seguir existiendo, no borrarse"
