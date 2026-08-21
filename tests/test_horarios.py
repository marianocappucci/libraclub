"""El horario de atención: qué turnos existen y cuáles no se pueden vender.

Antes de esto el horario era `APERTURA = time(8, 0)` hardcodeado, igual para
toda cancha, sucursal y día, y el alta no validaba nada. Lo que se fija acá:

- que la grilla salga de las franjas configuradas, y no de una constante;
- que un complejo pueda abrir dos veces en el mismo día (mañana y tarde);
- que cerrar a las 02:00 —lo normal en pádel— funcione;
- que una reserva fuera de horario **no entre por la API**, no sólo que la
  pantalla no la ofrezca;
- que achicar el horario **no esconda** las reservas que ya estaban vendidas.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from app.models.enums import AlcanceDia, EstadoReserva
from app.models.maestros import Feriado, FranjaDeAtencion
from app.servicios import disponibilidad, horarios
from app.servicios import reservas as servicio
from app.tiempo import TZ

#: Un lunes cualquiera, lejos de cualquier feriado sembrado.
LUNES = date(2026, 9, 7)


def _franja(sesion, sucursal, abre, cierra, *, cancha=None, alcance=AlcanceDia.TODOS,
            dia_semana=None):
    f = FranjaDeAtencion(
        sucursal_id=sucursal.id,
        cancha_id=cancha.id if cancha else None,
        alcance_dia=alcance,
        dia_semana=dia_semana,
        abre=abre,
        cierra=cierra,
    )
    sesion.add(f)
    sesion.commit()
    return f


def _en(dia: date, hora: time) -> datetime:
    return datetime.combine(dia, hora, tzinfo=TZ)


@pytest.fixture
def feriado(sesion, sucursal) -> Feriado:
    """Un feriado que NO cierra: abre, con otro horario y otra tarifa."""
    item = Feriado(
        sucursal_id=sucursal.id, dia=date(2026, 9, 21), nombre="Día del Estudiante"
    )
    sesion.add(item)
    sesion.commit()
    return item


@pytest.fixture
def feriado_cerrado(sesion, sucursal) -> Feriado:
    item = Feriado(
        sucursal_id=sucursal.id, dia=date(2026, 12, 25), nombre="Navidad", cerrado=True
    )
    sesion.add(item)
    sesion.commit()
    return item


# ── Resolución de franjas ────────────────────────────────────────────────


def test_sin_franjas_rige_el_horario_por_defecto(sesion, cancha):
    """🔴 El piso que hace que desplegar esto no rompa nada.

    Una instancia que ya venía trabajando no tiene ninguna franja cargada. Sin
    este default se quedaría con la agenda vacía y sin un cartel que lo
    explique — el peor resultado posible de agregar una feature.
    """
    assert horarios.franjas_del_dia(sesion, cancha, LUNES) == [
        (_en(LUNES, time(8, 0)), _en(LUNES + timedelta(days=1), time(0, 0)))
    ]


def test_una_franja_cargada_reemplaza_al_default(sesion, cancha, sucursal):
    _franja(sesion, sucursal, time(16, 0), time(23, 0))
    assert horarios.franjas_del_dia(sesion, cancha, LUNES) == [
        (_en(LUNES, time(16, 0)), _en(LUNES, time(23, 0)))
    ]


def test_el_complejo_que_cierra_al_mediodia_tiene_DOS_franjas(sesion, cancha, sucursal):
    """🔑 El motivo por el que no gana una sola franja como en el tarifario.

    Una tarifa resuelve un precio (valor único); un horario resuelve un conjunto.
    Quedarse con la primera borraría el turno de la tarde sin que nada avise.
    """
    _franja(sesion, sucursal, time(9, 0), time(13, 0))
    _franja(sesion, sucursal, time(16, 0), time(23, 0))
    assert horarios.franjas_del_dia(sesion, cancha, LUNES) == [
        (_en(LUNES, time(9, 0)), _en(LUNES, time(13, 0))),
        (_en(LUNES, time(16, 0)), _en(LUNES, time(23, 0))),
    ]


def test_cerrar_a_las_dos_de_la_manana_corre_el_fin_al_dia_siguiente(
    sesion, cancha, sucursal
):
    """En pádel es la mayoría: se abre a las 16 y se cierra a las 02."""
    _franja(sesion, sucursal, time(16, 0), time(2, 0))
    assert horarios.franjas_del_dia(sesion, cancha, LUNES) == [
        (_en(LUNES, time(16, 0)), _en(LUNES + timedelta(days=1), time(2, 0)))
    ]


def test_abre_igual_a_cierra_son_veinticuatro_horas(sesion, cancha, sucursal):
    """El caso borde sale del mismo cálculo, sin rama especial."""
    _franja(sesion, sucursal, time(0, 0), time(0, 0))
    (inicio, fin), = horarios.franjas_del_dia(sesion, cancha, LUNES)
    assert fin - inicio == timedelta(hours=24)


def test_el_horario_de_la_cancha_reemplaza_al_de_la_sucursal(sesion, cancha, sucursal):
    """La cancha con luces cierra más tarde. Y **no se suman**: si se sumaran,
    esa cancha abriría en las dos ventanas a la vez."""
    _franja(sesion, sucursal, time(9, 0), time(22, 0))
    _franja(sesion, sucursal, time(9, 0), time(2, 0), cancha=cancha)
    assert horarios.franjas_del_dia(sesion, cancha, LUNES) == [
        (_en(LUNES, time(9, 0)), _en(LUNES + timedelta(days=1), time(2, 0)))
    ]


def test_el_dia_de_semana_le_gana_a_todos_los_dias(sesion, cancha, sucursal):
    _franja(sesion, sucursal, time(9, 0), time(22, 0))
    _franja(sesion, sucursal, time(16, 0), time(23, 0),
            alcance=AlcanceDia.DIA_SEMANA, dia_semana=LUNES.weekday())
    assert horarios.franjas_del_dia(sesion, cancha, LUNES) == [
        (_en(LUNES, time(16, 0)), _en(LUNES, time(23, 0)))
    ]
    # Control: el martes, que no tiene franja propia, sigue con la general.
    martes = LUNES + timedelta(days=1)
    assert horarios.franjas_del_dia(sesion, cancha, martes) == [
        (_en(martes, time(9, 0)), _en(martes, time(22, 0)))
    ]


def test_un_feriado_cerrado_no_tiene_franjas(sesion, cancha, sucursal, feriado_cerrado):
    _franja(sesion, sucursal, time(9, 0), time(22, 0))
    assert horarios.franjas_del_dia(sesion, cancha, feriado_cerrado.dia) == []


def test_el_feriado_puede_abrir_con_horario_propio(sesion, cancha, sucursal, feriado):
    """El docstring de `Feriado` prometía *"un día con tarifa y horario
    distintos"* desde el principio y el horario nunca existió. Ahora sí: una
    franja con `alcance_dia='feriado'`."""
    _franja(sesion, sucursal, time(9, 0), time(22, 0))
    _franja(sesion, sucursal, time(18, 0), time(23, 0), alcance=AlcanceDia.FERIADO)
    assert horarios.franjas_del_dia(sesion, cancha, feriado.dia) == [
        (_en(feriado.dia, time(18, 0)), _en(feriado.dia, time(23, 0)))
    ]
    # Control: un día que NO es feriado ignora esa franja.
    assert horarios.franjas_del_dia(sesion, cancha, LUNES) == [
        (_en(LUNES, time(9, 0)), _en(LUNES, time(22, 0)))
    ]


# ── La grilla ────────────────────────────────────────────────────────────


def test_la_grilla_arranca_y_termina_donde_dice_la_franja(sesion, cancha, sucursal):
    _franja(sesion, sucursal, time(16, 0), time(23, 0))
    turnos = disponibilidad.grilla_del_dia(sesion, cancha, LUNES, con_precio=False)
    assert turnos[0].comienza_at == _en(LUNES, time(16, 0))
    # 90 minutos de paso: 16:00, 17:30, 19:00, 20:30 — y 22:00 no entra entero
    # antes de las 23:00, así que el último termina a las 22:00.
    assert turnos[-1].termina_at <= _en(LUNES, time(23, 0))
    assert all(t.comienza_at >= _en(LUNES, time(16, 0)) for t in turnos)


def test_la_grilla_deja_el_hueco_del_mediodia(sesion, cancha, sucursal):
    _franja(sesion, sucursal, time(9, 0), time(13, 0))
    _franja(sesion, sucursal, time(16, 0), time(23, 0))
    turnos = disponibilidad.grilla_del_dia(sesion, cancha, LUNES, con_precio=False)
    horas = {t.comienza_at.hour for t in turnos}
    assert 9 in horas, "tiene que haber turnos a la mañana"
    assert 16 in horas, "y a la tarde"
    assert not {13, 14, 15} & horas, f"el complejo está cerrado al mediodía: {sorted(horas)}"


def test_una_reserva_que_quedo_fuera_de_horario_SIGUE_apareciendo(
    sesion, cancha, sucursal, cliente
):
    """🔴 El daño que hace achicar el horario de un complejo en marcha.

    La reserva de las 7 de la mañana ya está vendida y cobrada. Que ahora se
    abra a las 9 no la borra: si desapareciera de la grilla, el turno seguiría
    ocupado y nadie lo vería — y encima se podría vender de nuevo.
    """
    # El complejo abría a las 6 y vendió el turno de las 7.
    franja = _franja(sesion, sucursal, time(6, 0), time(23, 0))
    reserva = servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id,
        comienza_at=_en(LUNES, time(7, 0)), duracion_min=60, precio=1,
    )
    sesion.commit()

    # Y ahora decide abrir a las 9. La reserva ya vendida no se toca.
    franja.abre = time(9, 0)
    sesion.commit()
    turnos = disponibilidad.grilla_del_dia(sesion, cancha, LUNES, con_precio=False)

    huerfano = [t for t in turnos if t.reserva_id == reserva.id]
    assert huerfano, f"la reserva de las 7 desapareció de la grilla: {turnos[:3]}"
    assert huerfano[0].comienza_at == _en(LUNES, time(7, 0))
    assert huerfano[0].libre is False
    # Y sigue ordenada por hora, no colgada al final.
    assert [t.comienza_at for t in turnos] == sorted(t.comienza_at for t in turnos)


def test_la_reserva_de_la_madrugada_no_se_dibuja_dos_veces(
    sesion, cancha, sucursal, cliente
):
    """🔑 Un complejo que cierra a las 02:00 tiene su jornada del lunes
    terminando el martes. El turno de las 00:30 pertenece al lunes, y sin el
    chequeo contra las franjas de ayer aparecería también en el martes."""
    _franja(sesion, sucursal, time(16, 0), time(2, 0))
    martes = LUNES + timedelta(days=1)
    reserva = servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id,
        comienza_at=_en(martes, time(0, 30)), duracion_min=60, precio=1,
    )
    sesion.commit()

    del_lunes = disponibilidad.grilla_del_dia(sesion, cancha, LUNES, con_precio=False)
    del_martes = disponibilidad.grilla_del_dia(sesion, cancha, martes, con_precio=False)
    assert any(t.reserva_id == reserva.id for t in del_lunes), "es la jornada del lunes"
    assert not any(t.reserva_id == reserva.id for t in del_martes), "y no la del martes"


# ── El alta ──────────────────────────────────────────────────────────────


def test_no_se_puede_reservar_fuera_del_horario(sesion, cancha, sucursal, cliente):
    """🔴 Que la grilla no lo ofrezca no alcanza: la API sigue abierta."""
    _franja(sesion, sucursal, time(16, 0), time(23, 0))
    with pytest.raises(servicio.FueraDelHorario) as e:
        servicio.crear(
            sesion, cancha_id=cancha.id, cliente_id=cliente.id,
            comienza_at=_en(LUNES, time(4, 0)), duracion_min=60, precio=1,
        )
    # El mensaje dice a qué hora SÍ se puede: el encargado que se equivocó de
    # día necesita el horario, no un "no se puede".
    assert "16:00" in str(e.value), str(e.value)


def test_la_reserva_no_puede_ATRAVESAR_el_hueco_del_mediodia(
    sesion, cancha, sucursal, cliente
):
    """🔑 Entra entera en UNA franja, no en la unión de todas.

    De 12 a 17 las puntas caen dentro de dos franjas abiertas, pero el medio
    está cerrado. Preguntar "¿el inicio está abierto? ¿y el fin?" la aceptaría.
    """
    _franja(sesion, sucursal, time(9, 0), time(13, 0))
    _franja(sesion, sucursal, time(16, 0), time(23, 0))
    with pytest.raises(servicio.FueraDelHorario):
        servicio.crear(
            sesion, cancha_id=cancha.id, cliente_id=cliente.id,
            comienza_at=_en(LUNES, time(12, 0)), duracion_min=300, precio=1,
        )
    # Control: la misma reserva entera dentro de la franja de la tarde sí entra.
    r = servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id,
        comienza_at=_en(LUNES, time(16, 0)), duracion_min=120, precio=1,
    )
    assert r.id is not None


def test_una_reserva_que_TERMINA_pasado_el_cierre_no_entra(
    sesion, cancha, sucursal, cliente
):
    """Empieza adentro y termina afuera. Mirar sólo `comienza_at` la dejaría
    pasar, y el complejo cerraría con gente adentro."""
    _franja(sesion, sucursal, time(16, 0), time(23, 0))
    with pytest.raises(servicio.FueraDelHorario):
        servicio.crear(
            sesion, cancha_id=cancha.id, cliente_id=cliente.id,
            comienza_at=_en(LUNES, time(22, 0)), duracion_min=120, precio=1,
        )


def test_la_reserva_de_madrugada_entra_si_el_complejo_cierra_a_las_dos(
    sesion, cancha, sucursal, cliente
):
    """Control del test de arriba: si la guarda rechazara todo lo de madrugada,
    aquél pasaría igual sin probar el cruce de medianoche."""
    _franja(sesion, sucursal, time(16, 0), time(2, 0))
    r = servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id,
        comienza_at=_en(LUNES + timedelta(days=1), time(0, 30)),
        duracion_min=60, precio=1,
    )
    assert r.id is not None


def test_un_bloqueo_SI_puede_ir_fuera_de_horario(sesion, cancha, sucursal):
    """El mantenimiento de las 6 de la mañana es justamente lo que se hace con
    el lugar cerrado. Es del complejo, no de un cliente."""
    _franja(sesion, sucursal, time(16, 0), time(23, 0))
    b = servicio.crear_bloqueo(
        sesion, cancha_id=cancha.id,
        comienza_at=_en(LUNES, time(6, 0)),
        termina_at=_en(LUNES, time(8, 0)),
        motivo="Mantenimiento",
    )
    assert b.estado is EstadoReserva.BLOQUEO


# ── Las series, que el horario rompió sin que nadie lo notara ────────────


def test_una_serie_con_una_ocurrencia_fuera_de_horario_NO_aborta_entera(
    sesion, cancha, sucursal, cliente, tarifa_base
):
    """🔴 El defecto que introdujo esta feature, y que la suite no vio.

    `materializar_serie` saltea la ocurrencia que no se puede crear y sigue con
    las demás — una cancha fija de los martes con un torneo el tercer martes
    tiene que dejar las otras doce. Su `except` cubría las **dos** excepciones
    que existían cuando se escribió (`Superpuesta` y `SinTarifa`);
    `FueraDelHorario` nació después y esa línea no se enteró.

    Resultado: con el complejo abriendo a las 09:00 y una serie de los martes a
    las 07:00, `POST /series` devolvía 422 y **no creaba ninguna** de las trece,
    ni siquiera las que sí entraban. Verificado contra PostgreSQL antes de
    tocarlo: abortaba con `FueraDelHorario`.
    """
    from app.models.reservas import Serie

    _franja(sesion, sucursal, time(9, 0), time(23, 0))
    serie = Serie(
        cancha_id=cancha.id, cliente_id=cliente.id, dia_semana=LUNES.weekday(),
        hora=time(7, 0), duracion_min=60, desde=LUNES,
    )
    sesion.add(serie)
    sesion.flush()

    creadas, salteadas = servicio.materializar_serie(
        sesion, serie, hasta=LUNES + timedelta(days=28)
    )

    assert creadas == [], "ninguna entra: todas caen a las 07:00"
    assert len(salteadas) >= 4, f"tienen que estar salteadas, no abortadas: {salteadas}"
    assert {x.motivo for x in salteadas} == {"fuera_de_horario"}
    # El detalle nombra el horario del día, que es lo que el operador necesita
    # para corregir: o mueve la serie o cambia el horario.
    assert "09:00" in salteadas[0].detalle


def test_la_serie_crea_las_que_SI_entran_y_saltea_las_otras(
    sesion, cancha, sucursal, cliente, tarifa_base
):
    """Control del test de arriba: si `materializar_serie` no creara nunca nada,
    aquél pasaría igual con la serie rota de otra forma.

    Acá el horario general deja pasar la serie, y **un feriado cerrado** carga
    una sola fecha imposible en el medio.
    """
    from app.models.maestros import Feriado
    from app.models.reservas import Serie

    _franja(sesion, sucursal, time(9, 0), time(23, 0))
    serie = Serie(
        cancha_id=cancha.id, cliente_id=cliente.id, dia_semana=LUNES.weekday(),
        hora=time(20, 0), duracion_min=60, desde=LUNES,
    )
    sesion.add(serie)
    # El segundo lunes, cerrado.
    sesion.add(Feriado(sucursal_id=sucursal.id, dia=LUNES + timedelta(days=7),
                       nombre="Feriado", cerrado=True))
    sesion.flush()

    creadas, salteadas = servicio.materializar_serie(
        sesion, serie, hasta=LUNES + timedelta(days=21)
    )

    assert len(creadas) >= 3, f"las demás tienen que entrar: {len(creadas)}"
    assert len(salteadas) == 1, f"sólo el feriado: {salteadas}"
    assert salteadas[0].motivo == "fuera_de_horario"
    assert salteadas[0].comienza_at.date() == LUNES + timedelta(days=7)


def test_el_motivo_distingue_falta_de_tarifa_de_falta_de_horario(
    sesion, cancha, sucursal, cliente
):
    """🔑 Los dos se arreglan en pantallas distintas.

    Sin tarifa el operador va a Tarifas; fuera de horario, a Horario de
    atención. Un "no se pudo" sin motivo lo manda a adivinar.

    Sin la fixture `tarifa_base`: acá no hay ninguna tarifa cargada.
    """
    from app.models.reservas import Serie

    _franja(sesion, sucursal, time(9, 0), time(23, 0))
    serie = Serie(
        cancha_id=cancha.id, cliente_id=cliente.id, dia_semana=LUNES.weekday(),
        hora=time(20, 0), duracion_min=60, desde=LUNES,
    )
    sesion.add(serie)
    sesion.flush()

    _, salteadas = servicio.materializar_serie(
        sesion, serie, hasta=LUNES + timedelta(days=14)
    )
    assert salteadas, "sin tarifa no se puede crear ninguna"
    assert {x.motivo for x in salteadas} == {"sin_tarifa"}, (
        "el motivo tiene que ser la tarifa, no el horario"
    )
