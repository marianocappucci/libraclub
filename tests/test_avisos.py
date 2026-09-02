"""El motor de avisos: qué se manda, qué no, y qué pasa cuando falla.

Todo se mide con un `momento` explícito y un `created_at` puesto a mano. Nada
depende de la hora real a la que corra el CI: un test de recordatorios que use
`ahora()` pasa o falla según la hora del día, y el que lo vea rojo a las 3 de la
mañana no va a poder reproducirlo.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.models.avisos import Aviso
from app.models.enums import CanalAviso, EstadoAviso, EstadoReserva, TipoAviso
from app.models.reservas import Reserva
from app.servicios import avisos as servicio
from app.servicios import pagos as servicio_pagos
from app.servicios import reservas as servicio_reservas
from app.tiempo import TZ

#: El turno de todos los tests: martes 01-09-2026 a las 20:00, hora local. Fijo
#: —como `un_martes` del conftest— y dentro del horario por defecto (08:00 a
#: 00:00), para que la reserva no se rechace por estar fuera de hora.
CUANDO = datetime(2026, 9, 1, 20, 0, tzinfo=TZ)


class TransporteFalso:
    """Un canal que anota en vez de mandar.

    Implementa el mismo `Protocol` que `TransporteEmail` —`canal`,
    `disponible()` y `enviar()`— y nada más. Que la clase real cumpla ese
    contrato lo mide `test_el_transporte_de_email_sin_smtp_no_esta_disponible`,
    que la usa de verdad: un doble solo prueba lo que uno supone.
    """

    canal = CanalAviso.EMAIL

    def __init__(self, *, disponible: bool = True, falla: str | None = None) -> None:
        self.enviados: list[tuple[str, str, str]] = []
        self._disponible = disponible
        self._falla = falla

    def disponible(self) -> bool:
        return self._disponible

    def enviar(self, *, destino: str, asunto: str, cuerpo: str) -> None:
        if self._falla:
            raise RuntimeError(self._falla)
        self.enviados.append((destino, asunto, cuerpo))


@pytest.fixture
def jugador(sesion, cliente):
    """El cliente del conftest, con email: sin email no hay aviso que mandar."""
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


def _avisos(sesion) -> list[Aviso]:
    return list(sesion.scalars(select(Aviso).order_by(Aviso.id)).all())


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
    transporte = TransporteFalso()

    primera = servicio.despachar(sesion, transporte, momento)
    sesion.commit()
    segunda = servicio.despachar(sesion, transporte, momento + timedelta(minutes=5))
    sesion.commit()

    assert primera.enviados == 1, "el control positivo: la primera sí manda"
    assert segunda.enviados == 0
    assert len(transporte.enviados) == 1
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
    transporte = TransporteFalso()

    servicio.despachar(sesion, transporte, momento)
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

    resumen = servicio.despachar(sesion, TransporteFalso(), momento)
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
    transporte = TransporteFalso()

    de_24 = servicio.despachar(sesion, transporte, CUANDO - timedelta(hours=20))
    sesion.commit()
    de_2 = servicio.despachar(sesion, transporte, CUANDO - timedelta(hours=1))
    sesion.commit()
    otra_vez = servicio.despachar(sesion, transporte, CUANDO - timedelta(minutes=55))
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
    transporte = TransporteFalso()

    servicio.despachar(sesion, transporte, momento)
    sesion.commit()

    tipos = [a.tipo for a in _avisos(sesion)]
    assert tipos == [TipoAviso.CONFIRMACION], f"salió además: {tipos}"


def test_no_se_avisa_un_turno_que_ya_empezo(sesion, cancha, jugador, tarifa_base):
    reserva = _reserva(sesion, cancha, jugador)
    _creada(sesion, reserva, CUANDO - timedelta(days=3))

    resumen = servicio.despachar(sesion, TransporteFalso(), CUANDO + timedelta(minutes=1))
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
    transporte = TransporteFalso()
    servicio.despachar(sesion, transporte, momento)
    sesion.commit()

    servicio_reservas.cambiar_estado(
        sesion, reserva.id, EstadoReserva.CANCELADA, motivo="Lluvia"
    )
    sesion.commit()
    resumen = servicio.despachar(sesion, transporte, momento + timedelta(minutes=10))
    sesion.commit()

    assert resumen.enviados == 1
    cancelacion = [a for a in _avisos(sesion) if a.tipo is TipoAviso.CANCELACION]
    assert len(cancelacion) == 1
    assert "Lluvia" in (cancelacion[0].cuerpo or "")


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

    resumen = servicio.despachar(sesion, TransporteFalso(), CUANDO - timedelta(hours=9))
    sesion.commit()

    assert reserva.estado is EstadoReserva.CANCELADA, "el control: sí quedó cancelada"
    assert resumen.enviados == 0
    assert _avisos(sesion) == []


# --------------------------------------------------------------------------
# Quién queda afuera
# --------------------------------------------------------------------------


def test_sin_email_queda_omitido_y_no_se_reevalua(sesion, cancha, cliente, tarifa_base):
    """El cliente del conftest no tiene email: el turno se toma igual.

    Queda la fila `OMITIDO` y no nada: sin ella la barrida siguiente lo vuelve a
    evaluar, y el encargado que pregunta «¿por qué no le llegó?» no tiene dónde
    mirar.
    """
    reserva = _reserva(sesion, cancha, cliente)
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(minutes=5))
    transporte = TransporteFalso()

    primera = servicio.despachar(sesion, transporte, momento)
    sesion.commit()
    segunda = servicio.despachar(sesion, transporte, momento + timedelta(minutes=5))
    sesion.commit()

    assert (primera.omitidos, segunda.omitidos) == (1, 0)
    (aviso,) = _avisos(sesion)
    assert aviso.estado is EstadoAviso.OMITIDO
    assert aviso.destino == ""
    assert "email" in (aviso.detalle or "")
    assert transporte.enviados == []


def test_el_que_pidio_no_recibir_no_recibe(sesion, cancha, jugador, tarifa_base):
    jugador.acepta_avisos = False
    sesion.commit()
    reserva = _reserva(sesion, cancha, jugador)
    momento = CUANDO - timedelta(hours=10)
    _creada(sesion, reserva, momento - timedelta(minutes=5))
    transporte = TransporteFalso()

    resumen = servicio.despachar(sesion, transporte, momento)
    sesion.commit()

    assert (resumen.enviados, resumen.omitidos) == (0, 1)
    assert transporte.enviados == []
    assert _avisos(sesion)[0].estado is EstadoAviso.OMITIDO


def test_quitar_un_bloqueo_no_le_avisa_a_nadie(sesion, cancha, tarifa_base):
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

    resumen = servicio.despachar(sesion, TransporteFalso(), CUANDO - timedelta(hours=10))
    sesion.commit()

    assert bloqueo.cliente_id is None, "el control: la cancelada quedó sin cliente"
    assert resumen == servicio.Resumen()
    assert _avisos(sesion) == []


def test_el_bloqueo_no_le_avisa_a_nadie(sesion, cancha, tarifa_base):
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

    resumen = servicio.despachar(sesion, TransporteFalso(), momento)
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
    roto = TransporteFalso(falla="550 mailbox unavailable")

    for i in range(5):
        servicio.despachar(sesion, roto, momento + timedelta(minutes=i))
        sesion.commit()

    (aviso,) = _avisos(sesion)
    assert aviso.estado is EstadoAviso.FALLIDO
    assert aviso.intentos == servicio.MAX_INTENTOS
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

    servicio.despachar(sesion, TransporteFalso(falla="conexión rechazada"), momento)
    sesion.commit()
    bueno = TransporteFalso()
    resumen = servicio.despachar(sesion, bueno, momento + timedelta(minutes=5))
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

    resumen = servicio.despachar(sesion, TransporteFalso(disponible=False), momento)
    sesion.commit()

    assert resumen == servicio.Resumen()
    assert _avisos(sesion) == []


# --------------------------------------------------------------------------
# El texto, el transporte real y el cron
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
    transporte = TransporteFalso()

    servicio.despachar(sesion, transporte, momento)
    sesion.commit()

    (destino, asunto, cuerpo) = transporte.enviados[0]
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


def test_el_transporte_de_email_sin_smtp_no_esta_disponible():
    """La clase **real**, no el doble.

    Es lo que ata el `Protocol` a la implementación: si `TransporteEmail`
    cambiara de forma —otro nombre de método, otra firma— el doble seguiría
    andando y la suite entera quedaría verde midiendo un objeto que ya no
    existe.
    """
    from libraauth.email_sender import SmtpConfig

    transporte = servicio.TransporteEmail(lambda: SmtpConfig())

    assert transporte.canal is CanalAviso.EMAIL
    assert transporte.disponible() is False


def test_el_transporte_de_email_con_smtp_cargado_esta_disponible():
    """El control positivo del de arriba: `disponible()` puede dar `True`.

    Sin él, un `disponible()` que devolviera siempre `False` —o que mirara el
    campo equivocado— pasaría el test anterior sin despeinarse, y en producción
    no saldría un solo mail.
    """
    from libraauth.email_sender import SmtpConfig

    config = SmtpConfig(
        host="smtp.ejemplo.com", port=587, user="u", password="p",
        from_email="turnos@ejemplo.com",
    )
    assert servicio.TransporteEmail(lambda: config).disponible() is True


def test_el_script_del_cron_existe_y_se_puede_importar():
    """🔑 El mecanismo que nadie invoca.

    Este script **es** el interruptor de los avisos: sin él no sale nada. Un
    import roto —una función que se renombró— sólo se descubriría cuando el cron
    escriba un traceback en un log que nadie mira.
    """
    import importlib

    modulo = importlib.import_module("scripts.enviar_avisos")

    assert callable(modulo.main)


def test_los_dias_de_la_semana_no_cambian_el_resultado():
    """La fecha de los tests es fija a propósito. Este assert lo deja escrito.

    Si alguien la cambia por `hoy()`, este test no falla — pero el comentario
    que explica por qué no hay que hacerlo queda en un lugar donde se lee.
    """
    assert CUANDO.date() == date(2026, 9, 1)
    assert CUANDO.strftime("%A") in {"Tuesday", "martes"}
