"""Que el schema real diga lo que el código cree que dice."""

from __future__ import annotations

import re

from sqlalchemy import text

from app.models.enums import ESTADOS_QUE_OCUPAN, EstadoReserva


def test_la_extension_btree_gist_existe(engine):
    """Sin ella el constraint de exclusión no se puede ni crear.

    Se chequea aparte del constraint porque el modo de falla es distinto: la
    extensión la crea la migración, y una base restaurada desde un dump viejo
    puede tener las tablas y no tenerla.
    """
    with engine.connect() as conexion:
        cuantas = conexion.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'")
        ).scalar_one()
    assert cuantas == 1


def test_constraint_coincide_con_el_enum(engine):
    """🔑 La lista del constraint y la del código no pueden divergir.

    La migración escribe los estados **literales** —es un registro histórico— y
    la aplicación los deriva de `ESTADOS_QUE_OCUPAN`. Este test es el único que
    ata las dos: alguien que agregue un estado que ocupa la cancha y se olvide de
    la migración lo ve acá, y no el día que una cancha se reserva dos veces.
    """
    with engine.connect() as conexion:
        definicion = conexion.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ex_reservas_sin_superposicion'"
            )
        ).scalar_one()

    # Los valores que PostgreSQL imprime en el WHERE, con o sin el cast
    # `::estado_reserva` que agrega al normalizar la expresión.
    en_la_base = set(re.findall(r"'([a-z_]+)'::estado_reserva|'([a-z_]+)'", definicion))
    encontrados = {a or b for a, b in en_la_base}
    esperados = {estado.value for estado in ESTADOS_QUE_OCUPAN}

    assert encontrados == esperados, (
        f"el constraint cubre {sorted(encontrados)} y el enum dice "
        f"{sorted(esperados)}: uno de los dos quedó atrás"
    )


def test_todos_los_estados_estan_clasificados():
    """Ningún estado nuevo queda sin decidir de qué lado del predicado cae.

    Sin este test, agregar un valor a `EstadoReserva` y olvidarse de
    `ESTADOS_QUE_OCUPAN` no rompe nada visible: la reserva simplemente no ocupa
    la cancha, y la cancha se reserva dos veces.
    """
    ocupan = set(ESTADOS_QUE_OCUPAN)
    liberan = {EstadoReserva.CANCELADA, EstadoReserva.AUSENTE}
    assert ocupan | liberan == set(EstadoReserva), (
        "hay estados sin clasificar: "
        f"{sorted(e.value for e in set(EstadoReserva) - ocupan - liberan)}"
    )
    assert not (ocupan & liberan)


def test_periodo_es_columna_generada(engine):
    """Si dejara de ser generada, se podría insertar una fila fuera del constraint.

    Una `periodo` común que un `INSERT` no llene queda en NULL, y un NULL no
    solapa con nada: la fila sería invisible para la exclusión y perfectamente
    insertable encima de otra reserva.
    """
    with engine.connect() as conexion:
        generada = conexion.execute(
            text(
                "SELECT is_generated FROM information_schema.columns "
                "WHERE table_name = 'reservas' AND column_name = 'periodo'"
            )
        ).scalar_one()
    assert generada == "ALWAYS"
