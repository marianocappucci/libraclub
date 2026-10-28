"""Aviso de seña por vencer, WhatsApp en modo registro y la configuración de avisos (ADR-029).

Igual que `test_avisos.py`: todo con un `momento` explícito y `created_at` / `vence_at` puestos a
mano. Un test que dependa de la hora a la que corre el CI no se puede reproducir.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from sqlalchemy import select, update

from app.config import Config
from app.main import crear_app
from app.models.avisos import Aviso
from app.models.enums import CanalAviso, EstadoAviso, EstadoReserva, ModoWhatsapp, TipoAviso
from app.models.reservas import EstadoPago, PagoDeReserva, Reserva
from app.servicios import avisos as servicio
from app.servicios import pagos as servicio_pagos
from app.servicios import reservas as servicio_reservas
from app.tiempo import TZ

#: El turno de todos los tests, igual que en `test_avisos.py`: martes 01-09-2026 a las 20:00.
CUANDO = datetime(2026, 9, 1, 20, 0, tzinfo=TZ)
#: «Ahora» de los tests de seña: 19:00, una hora antes del turno.
AHORA = datetime(2026, 9, 1, 19, 0, tzinfo=TZ)

USUARIO, CLAVE = "admin", "clave-de-prueba"


class Transporte:
    """Un canal que anota en vez de mandar. `simulado` es lo que cambia entre los dos usos."""

    def __init__(self, canal=CanalAviso.EMAIL, *, simulado=False, disponible=True):
        self.canal = canal
        self.simulado = simulado
        self._disponible = disponible
        self.enviados: list[tuple[str, str, str]] = []

    def disponible(self) -> bool:
        return self._disponible

    def enviar(self, *, destino: str, asunto: str, cuerpo: str) -> None:
        self.enviados.append((destino, asunto, cuerpo))


@pytest.fixture
def jugador(sesion, cliente):
    """El cliente del conftest (teléfono `2255-123456`), con email."""
    cliente.email = "jugador@ejemplo.com"
    sesion.commit()
    return cliente


def _avisos(sesion) -> list[Aviso]:
    return list(sesion.scalars(select(Aviso).order_by(Aviso.id)).all())


def _creada(sesion, reserva: Reserva, cuando: datetime) -> None:
    sesion.execute(update(Reserva).where(Reserva.id == reserva.id).values(created_at=cuando))
    sesion.commit()
    sesion.expire(reserva)


def _confirmada(sesion, cancha, jugador, *, creada=None, cuando=CUANDO) -> Reserva:
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=cuando,
        estado=EstadoReserva.CONFIRMADA,
    )
    sesion.commit()
    _creada(sesion, reserva, creada or AHORA - timedelta(minutes=5))
    return reserva


def _retenida(sesion, cancha, jugador, *, vence_en: timedelta, pago=EstadoPago.PENDIENTE):
    """Una provisoria del portal: turno retenido, con su pago, que vence `vence_en` después de AHORA."""
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=CUANDO,
        estado=EstadoReserva.PROVISORIA,
    )
    pago_ = servicio_pagos.crear_pago(sesion, reserva, Decimal("10000.00"))
    pago_.estado = pago
    reserva.vence_at = AHORA + vence_en
    sesion.commit()
    return reserva


# ── Seña por vencer ──────────────────────────────────────────────────────


def test_avisa_que_el_turno_se_libera_cuando_faltan_pocos_minutos(
    sesion, cancha, jugador, tarifa_base
):
    reserva = _retenida(sesion, cancha, jugador, vence_en=timedelta(minutes=6))
    transporte = Transporte()

    resumen = servicio.despachar(sesion, transporte, AHORA)
    sesion.commit()

    assert resumen.enviados == 1
    (destino, asunto, cuerpo) = transporte.enviados[0]
    assert destino == "jugador@ejemplo.com"
    assert asunto == "Tu turno se libera a las 19:06: Cancha 1, 01-09-2026 20:00"
    assert "retenido hasta las 19:06" in cuerpo
    assert "A pagar: $10.000,00" in cuerpo
    assert "Mis reservas" in cuerpo
    (guardado,) = _avisos(sesion)
    assert guardado.tipo is TipoAviso.SENA_POR_VENCER and guardado.reserva_id == reserva.id
    assert guardado.estado is EstadoAviso.ENVIADO and guardado.horas_antes is None


def test_no_avisa_si_falta_mucho(sesion, cancha, jugador, tarifa_base):
    """Al minuto de empezar a pagar no hay nada que avisar: le quedan 14."""
    _retenida(sesion, cancha, jugador, vence_en=timedelta(minutes=14))

    assert servicio.despachar(sesion, Transporte(), AHORA).enviados == 0


def test_no_avisa_un_turno_que_ya_se_libero(sesion, cancha, jugador, tarifa_base):
    """🔴 «Se libera en unos minutos» cuando ya se liberó es peor que no mandar nada."""
    _retenida(sesion, cancha, jugador, vence_en=-timedelta(minutes=1))

    assert servicio.despachar(sesion, Transporte(), AHORA).enviados == 0


@pytest.mark.parametrize("pago", [EstadoPago.APROBADO, EstadoPago.RECHAZADO, EstadoPago.VENCIDO])
def test_solo_avisa_si_el_pago_sigue_pendiente(sesion, cancha, jugador, tarifa_base, pago):
    """Si ya no hay un pago en curso, no hay seña que se esté pagando."""
    _retenida(sesion, cancha, jugador, vence_en=timedelta(minutes=6), pago=pago)

    assert servicio.despachar(sesion, Transporte(), AHORA).enviados == 0


def test_una_provisoria_sin_pago_no_se_avisa(sesion, cancha, jugador, tarifa_base):
    """La retención del mostrador no pasa por MercadoPago: no hay pago pendiente que recordar."""
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=CUANDO,
        estado=EstadoReserva.PROVISORIA,
    )
    reserva.vence_at = AHORA + timedelta(minutes=6)
    sesion.commit()

    assert servicio.despachar(sesion, Transporte(), AHORA).enviados == 0


def test_no_se_repite(sesion, cancha, jugador, tarifa_base):
    _retenida(sesion, cancha, jugador, vence_en=timedelta(minutes=7))
    transporte = Transporte()

    servicio.despachar(sesion, transporte, AHORA)
    sesion.commit()
    segunda = servicio.despachar(sesion, transporte, AHORA + timedelta(minutes=5))
    sesion.commit()

    assert segunda.enviados == 0 and len(transporte.enviados) == 1


def test_el_cron_cada_5_minutos_siempre_avisa_antes_de_que_venza(
    sesion, cancha, jugador, tarifa_base
):
    """🔑 Por qué la ventana son 8 minutos y no 5.

    Se simula el cron (un tick cada 5 minutos) con todas las fases posibles respecto de la
    retención de 15 minutos. El aviso tiene que salir **siempre**, y al menos 3 minutos antes de
    que el turno se libere: con una ventana igual al período del cron, algunas fases lo mandan
    justo cuando ya se perdió.
    """
    assert servicio.VENTANA_DE_SENA > timedelta(minutes=5), "la ventana tiene que superar al cron"
    assert servicio.VENTANA_DE_SENA < servicio_reservas.VENCIMIENTO_PROVISORIA

    for desfase in range(5):
        sesion.execute(Aviso.__table__.delete())
        sesion.execute(PagoDeReserva.__table__.delete())
        sesion.execute(Reserva.__table__.delete())
        sesion.commit()
        # La retención arranca `desfase` minutos después del último tick del cron.
        inicio = AHORA + timedelta(minutes=desfase)
        reserva = _retenida(sesion, cancha, jugador, vence_en=timedelta(minutes=desfase + 15))
        assert reserva.vence_at - inicio == servicio_reservas.VENCIMIENTO_PROVISORIA
        transporte = Transporte()

        salio_a = None
        for minuto in range(0, 40, 5):
            tick = AHORA + timedelta(minutes=minuto)
            if tick >= reserva.vence_at:
                break
            if servicio.despachar(sesion, transporte, tick).enviados:
                salio_a = tick
                break
            sesion.commit()
        sesion.commit()

        assert salio_a is not None, f"desfase {desfase}: nunca avisó"
        assert reserva.vence_at - salio_a >= timedelta(minutes=3), (
            f"desfase {desfase}: avisó a {reserva.vence_at - salio_a} del vencimiento"
        )


def test_el_aviso_de_sena_no_habilita_la_cancelacion(sesion, cancha, jugador, tarifa_base):
    """🔴 Una provisoria que venció sin pagarse no recibe «se canceló tu reserva».

    La cancelación se avisa sólo si la **confirmación** salió. El aviso de seña es de otro tipo
    y no cuenta: si contara, el jugador que no llegó a pagar se enteraría de que «perdió» un
    turno que nunca tuvo.
    """
    reserva = _retenida(sesion, cancha, jugador, vence_en=timedelta(minutes=6))
    transporte = Transporte()
    servicio.despachar(sesion, transporte, AHORA)
    sesion.commit()

    servicio_reservas.vencer_provisorias(sesion, AHORA + timedelta(minutes=7))
    sesion.commit()
    sesion.expire(reserva)
    resumen = servicio.despachar(sesion, transporte, AHORA + timedelta(minutes=8))
    sesion.commit()

    assert reserva.estado is EstadoReserva.CANCELADA
    assert resumen.enviados == 0
    assert [a.tipo for a in _avisos(sesion)] == [TipoAviso.SENA_POR_VENCER]


# ── WhatsApp en modo registro ────────────────────────────────────────────


def test_apagado_no_registra_nada(sesion, cancha, jugador, tarifa_base):
    reserva = _confirmada(sesion, cancha, jugador)
    transporte = servicio.TransporteWhatsAppRegistro(ModoWhatsapp.APAGADO)

    resumen = servicio.despachar(sesion, transporte, AHORA)
    sesion.commit()

    assert reserva.id and not transporte.disponible()
    assert str(resumen) == "enviados: 0 · fallidos: 0 · omitidos: 0"
    assert _avisos(sesion) == []


def test_en_modo_registro_el_mensaje_queda_anotado_y_no_sale(
    sesion, cancha, jugador, tarifa_base
):
    _confirmada(sesion, cancha, jugador)
    transporte = servicio.TransporteWhatsAppRegistro(ModoWhatsapp.REGISTRO)

    resumen = servicio.despachar(sesion, transporte, AHORA)
    sesion.commit()

    assert (resumen.enviados, resumen.registrados) == (0, 1)
    assert "registrados: 1" in str(resumen)
    (guardado,) = _avisos(sesion)
    assert guardado.canal is CanalAviso.WHATSAPP
    # 🔴 `registrado` y **no** `enviado`: ese estado dice que alguien lo recibió.
    assert guardado.estado is EstadoAviso.REGISTRADO
    assert guardado.enviado_at is None
    assert guardado.detalle == servicio.DETALLE_REGISTRADO
    # El teléfono `2255-123456` (característica 2255, sin el 0 ni el 15) sale con país y el 9 del celular.
    assert guardado.destino == "5492255123456"
    assert guardado.asunto is None
    assert guardado.cuerpo.startswith("*Turno confirmado: Cancha 1, 01-09-2026 20:00*\n\n")
    assert "Hola Juan Pérez," in guardado.cuerpo


def test_el_registro_no_se_repite_con_el_mismo_transporte(sesion, cancha, jugador, tarifa_base):
    _confirmada(sesion, cancha, jugador)
    transporte = servicio.TransporteWhatsAppRegistro(ModoWhatsapp.REGISTRO)

    servicio.despachar(sesion, transporte, AHORA)
    sesion.commit()
    segunda = servicio.despachar(sesion, transporte, AHORA + timedelta(minutes=5))
    sesion.commit()

    assert segunda.registrados == 0 and len(_avisos(sesion)) == 1


def test_un_proveedor_real_manda_lo_que_solo_se_registro(sesion, cancha, jugador, tarifa_base):
    """🔑 El día que se conecte WhatsApp de verdad, lo anotado en modo prueba no se da por mandado.

    Es lo que justifica que `registrado` no sea terminal para un transporte real: el mensaje
    nunca llegó a nadie.
    """
    reserva = _confirmada(sesion, cancha, jugador)
    servicio.despachar(sesion, servicio.TransporteWhatsAppRegistro(ModoWhatsapp.REGISTRO), AHORA)
    sesion.commit()
    real = Transporte(CanalAviso.WHATSAPP, simulado=False)

    resumen = servicio.despachar(sesion, real, AHORA + timedelta(minutes=5))
    sesion.commit()

    assert resumen.enviados == 1 and len(real.enviados) == 1
    (guardado,) = _avisos(sesion)
    assert guardado.reserva_id == reserva.id
    assert guardado.estado is EstadoAviso.ENVIADO and guardado.intentos == 2
    assert guardado.enviado_at is not None and guardado.detalle is None


def test_el_registro_no_pisa_lo_que_ya_se_mando(sesion, cancha, jugador, tarifa_base):
    _confirmada(sesion, cancha, jugador)
    servicio.despachar(sesion, Transporte(CanalAviso.WHATSAPP), AHORA)
    sesion.commit()

    resumen = servicio.despachar(
        sesion, servicio.TransporteWhatsAppRegistro(ModoWhatsapp.REGISTRO), AHORA
    )
    sesion.commit()

    assert resumen.registrados == 0
    assert [a.estado for a in _avisos(sesion)] == [EstadoAviso.ENVIADO]


def test_mail_y_whatsapp_son_avisos_distintos_del_mismo_turno(sesion, cancha, jugador, tarifa_base):
    _confirmada(sesion, cancha, jugador)

    servicio.despachar(sesion, Transporte(CanalAviso.EMAIL), AHORA)
    servicio.despachar(sesion, servicio.TransporteWhatsAppRegistro(ModoWhatsapp.REGISTRO), AHORA)
    sesion.commit()

    assert sorted(a.canal.value for a in _avisos(sesion)) == ["email", "whatsapp"]


def test_sin_telefono_reconocible_el_aviso_se_omite_con_motivo(sesion, cancha, jugador, tarifa_base):
    jugador.telefono = "12345"
    sesion.commit()
    _confirmada(sesion, cancha, jugador)

    resumen = servicio.despachar(
        sesion, servicio.TransporteWhatsAppRegistro(ModoWhatsapp.REGISTRO), AHORA
    )
    sesion.commit()

    assert resumen.omitidos == 1 and resumen.registrados == 0
    (guardado,) = _avisos(sesion)
    assert guardado.estado is EstadoAviso.OMITIDO and guardado.destino == ""
    assert guardado.detalle == "El cliente no tiene un teléfono que WhatsApp reconozca."


def test_el_cliente_que_no_quiere_avisos_no_recibe_whatsapp(sesion, cancha, jugador, tarifa_base):
    jugador.acepta_avisos = False
    sesion.commit()
    _confirmada(sesion, cancha, jugador)

    servicio.despachar(sesion, servicio.TransporteWhatsAppRegistro(ModoWhatsapp.REGISTRO), AHORA)
    sesion.commit()

    (guardado,) = _avisos(sesion)
    assert guardado.estado is EstadoAviso.OMITIDO
    assert guardado.detalle == "El cliente pidió no recibir avisos."


def test_la_cancelacion_por_whatsapp_dice_mensaje_y_la_de_mail_dice_mail(
    sesion, cancha, jugador, tarifa_base
):
    reserva = _confirmada(sesion, cancha, jugador)
    mail, wsp = Transporte(CanalAviso.EMAIL), servicio.TransporteWhatsAppRegistro(ModoWhatsapp.REGISTRO)
    for t in (mail, wsp):
        servicio.despachar(sesion, t, AHORA)
    sesion.commit()
    servicio_reservas.cambiar_estado(sesion, reserva.id, EstadoReserva.CANCELADA, motivo="Lluvia")
    sesion.commit()

    for t in (mail, wsp):
        servicio.despachar(sesion, t, AHORA + timedelta(minutes=10))
    sesion.commit()

    cancelaciones = {
        a.canal: a for a in _avisos(sesion) if a.tipo is TipoAviso.CANCELACION
    }
    assert set(cancelaciones) == {CanalAviso.EMAIL, CanalAviso.WHATSAPP}
    assert "respondé este mail" in cancelaciones[CanalAviso.EMAIL].cuerpo
    assert "respondé este mensaje" in cancelaciones[CanalAviso.WHATSAPP].cuerpo
    assert cancelaciones[CanalAviso.WHATSAPP].estado is EstadoAviso.REGISTRADO
    assert "Motivo: Lluvia" in cancelaciones[CanalAviso.WHATSAPP].cuerpo


def test_un_proveedor_real_no_cancela_lo_que_solo_se_registro(sesion, cancha, jugador, tarifa_base):
    """Si la confirmación nunca llegó, avisar la cancelación sería hablar de un turno que el
    jugador no sabía que tenía."""
    reserva = _confirmada(sesion, cancha, jugador)
    servicio.despachar(sesion, servicio.TransporteWhatsAppRegistro(ModoWhatsapp.REGISTRO), AHORA)
    sesion.commit()
    servicio_reservas.cambiar_estado(sesion, reserva.id, EstadoReserva.CANCELADA)
    sesion.commit()
    real = Transporte(CanalAviso.WHATSAPP)

    # Sólo cuenta lo que ya existe: la confirmación registrada se manda (intento 2), la cancelación no.
    servicio.despachar(sesion, real, AHORA + timedelta(minutes=10))
    sesion.commit()

    assert all("cancel" not in (a[1] or "").lower() for a in real.enviados)


def test_tambien_avisa_la_sena_por_whatsapp(sesion, cancha, jugador, tarifa_base):
    _retenida(sesion, cancha, jugador, vence_en=timedelta(minutes=6))

    servicio.despachar(sesion, servicio.TransporteWhatsAppRegistro(ModoWhatsapp.REGISTRO), AHORA)
    sesion.commit()

    (guardado,) = _avisos(sesion)
    assert guardado.tipo is TipoAviso.SENA_POR_VENCER and guardado.canal is CanalAviso.WHATSAPP
    assert guardado.cuerpo.startswith("*Tu turno se libera a las 19:06")


def test_construir_transportes_arma_uno_por_canal(sesion):
    transportes = servicio.construir_transportes(sesion, lambda: None)
    assert [t.canal for t in transportes] == [CanalAviso.EMAIL, CanalAviso.WHATSAPP]
    assert [t.simulado for t in transportes] == [False, True]
    assert not transportes[1].disponible(), "sin configuración, WhatsApp está apagado"

    servicio.guardar_configuracion(
        sesion, servicio.ConfiguracionDeAvisos(whatsapp=ModoWhatsapp.REGISTRO)
    )
    assert servicio.construir_transportes(sesion, lambda: None)[1].disponible()


# ── El teléfono ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("11 5555-1234", "5491155551234"),
        ("(011) 5555-1234", "5491155551234"),
        ("011 15 5555-1234", "5491155551234"),
        ("15 5555-1234 ", ""),  # sin característica no se sabe de dónde es
        ("+54 9 11 5555 1234", "5491155551234"),
        ("+54 11 5555 1234", "5491155551234"),
        ("0054 9 11 5555 1234", "5491155551234"),
        ("2255-123456", "5492255123456"),
        ("+598 99 123 456", "59899123456"),  # otro país: pasa tal cual
        ("5555-1234", ""),  # 8 dígitos
        ("12345", ""),
        ("", ""),
        (None, ""),
        # El 15 del interior no se puede ubicar solo: ante la duda, vacío y no un número inventado.
        ("2342 15 123456", ""),
    ],
)
def test_telefono_para_whatsapp(texto, esperado):
    assert servicio.telefono_para_whatsapp(texto) == esperado


# ── La configuración ─────────────────────────────────────────────────────


def test_sin_fila_rigen_los_defaults(sesion):
    assert servicio.configuracion(sesion) == servicio.ConfiguracionDeAvisos()
    assert servicio.configuracion(sesion).whatsapp is ModoWhatsapp.APAGADO


@pytest.mark.parametrize("apagado", ["confirmacion", "recordatorio"])
def test_un_tipo_apagado_no_sale_y_el_otro_sigue(sesion, cancha, jugador, tarifa_base, apagado):
    """Cada tipo se apaga solo. Con dos turnos, uno que pide recordatorio y otro que pide confirmación."""
    momento = CUANDO - timedelta(hours=20)
    # Cargado hace tres días: le toca el recordatorio de 24 h, no la confirmación.
    _confirmada(sesion, cancha, jugador, creada=CUANDO - timedelta(days=3))
    # Recién cargado: le toca la confirmación; su turno es más tarde, así que no entra en las 24 h.
    _confirmada(
        sesion, cancha, jugador, cuando=CUANDO + timedelta(hours=2),
        creada=momento - timedelta(minutes=5),
    )
    transporte = Transporte()

    servicio.despachar(sesion, transporte, momento)
    sesion.commit()
    con_todo = {a.tipo.value for a in _avisos(sesion)}
    sesion.execute(Aviso.__table__.delete())
    servicio.guardar_configuracion(sesion, servicio.ConfiguracionDeAvisos(**{apagado: False}))
    sesion.commit()
    servicio.despachar(sesion, transporte, momento)
    sesion.commit()
    con_uno_apagado = {a.tipo.value for a in _avisos(sesion)}

    assert con_todo == {"confirmacion", "recordatorio"}, "el control: sin apagar salen los dos"
    assert con_uno_apagado == {"confirmacion", "recordatorio"} - {apagado}


def test_la_sena_apagada_no_sale(sesion, cancha, jugador, tarifa_base):
    _retenida(sesion, cancha, jugador, vence_en=timedelta(minutes=6))
    servicio.guardar_configuracion(
        sesion, servicio.ConfiguracionDeAvisos(sena_por_vencer=False)
    )
    sesion.commit()

    assert servicio.despachar(sesion, Transporte(), AHORA).enviados == 0


def test_la_cancelacion_apagada_no_sale(sesion, cancha, jugador, tarifa_base):
    reserva = _confirmada(sesion, cancha, jugador)
    transporte = Transporte()
    servicio.despachar(sesion, transporte, AHORA)
    sesion.commit()
    servicio_reservas.cambiar_estado(sesion, reserva.id, EstadoReserva.CANCELADA)
    servicio.guardar_configuracion(sesion, servicio.ConfiguracionDeAvisos(cancelacion=False))
    sesion.commit()

    assert servicio.despachar(sesion, transporte, AHORA + timedelta(minutes=10)).enviados == 0


# ── La API ───────────────────────────────────────────────────────────────


def _config() -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos", libracore_database_url=None,
    )


@pytest.fixture
def clientes_api(engine, sesion, monkeypatch):
    """Un admin y un encargado, cada uno con su sesión."""
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    app = crear_app(_config())
    app.state.users.create(username="encargado", name="Encargado", password=CLAVE, role="staff")
    admin = TestClient(app, base_url="https://testserver")
    assert admin.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    encargado = TestClient(app, base_url="https://testserver")
    assert encargado.post(
        "/auth/login", json={"username": "encargado", "password": CLAVE}
    ).status_code == 200
    yield admin, encargado
    AuthBase.metadata.drop_all(engine)


def test_la_api_devuelve_los_defaults_y_guarda_la_configuracion(clientes_api, sesion):
    admin, _ = clientes_api
    assert admin.get("/api/avisos/config").json() == {
        "whatsapp": "apagado", "confirmacion": True, "recordatorio": True,
        "cancelacion": True, "sena_por_vencer": True,
    }

    nueva = {
        "whatsapp": "registro", "confirmacion": True, "recordatorio": False,
        "cancelacion": True, "sena_por_vencer": False,
    }
    assert admin.put("/api/avisos/config", json=nueva).json() == nueva
    assert admin.get("/api/avisos/config").json() == nueva
    leida = servicio.configuracion(sesion)
    assert leida.whatsapp is ModoWhatsapp.REGISTRO and not leida.recordatorio
    # Guardar de nuevo actualiza la única fila; no crea otra.
    assert admin.put("/api/avisos/config", json={**nueva, "whatsapp": "apagado"}).status_code == 200
    assert servicio.configuracion(sesion).whatsapp is ModoWhatsapp.APAGADO


def test_el_encargado_ve_la_configuracion_pero_no_la_cambia(clientes_api):
    """Apagar la confirmación o prender WhatsApp cambia lo que reciben los clientes: es de admin."""
    admin, encargado = clientes_api
    assert encargado.get("/api/avisos/config").status_code == 200
    r = encargado.put("/api/avisos/config", json=admin.get("/api/avisos/config").json())
    assert r.status_code == 403


def test_la_api_rechaza_un_modo_que_no_existe(clientes_api):
    admin, _ = clientes_api
    cuerpo = {**admin.get("/api/avisos/config").json(), "whatsapp": "evolution"}
    assert admin.put("/api/avisos/config", json=cuerpo).status_code == 422


def test_el_registro_trae_lo_que_salio_y_lo_que_solo_se_registro(
    clientes_api, sesion, cancha, jugador, tarifa_base
):
    _, encargado = clientes_api
    _confirmada(sesion, cancha, jugador)
    servicio.despachar(sesion, Transporte(), AHORA)
    servicio.despachar(sesion, servicio.TransporteWhatsAppRegistro(ModoWhatsapp.REGISTRO), AHORA)
    sesion.commit()

    todos = encargado.get("/api/avisos/registro")
    solo_wsp = encargado.get("/api/avisos/registro?canal=whatsapp").json()
    solo_enviados = encargado.get("/api/avisos/registro?estado=enviado").json()

    assert todos.status_code == 200, todos.text
    assert {(a["canal"], a["estado"]) for a in todos.json()} == {
        ("email", "enviado"), ("whatsapp", "registrado"),
    }
    (wsp,) = solo_wsp
    assert wsp["destino"] == "5492255123456" and wsp["cancha"] == "Cancha 1"
    assert wsp["tipo"] == "confirmacion" and wsp["cuerpo"].startswith("*Turno confirmado")
    assert [a["canal"] for a in solo_enviados] == ["email"]


def test_el_registro_acota_el_limite(clientes_api):
    admin, _ = clientes_api
    assert admin.get("/api/avisos/registro?limite=0").status_code == 422
    assert admin.get("/api/avisos/registro?limite=501").status_code == 422
