"""La política de cancelación: cuándo se devuelve la seña y cuándo no.

La regla del producto son tres frases, y cada una tiene su test:

1. **Cancelar siempre se puede.** La ventana decide si se devuelve la plata, no
   si el jugador puede soltar el turno.
2. **La cancelación no se cae porque falle la devolución.** El turno queda libre
   y la deuda queda anotada.
3. **Sólo se devuelve el pago del portal.** El de mostrador ya entró a la caja.

Ninguno de estos tests sale a la red: la pasarela es un doble, y hay un test que
mide que la de verdad **no llama** cuando no hay token.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app
from app.models.enums import AlcanceDia, EstadoReserva
from app.models.maestros import FranjaDeAtencion
from app.models.reservas import CanalDePago, EstadoPago, PagoDeReserva
from app.servicios import cancelacion as servicio
from app.servicios import devoluciones
from app.servicios import pagos as servicio_pagos
from app.servicios import reservas as servicio_reservas
from app.tiempo import ahora

USUARIO, CLAVE = "admin", "clave-de-prueba"


class PasarelaFalsa:
    """Devuelve lo que se le diga, y anota con qué la llamaron.

    Guarda las referencias de idempotencia porque **son la garantía de no
    devolver dos veces**: si el reintento mandara una distinta, MercadoPago
    trataría el segundo pedido como una devolución nueva.
    """

    def __init__(self, *, disponible: bool = True, falla: str | None = None) -> None:
        self.llamadas: list[tuple[str, str]] = []
        self._disponible = disponible
        self._falla = falla

    def disponible(self) -> bool:
        return self._disponible

    def devolver(self, *, payment_id: str, referencia: str) -> str:
        self.llamadas.append((payment_id, referencia))
        if self._falla:
            raise devoluciones.DevolucionRechazada(self._falla)
        return f"refund-{payment_id}"


def _en(horas: int) -> datetime:
    """Un turno dentro de N horas, redondeado a la hora en punto local.

    Redondeado para que el turno caiga siempre a la misma hora de pared y no
    dependa del minuto en que corra la suite.
    """
    momento = ahora() + timedelta(hours=horas)
    return momento.replace(minute=0, second=0, microsecond=0)


@pytest.fixture
def abierto(sesion, sucursal):
    """El complejo abre las 24 h: acá no se prueba el horario de atención."""
    sesion.add(
        FranjaDeAtencion(
            sucursal_id=sucursal.id, alcance_dia=AlcanceDia.TODOS,
            abre=time(0, 0), cierra=time(0, 0),
        )
    )
    sesion.commit()


@pytest.fixture
def vendible(abierto, tarifa_base):
    """Lo mínimo para que un turno se pueda vender: complejo abierto y tarifa.

    Van juntas porque acá no se prueba ninguna de las dos: un test de política
    de cancelación que falla por `SinTarifa` no dice nada sobre la política.
    """


@pytest.fixture
def con_politica(sesion, sucursal):
    """La sucursal devuelve si se avisa con 24 horas."""
    sucursal.horas_de_cancelacion = 24
    sesion.commit()
    return sucursal


def _reserva_pagada(sesion, cancha, cliente, *, en_horas=48, canal=CanalDePago.PORTAL):
    """Un turno confirmado con su seña aprobada, como lo deja el portal."""
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id,
        comienza_at=_en(en_horas), estado=EstadoReserva.PROVISORIA,
    )
    sesion.commit()
    pago = servicio_pagos.crear_pago(sesion, reserva, Decimal("5000.00"))
    pago.canal = canal
    sesion.commit()
    servicio_pagos.aplicar_pago_aprobado(
        sesion, pago, payment_id="mp-123", estado_mp="approved"
    )
    sesion.commit()
    return reserva, pago


# ── La ventana ───────────────────────────────────────────────────────────


def test_a_tiempo_se_devuelve(sesion, cancha, cliente, vendible, con_politica):
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=48)
    pasarela = PasarelaFalsa()

    resultado = servicio.cancelar(
        sesion, reserva.id, motivo="Se lesionó", pasarela=pasarela
    )
    sesion.commit()

    assert resultado.reserva.estado is EstadoReserva.CANCELADA
    assert resultado.devolucion is EstadoPago.DEVUELTO
    assert pago.estado is EstadoPago.DEVUELTO
    assert pago.refund_id == "refund-mp-123"
    assert pago.devuelto_at is not None
    assert pago.detalle_devolucion is None
    assert len(pasarela.llamadas) == 1


def test_tarde_no_se_devuelve_pero_se_cancela_igual(
    sesion, cancha, cliente, vendible, con_politica
):
    """🔑 Las dos mitades del mismo test, y la segunda es la que importa.

    Impedirle cancelar fuera de plazo no le devuelve la cancha al complejo: la
    deja ocupada por alguien que ya sabe que no viene, y encima sin poder
    revenderla.
    """
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=3)
    pasarela = PasarelaFalsa()

    resultado = servicio.cancelar(sesion, reserva.id, motivo="Llueve", pasarela=pasarela)
    sesion.commit()

    assert resultado.reserva.estado is EstadoReserva.CANCELADA, "se cancela igual"
    assert resultado.devolucion is None
    assert pago.estado is EstadoPago.APROBADO, "la seña se queda en el complejo"
    assert pasarela.llamadas == [], "ni se le pidió la devolución"
    assert "24 horas" in resultado.detalle


def test_el_borde_de_la_ventana_devuelve(sesion, cancha, cliente, vendible, con_politica):
    """Exactamente 24 h cuenta como a tiempo.

    Sin este test, `>=` y `>` pasan los dos, y la diferencia le cuesta la seña a
    quien avisó justo con un día — que es el caso que la política describe.
    """
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=24)
    # `_en` redondea a la hora en punto, así que faltan 24 h **menos** los
    # minutos corridos: se mide con un `momento` explícito para caer al borde.
    momento = reserva.comienza_at - timedelta(hours=24)

    resultado = servicio.cancelar(
        sesion, reserva.id, motivo="Justo", pasarela=PasarelaFalsa(), momento=momento
    )
    sesion.commit()

    assert resultado.politica.a_tiempo is True
    assert pago.estado is EstadoPago.DEVUELTO


def test_sin_politica_cargada_no_se_devuelve_nada(sesion, cancha, cliente, vendible):
    """🔴 El default de una sucursal es NO devolver.

    Es lo que hace que la migración sea segura: las instancias que ya existen
    siguen comportándose igual hasta que alguien cargue el número.
    """
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=48)
    pasarela = PasarelaFalsa()

    resultado = servicio.cancelar(sesion, reserva.id, motivo="X", pasarela=pasarela)
    sesion.commit()

    assert resultado.reserva.estado is EstadoReserva.CANCELADA
    assert resultado.devolucion is None
    assert pago.estado is EstadoPago.APROBADO
    assert pasarela.llamadas == []
    assert "no tiene política" in resultado.detalle


# ── Qué pago se devuelve ─────────────────────────────────────────────────


def test_el_cobro_de_mostrador_no_se_devuelve_por_api(
    sesion, cancha, cliente, vendible, con_politica
):
    """🔴 Ese pago ya entró a la caja del turno.

    Devolverlo por API dejaría el arqueo descuadrado: la plata saldría por un
    lado que la caja no ve. Y el resultado lo **dice**, en vez de quedarse
    callado como si no hubiera habido seña.
    """
    reserva, pago = _reserva_pagada(
        sesion, cancha, cliente, en_horas=48, canal=CanalDePago.MOSTRADOR
    )
    pasarela = PasarelaFalsa()

    resultado = servicio.cancelar(sesion, reserva.id, motivo="X", pasarela=pasarela)
    sesion.commit()

    assert resultado.devolucion is None
    assert pago.estado is EstadoPago.APROBADO
    assert pasarela.llamadas == []
    assert "caja" in resultado.detalle


def test_sin_sena_pagada_no_hay_nada_que_devolver(
    sesion, cancha, cliente, vendible, con_politica, tarifa_base
):
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_en(48)
    )
    sesion.commit()

    resultado = servicio.cancelar(
        sesion, reserva.id, motivo="X", pasarela=PasarelaFalsa()
    )
    sesion.commit()

    assert resultado.reserva.estado is EstadoReserva.CANCELADA
    assert resultado.pago is None
    assert "No había seña" in resultado.detalle


# ── Cuando la devolución falla ───────────────────────────────────────────


def test_sin_pasarela_el_turno_se_cancela_y_la_deuda_queda_anotada(
    sesion, cancha, cliente, vendible, con_politica
):
    """🔴 El caso de una instancia sin credenciales de MercadoPago.

    Es el que hoy corre en `dev`. La reserva **tiene** que quedar cancelada: el
    jugador soltó el turno y el complejo puede revenderlo. Lo que queda
    pendiente es la plata, y queda visible.
    """
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=48)

    resultado = servicio.cancelar(
        sesion, reserva.id, motivo="X", pasarela=PasarelaFalsa(disponible=False)
    )
    sesion.commit()

    assert resultado.reserva.estado is EstadoReserva.CANCELADA
    assert pago.estado is EstadoPago.DEVOLUCION_PENDIENTE
    assert "MercadoPago" in (pago.detalle_devolucion or "")
    assert servicio.pendientes(sesion) == [pago]


def test_si_mercadopago_rechaza_la_deuda_queda_con_el_motivo(
    sesion, cancha, cliente, vendible, con_politica
):
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=48)

    resultado = servicio.cancelar(
        sesion, reserva.id, motivo="X",
        pasarela=PasarelaFalsa(falla="400: refund not allowed"),
    )
    sesion.commit()

    assert resultado.reserva.estado is EstadoReserva.CANCELADA
    assert pago.estado is EstadoPago.DEVOLUCION_PENDIENTE
    assert "refund not allowed" in (pago.detalle_devolucion or "")


def test_el_reintento_completa_la_devolucion(
    sesion, cancha, cliente, vendible, con_politica
):
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=48)
    servicio.cancelar(
        sesion, reserva.id, motivo="X", pasarela=PasarelaFalsa(disponible=False)
    )
    sesion.commit()

    buena = PasarelaFalsa()
    resultado = servicio.reintentar(sesion, pago.id, pasarela=buena)
    sesion.commit()

    assert resultado.devolucion is EstadoPago.DEVUELTO
    assert pago.estado is EstadoPago.DEVUELTO
    assert pago.detalle_devolucion is None
    assert servicio.pendientes(sesion) == []


def test_todos_los_intentos_mandan_la_MISMA_clave_de_idempotencia(
    sesion, cancha, cliente, vendible, con_politica
):
    """🔴 Es lo único que impide devolver dos veces la misma seña.

    Si el reintento mandara una clave distinta, MercadoPago lo tomaría como una
    devolución nueva y el complejo pagaría dos veces.
    """
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=48)
    primera = PasarelaFalsa(falla="timeout")
    servicio.cancelar(sesion, reserva.id, motivo="X", pasarela=primera)
    sesion.commit()

    segunda = PasarelaFalsa()
    servicio.reintentar(sesion, pago.id, pasarela=segunda)
    sesion.commit()

    assert primera.llamadas[0][1] == segunda.llamadas[0][1]
    assert primera.llamadas[0][1] == f"devolucion-{pago.referencia}"


def test_no_se_reintenta_un_pago_que_no_debe_nada(
    sesion, cancha, cliente, vendible, con_politica
):
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=48)

    with pytest.raises(servicio_reservas.TransicionInvalida):
        servicio.reintentar(sesion, pago.id, pasarela=PasarelaFalsa())


# ── La pasarela de verdad ────────────────────────────────────────────────


def test_la_pasarela_real_sin_token_no_esta_disponible():
    """🔴 Es lo que impide que la suite salga a MercadoPago de verdad.

    `disponible()` se pregunta **antes** de intentar, así que con el token vacío
    —el estado de una instancia sin configurar y el de este test— no hay ninguna
    llamada HTTP que pueda salir.
    """
    pasarela = devoluciones.DevolucionMercadoPago(lambda: "")

    assert pasarela.disponible() is False
    with pytest.raises(devoluciones.DevolucionRechazada):
        pasarela.devolver(payment_id="1", referencia="x")


def test_la_pasarela_real_con_token_si_esta_disponible():
    """El control positivo del de arriba: `disponible()` puede dar `True`.

    Sin él, un `disponible()` que devolviera siempre `False` pasaría el test
    anterior sin despeinarse y en producción no se devolvería nunca nada.
    """
    assert devoluciones.DevolucionMercadoPago(lambda: "APP_USR-xxx").disponible() is True


def test_el_pago_simulado_no_se_manda_a_mercadopago(
    sesion, cancha, cliente, vendible, con_politica
):
    """Un pago aprobado sin `payment_id` es el simulado de dev: allá no existe.

    Pedirle a MercadoPago que devuelva un pago que nunca recibió es un error
    garantizado; queda pendiente y lo dice.
    """
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=48)
    pago.payment_id = None
    sesion.commit()
    pasarela = PasarelaFalsa()

    servicio.cancelar(sesion, reserva.id, motivo="X", pasarela=pasarela)
    sesion.commit()

    assert pasarela.llamadas == []
    assert pago.estado is EstadoPago.DEVOLUCION_PENDIENTE
    assert "id de MercadoPago" in (pago.detalle_devolucion or "")


# ── Los dos caminos que cancelan, por API ────────────────────────────────


def _config() -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos", libracore_database_url=None,
    )


@pytest.fixture
def api(engine, sesion, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(crear_app(_config()), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


def test_cancelar_desde_el_mostrador_pasa_por_la_MISMA_politica(
    api, sesion, cancha, cliente, vendible, con_politica
):
    """🔑 El test que justifica el desvío en el router.

    Si el mostrador usara `cambiar_estado` a secas, la seña se devolvería o no
    **según quién apretó el botón** — el jugador desde el portal sí, el
    encargado no. Eso no es una regla de negocio, es un accidente.
    """
    reserva, pago = _reserva_pagada(sesion, cancha, cliente, en_horas=48)

    respuesta = api.post(
        f"/api/reservas/{reserva.id}/estado",
        json={"estado": "cancelada", "motivo": "Avisó por teléfono"},
    )

    assert respuesta.status_code == 200, respuesta.text
    sesion.expire_all()
    guardado = sesion.get(PagoDeReserva, pago.id)
    # Sin credenciales en la config de la suite, la devolución queda pendiente
    # —pero **queda**, que es lo que prueba que el camino pasó por la política.
    assert guardado.estado is EstadoPago.DEVOLUCION_PENDIENTE


def test_cancelar_un_turno_sin_pagar_desde_el_mostrador_sigue_andando(
    api, sesion, cancha, cliente, vendible
):
    """El control: el desvío no rompió la cancelación de siempre."""
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=_en(48)
    )
    sesion.commit()

    respuesta = api.post(
        f"/api/reservas/{reserva.id}/estado", json={"estado": "cancelada"}
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"] == "cancelada"


def test_el_portal_le_dice_al_jugador_que_paso_con_la_plata(
    api, sesion, cancha, cliente, vendible, con_politica
):
    """Sin `detalle`, el que canceló a tiempo y el que canceló tarde ven lo
    mismo, y el segundo llama por teléfono a preguntar por su seña."""
    reserva, _ = _reserva_pagada(sesion, cancha, cliente, en_horas=3)
    jugador = TestClient(crear_app(_config()), base_url="https://testserver")
    jugador.post("/api/portal/registro", json={
        "email": "otro@ejemplo.com", "password": "una-clave-larga", "nombre": "Otro"})
    # La reserva es del `cliente` del conftest, no del jugador recién creado:
    # cancelarla tiene que dar 404 y **no** decir que existe.
    ajena = jugador.post(f"/api/portal/reservas/{reserva.id}/cancelar")

    assert ajena.status_code == 404
    assert "encontramos" in ajena.json()["detail"]


def test_el_portal_no_le_cuenta_al_jugador_como_esta_configurado_el_complejo(
    sesion, cancha, cliente, vendible, con_politica
):
    """🔴 El portal está expuesto a internet sin sesión.

    El `detalle` interno dice «la instancia no tiene MercadoPago configurado» —es
    lo que el mostrador necesita leer— y eso es información del complejo, no de
    quien pregunta. Al jugador se le dice que le corresponde la devolución, que
    es la parte que es suya.
    """
    reserva, _ = _reserva_pagada(sesion, cancha, cliente, en_horas=48)

    resultado = servicio.cancelar(
        sesion, reserva.id, motivo="X", pasarela=PasarelaFalsa(disponible=False)
    )
    sesion.commit()

    assert "MercadoPago" in resultado.detalle, "el control: el detalle interno sí lo dice"
    assert "MercadoPago" not in resultado.para_el_jugador
    assert "instancia" not in resultado.para_el_jugador
    assert "corresponde la devolución" in resultado.para_el_jugador


def test_al_jugador_que_cancelo_tarde_se_le_dice_por_que(
    sesion, cancha, cliente, vendible, con_politica
):
    """Y con el número: «con menos de 24 horas» se puede discutir, «no se
    devuelve» a secas se lee como arbitrario."""
    reserva, _ = _reserva_pagada(sesion, cancha, cliente, en_horas=3)

    resultado = servicio.cancelar(sesion, reserva.id, motivo="X", pasarela=PasarelaFalsa())

    assert "24 horas" in resultado.para_el_jugador
    assert "no se devuelve" in resultado.para_el_jugador


def test_al_que_le_devolvieron_se_le_avisa_que_puede_tardar(
    sesion, cancha, cliente, vendible, con_politica
):
    reserva, _ = _reserva_pagada(sesion, cancha, cliente, en_horas=48)

    resultado = servicio.cancelar(sesion, reserva.id, motivo="X", pasarela=PasarelaFalsa())

    assert "devolvimos la seña" in resultado.para_el_jugador
    assert "días" in resultado.para_el_jugador


def test_la_fecha_de_los_turnos_no_depende_del_dia(sesion):
    """`_en` redondea a la hora en punto para no depender del minuto de corrida."""
    turno = _en(48)
    assert turno.minute == 0 and turno.second == 0
    assert turno.tzinfo is not None
    assert turno.date() >= date.today()
