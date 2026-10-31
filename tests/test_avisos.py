"""El barrido de avisos: qué se manda, qué no, y qué pasa cuando falla.

Desde el ADR-030 el envío es del motor (`libracore.avisos`): estos tests miden **lo que es de LibraClub** —qué
corresponde avisar y con qué texto— contra un proveedor falso, y que el barrido deja el rastro en `avisos_envios`. Cómo
reintenta, cómo reserva y cómo contesta cada proveedor lo miden los tests del motor.

Todo se mide con un `momento` explícito y un `created_at` puesto a mano. Nada
depende de la hora real a la que corra el CI: un test de recordatorios que use
`ahora()` pasa o falla según la hora del día, y el que lo vea rojo a las 3 de la
mañana no va a poder reproducirlo.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from libracore.avisos import MAX_INTENTOS
from sqlalchemy import update

from app.models.enums import EstadoAviso, EstadoReserva, TipoAviso
from app.models.reservas import CanalDePago, EstadoPago, Reserva
from app.servicios import avisos as servicio
from app.servicios import pagos as servicio_pagos
from app.servicios import reservas as servicio_reservas
from app.tiempo import TZ
from tests.avisos_apoyo import Guardado, ProveedorFalso, guardados

#: El turno de todos los tests: martes 01-09-2026 a las 20:00, hora local. Fijo
#: —como `un_martes` del conftest— y dentro del horario por defecto (08:00 a
#: 00:00), para que la reserva no se rechace por estar fuera de hora.
CUANDO = datetime(2026, 9, 1, 20, 0, tzinfo=TZ)


@pytest.fixture
def jugador(sesion, cliente, motor):
    """El cliente del conftest, con email (sin email no hay aviso que mandar), y el motor apuntando a la base."""
    cliente.email = "jugador@ejemplo.com"
    sesion.commit()
    return cliente


def _creada(sesion, reserva: Reserva, cuando: datetime) -> None:
    """Pone `created_at` a mano.

    Es `server_default now()`, así que sin esto toda reserva de la suite nace
    "recién creada" y las dos reglas que miran la antigüedad —la ventana de la
    confirmación y la del recordatorio— no se pueden probar.
    """
    sesion.execute(
        update(Reserva).where(Reserva.id == reserva.id).values(created_at=cuando)
    )
    sesion.commit()
    sesion.expire(reserva)


def _reserva(sesion, cancha, jugador, *, estado=EstadoReserva.CONFIRMADA, cuando=CUANDO):
    reserva = servicio_reservas.crear(
        sesion,
        cancha_id=cancha.id,
        cliente_id=jugador.id,
        comienza_at=cuando,
        estado=estado,
    )
    sesion.commit()
    return reserva


def _avisos(sesion) -> list[Guardado]:
    """Lo que el barrido dejó en `avisos_envios`, del más viejo al más nuevo."""
    return guardados()


# --------------------------------------------------------------------------
# Confirmación
# --------------------------------------------------------------------------


def test_la_confirmacion_sale_y_no_se_repite(sesion, cancha, jugador, tarifa_base):
    """El cron corre cada 5 minutos sobre las mismas reservas.

    El segundo `despachar` es el que importa: sin la clave única y el filtro por
    aviso ya terminal, el turno del viernes recibiría un mail por corrida.
    """
    reserva = _reserva(sesion, cancha, jugador)
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(minutes=5))
    proveedor = ProveedorFalso()

    primera = servicio.barrer(sesion, proveedor, momento)
    sesion.commit()
    segunda = servicio.barrer(sesion, proveedor, momento + timedelta(minutes=5))
    sesion.commit()

    assert primera.enviados == 1, "el control positivo: la primera sí manda"
    assert segunda.enviados == 0
    assert len(proveedor.enviados) == 1
    (guardado,) = _avisos(sesion)
    assert guardado.tipo is TipoAviso.CONFIRMACION
    assert guardado.estado is EstadoAviso.ENVIADO
    assert guardado.destino == "jugador@ejemplo.com"
    assert guardado.enviado_at is not None


def test_no_se_confirman_las_reservas_viejas(sesion, cancha, jugador, tarifa_base):
    """🔴 El mailing masivo del día que esto se enciende.

    Una reserva cargada hace meses ya está confirmada y nadie le prometió un
    mail. Sin la ventana, la primera corrida del cron le escribe a cada cliente
    por cada turno futuro que tenga.
    """
    reserva = _reserva(sesion, cancha, jugador)
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(days=30))
    proveedor = ProveedorFalso()

    servicio.barrer(sesion, proveedor, momento)
    sesion.commit()

    tipos = [a.tipo for a in _avisos(sesion)]
    assert TipoAviso.CONFIRMACION not in tipos
    # 🔑 **El recordatorio sí sale, y está bien.** La primera corrida sobre una
    # base con historia manda los recordatorios de las próximas 24 h —que es la
    # función del producto— pero **no** una confirmación por cada turno futuro
    # cargado en los últimos meses. Sin este assert el test pasaría también con
    # un barrido que no manda nada, que es el otro error.
    assert tipos == [TipoAviso.RECORDATORIO]


def test_la_reserva_confirmada_por_el_webhook_tambien_avisa(
    sesion, cancha, jugador, tarifa_base
):
    """🔑 **El test que justifica que no haya cola.**

    `aplicar_pago_aprobado` escribe `reserva.estado = CONFIRMADA` a mano: no
    pasa por `crear()` ni por `cambiar_estado()`. Una cola que se llenara desde
    esos dos caminos dejaría al portal —que es de donde viene el jugador que
    reserva a las 2 de la mañana— sin un solo mail, y sin nada que fallara.
    """
    reserva = _reserva(sesion, cancha, jugador, estado=EstadoReserva.PROVISORIA)
    pago = servicio_pagos.crear_pago(sesion, reserva, Decimal("5000.00"))
    sesion.commit()
    servicio_pagos.aplicar_pago_aprobado(
        sesion, pago, payment_id="123", estado_mp="approved"
    )
    sesion.commit()
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(minutes=5))

    resumen = servicio.barrer(sesion, ProveedorFalso(), momento)
    sesion.commit()

    assert reserva.estado is EstadoReserva.CONFIRMADA
    assert resumen.enviados == 1
    assert _avisos(sesion)[0].tipo is TipoAviso.CONFIRMACION


# --------------------------------------------------------------------------
# Recordatorios
# --------------------------------------------------------------------------


def test_los_dos_recordatorios_son_avisos_distintos(sesion, cancha, jugador, tarifa_base):
    """El de 24 h y el de 2 h son el mismo `tipo` y **no** el mismo aviso.

    Si `horas_antes` no entrara en la clave ni en el filtro, mandar el primero
    cancelaría el segundo para siempre — y el segundo es el que evita el
    no-show.
    """
    reserva = _reserva(sesion, cancha, jugador)
    _creada(sesion, reserva, CUANDO - timedelta(days=3))
    proveedor = ProveedorFalso()

    de_24 = servicio.barrer(sesion, proveedor, CUANDO - timedelta(hours=20))
    sesion.commit()
    de_2 = servicio.barrer(sesion, proveedor, CUANDO - timedelta(hours=1))
    sesion.commit()
    otra_vez = servicio.barrer(sesion, proveedor, CUANDO - timedelta(minutes=55))
    sesion.commit()

    assert (de_24.enviados, de_2.enviados, otra_vez.enviados) == (1, 1, 0)
    anticipaciones = sorted(a.horas_antes for a in _avisos(sesion))
    assert anticipaciones == [2, 24]
    assert all(a.tipo is TipoAviso.RECORDATORIO for a in _avisos(sesion))


def test_no_se_recuerda_un_turno_que_se_acaba_de_reservar(
    sesion, cancha, jugador, tarifa_base
):
    """El que reserva a las 19:00 para las 20:00 no necesita que le recuerden.

    Sin la regla, ese jugador recibe la confirmación y, tres minutos después, un
    «te esperamos mañana» por el mismo turno. Se lee como un error del sistema,
    porque lo es.
    """
    reserva = _reserva(sesion, cancha, jugador)
    momento = CUANDO - timedelta(hours=1)
    _creada(sesion, reserva, momento - timedelta(minutes=5))
    proveedor = ProveedorFalso()

    servicio.barrer(sesion, proveedor, momento)
    sesion.commit()

    tipos = [a.tipo for a in _avisos(sesion)]
    assert tipos == [TipoAviso.CONFIRMACION], f"salió además: {tipos}"


def test_no_se_avisa_un_turno_que_ya_empezo(sesion, cancha, jugador, tarifa_base):
    reserva = _reserva(sesion, cancha, jugador)
    _creada(sesion, reserva, CUANDO - timedelta(days=3))

    resumen = servicio.barrer(sesion, ProveedorFalso(), CUANDO + timedelta(minutes=1))
    sesion.commit()

    assert resumen.enviados == 0
    assert _avisos(sesion) == []


# --------------------------------------------------------------------------
# Cancelación
# --------------------------------------------------------------------------


def test_la_cancelacion_se_avisa_si_el_cliente_sabia_que_tenia_turno(
    sesion, cancha, jugador, tarifa_base
):
    reserva = _reserva(sesion, cancha, jugador)
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(minutes=5))
    proveedor = ProveedorFalso()
    servicio.barrer(sesion, proveedor, momento)
    sesion.commit()

    servicio_reservas.cambiar_estado(
        sesion, reserva.id, EstadoReserva.CANCELADA, motivo="Lluvia"
    )
    sesion.commit()
    resumen = servicio.barrer(sesion, proveedor, momento + timedelta(minutes=10))
    sesion.commit()

    assert resumen.enviados == 1
    cancelacion = [a for a in _avisos(sesion) if a.tipo is TipoAviso.CANCELACION]
    assert len(cancelacion) == 1
    assert "Lluvia" in (cancelacion[0].cuerpo or "")


def _aviso_de_cancelacion(
    sesion, cancha, jugador, *, estado_pago=None, canal=None, horas=None
) -> str:
    """El cuerpo del mail de cancelación de un turno ya avisado.

    Con `estado_pago`, el turno se paga por el portal y al pago se le pone ese
    estado **a mano** antes de cancelar. Acá no se prueba la política —eso es
    `test_cancelacion.py`— sino que el mail diga **lo que quedó guardado**: el
    cron corre en otro proceso, minutos después, y la base es lo único que tiene.
    """
    if horas is not None:
        cancha.sucursal.horas_de_cancelacion = horas
        sesion.commit()
    pago = None
    if estado_pago is None:
        reserva = _reserva(sesion, cancha, jugador)
    else:
        reserva = _reserva(sesion, cancha, jugador, estado=EstadoReserva.PROVISORIA)
        pago = servicio_pagos.crear_pago(sesion, reserva, Decimal("5000.00"))
        sesion.commit()
        servicio_pagos.aplicar_pago_aprobado(
            sesion, pago, payment_id="123", estado_mp="approved"
        )
        sesion.commit()
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(minutes=5))
    proveedor = ProveedorFalso()
    servicio.barrer(sesion, proveedor, momento)
    sesion.commit()

    if pago is not None:
        pago.estado = estado_pago
        if canal is not None:
            pago.canal = canal
    servicio_reservas.cambiar_estado(
        sesion, reserva.id, EstadoReserva.CANCELADA, motivo="Lluvia"
    )
    sesion.commit()
    servicio.barrer(sesion, proveedor, momento + timedelta(minutes=10))
    sesion.commit()

    cuerpos = [c for _d, a, c in proveedor.enviados if a.startswith("Turno cancelado")]
    assert len(cuerpos) == 1, proveedor.enviados
    return cuerpos[0]


def test_la_cancelacion_dice_que_se_devolvio_la_sena(sesion, cancha, jugador, tarifa_base):
    cuerpo = _aviso_de_cancelacion(sesion, cancha, jugador, estado_pago=EstadoPago.DEVUELTO)

    assert "Te devolvimos la seña" in cuerpo
    assert "unos días" in cuerpo


def test_la_sena_devuelta_por_caja_no_dice_que_llega_a_la_cuenta(
    sesion, cancha, jugador, tarifa_base
):
    """Salió del cajón en efectivo: «puede tardar en verse en tu cuenta» sería
    mentira, porque no pasa por ninguna cuenta."""
    cuerpo = _aviso_de_cancelacion(
        sesion, cancha, jugador, estado_pago=EstadoPago.DEVUELTO, canal=CanalDePago.MOSTRADOR
    )

    assert "en efectivo" in cuerpo
    assert "cuenta" not in cuerpo


def test_la_devolucion_pendiente_se_avisa_sin_contar_por_que(
    sesion, cancha, jugador, tarifa_base
):
    """🔴 Le corresponde y se le dice; el motivo interno —credenciales, caja
    cerrada— es del complejo y no va en un mail."""
    cuerpo = _aviso_de_cancelacion(
        sesion, cancha, jugador, estado_pago=EstadoPago.DEVOLUCION_PENDIENTE
    )

    assert "corresponde la devolución de la seña" in cuerpo
    assert "MercadoPago" not in cuerpo
    assert "caja" not in cuerpo


def test_cancelada_tarde_dice_por_que_no_se_devuelve(sesion, cancha, jugador, tarifa_base):
    """El pago siguió `aprobado` con la política cargada: se canceló tarde.

    El momento sale del `updated_at` de la cancelación —hoy, días después de
    `CUANDO`—, así que el turno ya había pasado: tarde sin discusión.
    """
    cuerpo = _aviso_de_cancelacion(
        sesion, cancha, jugador, estado_pago=EstadoPago.APROBADO, horas=24
    )

    assert "menos de 24 horas" in cuerpo
    assert "no se devuelve" in cuerpo


def test_sin_politica_la_sena_no_se_devuelve_a_secas(sesion, cancha, jugador, tarifa_base):
    cuerpo = _aviso_de_cancelacion(sesion, cancha, jugador, estado_pago=EstadoPago.APROBADO)

    assert "La seña no se devuelve." in cuerpo
    assert "horas" not in cuerpo


def test_sin_sena_el_aviso_no_habla_de_sena(sesion, cancha, jugador, tarifa_base):
    """🔑 El control de los cinco de arriba.

    `tarifa_base` le pone seña del 50 % a la reserva, así que el turno **tiene**
    `sena` cargada — pero nadie la pagó. El mail no puede decir que se devolvió
    ni que no se devuelve una plata que nunca entró.
    """
    cuerpo = _aviso_de_cancelacion(sesion, cancha, jugador)

    assert "Lluvia" in cuerpo, "el control: es el mail de la cancelación"
    assert "seña" not in cuerpo.lower()


def test_un_pago_rechazado_no_es_una_sena(sesion, cancha, jugador, tarifa_base):
    """Un pago que MercadoPago rechazó es plata que nunca entró."""
    cuerpo = _aviso_de_cancelacion(sesion, cancha, jugador, estado_pago=EstadoPago.RECHAZADO)

    assert "seña" not in cuerpo.lower()


def test_la_provisoria_vencida_no_avisa_nada(sesion, cancha, jugador, tarifa_base):
    """🔴 Mandarle «se canceló tu reserva» a quien nunca tuvo una es peor que
    no mandar nada: el jugador cree que perdió un turno.

    Una provisoria que vence sin pagarse termina en `cancelada`, igual que un
    turno confirmado que se cae. Lo que las distingue es si se le avisó al
    cliente que lo tenía.
    """
    reserva = _reserva(sesion, cancha, jugador, estado=EstadoReserva.PROVISORIA)
    _creada(sesion, reserva, CUANDO - timedelta(hours=11))

    # 🔴 El corte sale del `vence_at` de LA PROPIA reserva, no de `CUANDO`.
    #
    # `CUANDO` es el reloj fijo de este archivo, pero `servicio_reservas.crear()`
    # calcula `vence_at` con `ahora()` — el reloj REAL. Mientras la fecha de hoy
    # coincidió con `CUANDO` los dos valores estaban cerca y el test pasaba; el
    # 2026-09-02 se separaron un día, `vence_at` quedó después del corte, la
    # provisoria no venció y el test se puso rojo sin que nadie tocara nada.
    #
    # Es el idioma que ya usa `test_reservas.py`: vencerla "desde el futuro"
    # relativo a su propio vencimiento. Así el test no depende del calendario.
    assert reserva.vence_at is not None, "una provisoria nace con vencimiento"
    servicio_reservas.vencer_provisorias(
        sesion, reserva.vence_at + timedelta(seconds=1)
    )
    sesion.commit()

    resumen = servicio.barrer(sesion, ProveedorFalso(), CUANDO - timedelta(hours=9))
    sesion.commit()

    assert reserva.estado is EstadoReserva.CANCELADA, "el control: sí quedó cancelada"
    assert resumen.enviados == 0
    assert _avisos(sesion) == []


# --------------------------------------------------------------------------
# Quién queda afuera
# --------------------------------------------------------------------------


def test_sin_email_queda_omitido_y_no_se_reevalua(sesion, cancha, cliente, tarifa_base, motor):
    """El cliente del conftest no tiene email: el turno se toma igual.

    Queda la fila `OMITIDO` y no nada: sin ella la barrida siguiente lo vuelve a
    evaluar, y el encargado que pregunta «¿por qué no le llegó?» no tiene dónde
    mirar.
    """
    reserva = _reserva(sesion, cancha, cliente)
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(minutes=5))
    proveedor = ProveedorFalso()

    primera = servicio.barrer(sesion, proveedor, momento)
    sesion.commit()
    segunda = servicio.barrer(sesion, proveedor, momento + timedelta(minutes=5))
    sesion.commit()

    assert (primera.omitidos, segunda.omitidos) == (1, 0)
    (aviso,) = _avisos(sesion)
    assert aviso.estado is EstadoAviso.OMITIDO
    assert aviso.destino == ""
    assert "email" in (aviso.detalle or "")
    assert proveedor.enviados == []


def test_el_que_pidio_no_recibir_no_recibe(sesion, cancha, jugador, tarifa_base):
    jugador.acepta_avisos = False
    sesion.commit()
    reserva = _reserva(sesion, cancha, jugador)
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(minutes=5))
    proveedor = ProveedorFalso()

    resumen = servicio.barrer(sesion, proveedor, momento)
    sesion.commit()

    assert (resumen.enviados, resumen.omitidos) == (0, 1)
    assert proveedor.enviados == []
    assert _avisos(sesion)[0].estado is EstadoAviso.OMITIDO


def test_quitar_un_bloqueo_no_le_avisa_a_nadie(sesion, cancha, tarifa_base, motor):
    """🔴 «Quitar bloqueo» deja una `cancelada` **sin cliente**.

    Es la única fila viva del sistema donde `cliente_id` puede ser `NULL` fuera
    de un bloqueo —el CHECK exime a las canceladas justamente por esto— así que
    es el caso que puede hacer explotar el barrido de cancelaciones al buscar a
    quién escribirle. Lo que lo deja afuera es el `EXISTS` de la confirmación:
    un bloqueo nunca recibió una.
    """
    bloqueo = servicio_reservas.crear_bloqueo(
        sesion,
        cancha_id=cancha.id,
        comienza_at=CUANDO,
        termina_at=CUANDO + timedelta(hours=2),
        motivo="Pintura",
    )
    sesion.commit()
    servicio_reservas.cambiar_estado(sesion, bloqueo.id, EstadoReserva.CANCELADA)
    sesion.commit()

    resumen = servicio.barrer(sesion, ProveedorFalso(), CUANDO - timedelta(hours=10))
    sesion.commit()

    assert bloqueo.cliente_id is None, "el control: la cancelada quedó sin cliente"
    assert resumen == servicio.Resumen()
    assert _avisos(sesion) == []


def test_el_bloqueo_no_le_avisa_a_nadie(sesion, cancha, tarifa_base, motor):
    """Un bloqueo de mantenimiento no tiene cliente. Es una fila de `reservas`
    como cualquier otra, así que lo único que lo deja afuera es el estado.

    ⚠️ El `_creada` **no es decorado**: sin él, el bloqueo queda con el
    `created_at` real —meses antes del `momento` de la prueba— y la ventana de
    la confirmación lo descarta antes de llegar al filtro por estado. El test
    pasaba igual y no medía nada: lo delató la mutación que saca el estado del
    barrido, que seguía verde.
    """
    bloqueo = servicio_reservas.crear_bloqueo(
        sesion,
        cancha_id=cancha.id,
        comienza_at=CUANDO,
        termina_at=CUANDO + timedelta(hours=2),
        motivo="Pintura",
    )
    sesion.commit()
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, bloqueo, momento - timedelta(minutes=5))

    resumen = servicio.barrer(sesion, ProveedorFalso(), momento)
    sesion.commit()

    assert resumen == servicio.Resumen()
    assert _avisos(sesion) == []


# --------------------------------------------------------------------------
# Cuando falla
# --------------------------------------------------------------------------


def test_un_envio_fallido_se_reintenta_y_despues_se_deja(
    sesion, cancha, jugador, tarifa_base
):
    """Tres intentos y basta.

    Sin el corte, un mail que rebota para siempre —una casilla que no existe—
    se reintenta en cada corrida del cron, es decir 288 veces por día.
    """
    reserva = _reserva(sesion, cancha, jugador)
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(minutes=5))
    roto = ProveedorFalso(falla="550 mailbox unavailable")

    for i in range(5):
        servicio.barrer(sesion, roto, momento + timedelta(minutes=i))
        sesion.commit()

    (aviso,) = _avisos(sesion)
    assert aviso.estado is EstadoAviso.FALLIDO
    assert aviso.intentos == MAX_INTENTOS
    assert "550" in (aviso.detalle or "")
    assert aviso.enviado_at is None


def test_un_reintento_que_funciona_queda_enviado(sesion, cancha, jugador, tarifa_base):
    """El control positivo del test de arriba: el reintento **sirve**.

    Sin esto, "se reintenta 3 veces" pasaría igual con un reintento que no
    manda nada nunca.
    """
    reserva = _reserva(sesion, cancha, jugador)
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(minutes=5))

    servicio.barrer(sesion, ProveedorFalso(falla="conexión rechazada"), momento)
    sesion.commit()
    bueno = ProveedorFalso()
    resumen = servicio.barrer(sesion, bueno, momento + timedelta(minutes=5))
    sesion.commit()

    assert resumen.enviados == 1
    (aviso,) = _avisos(sesion)
    assert aviso.estado is EstadoAviso.ENVIADO
    assert aviso.intentos == 2
    assert aviso.detalle is None
    assert len(bueno.enviados) == 1


def test_sin_transporte_disponible_no_se_anota_nada(sesion, cancha, jugador, tarifa_base):
    """🔴 Una instancia sin SMTP no puede quemar los tres intentos.

    Si la barrida corriera igual, cada reserva juntaría un `FALLIDO` por corrida
    y en quince minutos ya no le avisaría más a ese cliente — por una config que
    a lo mejor se completa al día siguiente.
    """
    reserva = _reserva(sesion, cancha, jugador)
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(minutes=5))

    resumen = servicio.barrer(sesion, ProveedorFalso(disponible=False), momento)
    sesion.commit()

    assert resumen == servicio.Resumen()
    assert _avisos(sesion) == []


# --------------------------------------------------------------------------
# El texto, el proveedor real y el cron
# --------------------------------------------------------------------------


def test_el_texto_lleva_la_hora_local_y_la_cancha(sesion, cancha, jugador, tarifa_base):
    """`dd-mm-aaaa HH:MM` y hora de pared del complejo.

    El turno es de las 20:00 para el que lo reservó. Si el cuerpo se armara con
    el `datetime` crudo que devuelve psycopg, diría 23:00 — el mismo instante en
    UTC, y una discusión en el mostrador.
    """
    reserva = _reserva(sesion, cancha, jugador)
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(minutes=5))
    proveedor = ProveedorFalso()

    servicio.barrer(sesion, proveedor, momento)
    sesion.commit()

    (destino, asunto, cuerpo) = proveedor.enviados[0]
    assert destino == "jugador@ejemplo.com"
    assert "01-09-2026 20:00" in cuerpo
    assert "23:00" not in cuerpo
    assert "Cancha 1" in cuerpo
    assert "Juan Pérez" in cuerpo
    assert "01-09-2026 20:00" in asunto
    # La tarifa del conftest son $10.000 con 50% de seña.
    assert "$10.000,00" in cuerpo
    assert "$5.000,00" in cuerpo


def test_la_plata_se_escribe_como_en_argentina():
    """🔴 Miles con punto y decimales con coma, y no las dos cosas con punto.

    Cambiar sólo la coma del formato de Python —el error fácil— deja `10.000.00`,
    que no es un número en ningún lado. Se prueba la función y no sólo el texto
    del mail: un número mal escrito en un precio es lo primero que el cliente
    mira y lo primero que hace desconfiar del sistema.
    """
    assert servicio.pesos(Decimal("10000")) == "$10.000,00"
    assert servicio.pesos(Decimal("1234567.89")) == "$1.234.567,89"
    assert servicio.pesos(Decimal("999.5")) == "$999,50"
    assert servicio.pesos(Decimal("0")) == "$0,00"
    assert "€" not in servicio.pesos(Decimal("1000"))


def test_el_proveedor_de_email_sin_smtp_no_esta_disponible():
    """El proveedor **real** del motor, armado como lo arma el cron (`construir_proveedores`), no el doble.

    Es lo que ata `ProveedorFalso` al contrato: un doble sólo prueba lo que uno supone. Y mide el enganche que es de
    LibraClub: que el resolver de SMTP de la instancia llegue al proveedor de mail.
    """
    from libraauth.email_sender import SmtpConfig

    email = servicio.construir_proveedores(lambda: SmtpConfig())["email"]

    assert email.canal == "email"
    assert email.simulado is False
    assert email.disponible() is False


def test_el_proveedor_de_email_con_smtp_cargado_esta_disponible():
    """El control positivo del de arriba: `disponible()` puede dar `True`.

    Sin él, un `disponible()` que devolviera siempre `False` —o que mirara el campo equivocado— pasaría el test anterior
    sin despeinarse, y en producción no saldría un solo mail.
    """
    from libraauth.email_sender import SmtpConfig

    config = SmtpConfig(
        host="smtp.ejemplo.com", port=587, user="u", password="p",
        from_email="turnos@ejemplo.com",
    )
    email = servicio.construir_proveedores(lambda: config)["email"]

    assert email.disponible() is True


def test_el_script_del_cron_existe_y_se_puede_importar(engine, monkeypatch):
    """🔑 El mecanismo que nadie invoca.

    Este script **es** el interruptor de los avisos: sin él no sale nada. Un import roto —una función que se
    renombró— sólo se descubriría cuando el cron escriba un traceback en un log que nadie mira.

    Importarlo levanta el arranque de la app (`import app.asgi`, que enchufa el almacén de secretos): acá con la config
    de la suite, como en `test_secretos_config_json.py`.
    """
    import importlib
    import sys

    from libraauth.models import Base as AuthBase
    from libraauth.testing import crear_schema_de_auth

    import app.main as app_main
    from tests.test_api import CLAVE, USUARIO, _config

    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    real = app_main.crear_app
    monkeypatch.setattr(app_main, "crear_app", lambda *a, **k: real(_config()))
    for nombre in ("app.asgi", "scripts.enviar_avisos"):
        monkeypatch.delitem(sys.modules, nombre, raising=False)

    modulo = importlib.import_module("scripts.enviar_avisos")

    assert callable(modulo.main)
    AuthBase.metadata.drop_all(engine)


def test_los_dias_de_la_semana_no_cambian_el_resultado():
    """La fecha de los tests es fija a propósito. Este assert lo deja escrito.

    Si alguien la cambia por `hoy()`, este test no falla — pero el comentario
    que explica por qué no hay que hacerlo queda en un lugar donde se lee.
    """
    assert CUANDO.date() == date(2026, 9, 1)
    assert CUANDO.strftime("%A") in {"Tuesday", "martes"}
