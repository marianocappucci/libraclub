"""El servicio de reservas: alta, bloqueos, estados y series."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.enums import EstadoReserva, OrigenReserva
from app.models.reservas import Serie
from app.servicios import reservas as servicio
from app.tiempo import TZ


def _a_las(hora: int, minuto: int = 0, dia: date | None = None) -> datetime:
    dia = dia or date(2026, 9, 1)
    return datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=TZ)


def test_crea_y_congela_el_precio(sesion, cancha, cliente, tarifa_base):
    """El precio se guarda al crear, no se resuelve al leer.

    Si mañana sube la tarifa, el turno que ya se tomó tiene que seguir valiendo
    lo que se le dijo al cliente — que es lo que el cliente va a recordar.
    """
    reserva = servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_a_las(20)
    )
    sesion.commit()

    assert reserva.precio == Decimal("10000.00")
    assert reserva.sena == Decimal("5000.00")

    tarifa_base.precio = Decimal("99999.00")
    sesion.commit()
    sesion.refresh(reserva)
    assert reserva.precio == Decimal("10000.00")


def test_la_duracion_sale_de_la_cancha(sesion, cancha, cliente, tarifa_base):
    reserva = servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_a_las(20)
    )
    assert reserva.termina_at - reserva.comienza_at == timedelta(minutes=90)


def test_el_mensaje_de_superposicion_dice_el_horario(sesion, cancha, cliente, tarifa_base):
    """El chequeo previo existe para esto: un texto que el operador entienda.

    El constraint da la garantía; este camino da el mensaje. Sin él, el operador
    vería "violates exclusion constraint" y llamaría por teléfono.
    """
    servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_a_las(20)
    )
    sesion.commit()

    with pytest.raises(servicio.Superpuesta) as error:
        servicio.crear(
            sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_a_las(20, 30)
        )
    assert "20:00" in str(error.value) and "21:30" in str(error.value)


def test_un_bloqueo_impide_una_reserva_y_al_reves(sesion, cancha, cliente, tarifa_base):
    """Las dos direcciones, y por eso viven en la misma tabla.

    Con el bloqueo en una tabla propia, el constraint no lo vería y habría que
    volver a chequear en la aplicación — que es lo que este diseño evita.
    """
    servicio.crear_bloqueo(
        sesion,
        cancha_id=cancha.id,
        comienza_at=_a_las(18),
        termina_at=_a_las(20),
        motivo="Mantenimiento de la red",
    )
    sesion.commit()

    with pytest.raises(servicio.Superpuesta):
        servicio.crear(
            sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_a_las(19)
        )

    servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_a_las(20)
    )
    sesion.commit()
    with pytest.raises(servicio.Superpuesta):
        servicio.crear_bloqueo(
            sesion,
            cancha_id=cancha.id,
            comienza_at=_a_las(20, 30),
            termina_at=_a_las(22),
            motivo="Torneo",
        )


def test_un_bloqueo_sin_motivo_no_entra(sesion, cancha):
    with pytest.raises(servicio.ReservaInvalida):
        servicio.crear_bloqueo(
            sesion,
            cancha_id=cancha.id,
            comienza_at=_a_las(18),
            termina_at=_a_las(20),
            motivo="   ",
        )


def test_una_cancha_de_baja_no_recibe_reservas(sesion, cancha, cliente, tarifa_base):
    cancha.activa = False
    sesion.commit()
    with pytest.raises(servicio.ReservaInvalida):
        servicio.crear(
            sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_a_las(20)
        )


def test_no_se_puede_cancelar_una_reserva_jugada(sesion, cancha, cliente, tarifa_base):
    """Un turno ya jugado que se cancela descuadra el reporte del mes pasado."""
    reserva = servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_a_las(20)
    )
    sesion.commit()
    servicio.cambiar_estado(sesion, reserva.id, EstadoReserva.JUGADA)
    sesion.commit()

    with pytest.raises(servicio.TransicionInvalida):
        servicio.cambiar_estado(sesion, reserva.id, EstadoReserva.CANCELADA)


def test_la_provisoria_nace_con_vencimiento_y_se_vence(sesion, cancha, cliente, tarifa_base):
    """Y al vencerse **libera el turno**, que es para lo que existe."""
    reserva = servicio.crear(
        sesion,
        cancha_id=cancha.id,
        cliente_id=cliente.id,
        comienza_at=_a_las(20),
        estado=EstadoReserva.PROVISORIA,
    )
    sesion.commit()
    assert reserva.vence_at is not None

    # Se la vence "desde el futuro" en vez de esperar 15 minutos reales.
    cuantas = servicio.vencer_provisorias(
        sesion, reserva.vence_at + timedelta(seconds=1)
    )
    sesion.commit()
    assert cuantas == 1

    sesion.refresh(reserva)
    assert reserva.estado is EstadoReserva.CANCELADA

    # El control que hace que el test signifique algo: si no liberara, esto
    # levantaría `Superpuesta`.
    servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_a_las(20)
    )
    sesion.commit()


def test_una_provisoria_que_no_vencio_no_se_toca(sesion, cancha, cliente, tarifa_base):
    """Control negativo del barrido: sin él, un `UPDATE` sin `WHERE` daría el
    mismo verde que el test de arriba."""
    reserva = servicio.crear(
        sesion,
        cancha_id=cancha.id,
        cliente_id=cliente.id,
        comienza_at=_a_las(20),
        estado=EstadoReserva.PROVISORIA,
    )
    sesion.commit()
    assert servicio.vencer_provisorias(sesion, reserva.vence_at - timedelta(minutes=1)) == 0


def test_la_serie_saltea_la_fecha_ocupada_y_deja_las_demas(
    sesion, cancha, cliente, tarifa_base
):
    """🔑 El caso que justifica el SAVEPOINT.

    Sin savepoint, el `IntegrityError` del martes bloqueado abortaría la
    transacción y las siguientes fallarían también: el operador vería "no se pudo
    crear la serie" cuando se podían crear todas menos una.
    """
    tercer_martes = date(2026, 9, 15)
    servicio.crear_bloqueo(
        sesion,
        cancha_id=cancha.id,
        comienza_at=_a_las(20, dia=tercer_martes),
        termina_at=_a_las(22, dia=tercer_martes),
        motivo="Torneo interno",
    )
    sesion.commit()

    serie = Serie(
        cancha_id=cancha.id,
        cliente_id=cliente.id,
        dia_semana=1,
        hora=time(20, 0),
        duracion_min=90,
        desde=date(2026, 9, 1),
        hasta=date(2026, 9, 29),
    )
    sesion.add(serie)
    sesion.flush()

    creadas, salteadas = servicio.materializar_serie(sesion, serie)
    sesion.commit()

    # Cinco martes en septiembre de 2026: 1, 8, 15, 22, 29. El 15 está bloqueado.
    assert len(creadas) == 4
    assert len(salteadas) == 1
    # `Salteada` y no un `datetime` pelado desde el 2026-08-21: cada una dice
    # POR QUÉ, que es lo que la pantalla necesita para mandar al operador a la
    # pantalla correcta —Tarifas, Horario de atención o la grilla—.
    assert salteadas[0].comienza_at.date() == tercer_martes
    assert salteadas[0].motivo == "ocupada"

    # Y las cuatro quedaron **realmente** en la base: que el servicio devuelva
    # objetos no prueba que el commit las haya escrito.
    en_base = sesion.execute(
        text("SELECT count(*) FROM reservas WHERE serie_id = :s"), {"s": serie.id}
    ).scalar_one()
    assert en_base == 4


def test_la_serie_marca_su_origen(sesion, cancha, cliente, tarifa_base):
    """Para poder medir después cuántas reservas vienen de canchas fijas."""
    serie = Serie(
        cancha_id=cancha.id,
        cliente_id=cliente.id,
        dia_semana=1,
        hora=time(20, 0),
        duracion_min=90,
        desde=date(2026, 9, 1),
        hasta=date(2026, 9, 8),
    )
    sesion.add(serie)
    sesion.flush()
    creadas, _ = servicio.materializar_serie(sesion, serie)
    sesion.commit()

    assert creadas
    assert all(r.origen is OrigenReserva.SERIE for r in creadas)
    # 🔴 Y con la hora local correcta: `generate_occurrences` devuelve datetimes
    # **naive**, y guardarlos sin zona los correría tres horas.
    from app.tiempo import a_local

    assert all(a_local(r.comienza_at).hour == 20 for r in creadas)


def test_una_serie_sin_fin_se_materializa_hasta_el_horizonte(
    sesion, cancha, cliente, tarifa_base
):
    """Una cancha fija "hasta que avise" no puede ocupar la agenda del 2100."""
    serie = Serie(
        cancha_id=cancha.id,
        cliente_id=cliente.id,
        dia_semana=1,
        hora=time(20, 0),
        duracion_min=90,
        desde=date(2026, 9, 1),
        hasta=None,
    )
    sesion.add(serie)
    sesion.flush()
    creadas, _ = servicio.materializar_serie(sesion, serie, hasta=date(2026, 10, 31))
    sesion.commit()

    assert 1 <= len(creadas) <= 10
    assert max(r.comienza_at for r in creadas).date() <= date(2026, 10, 31)
