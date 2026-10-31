"""Un aviso, un canal (addendum de ADR-030; libracore ADR-090, v1.204.0).

La decisión del humano (2026-10-28): un aviso sale por **un solo canal**, WhatsApp si el cliente tiene un teléfono
válido y WhatsApp está disponible (modo registro o Evolution), si no mail; si WhatsApp lo da por perdido, cae a mail con
la misma clave; y lo que ya salió por un canal no sale por el otro aunque la configuración cambie. La decisión es de
`libracore.avisos.avisar`; lo que se mide acá es el enganche de LibraClub:

- que `barrer` trabaja con **los dos canales a la vez** y le deja el reparto al motor;
- que lo que sigue siendo de LibraClub se mantiene: los interruptores por tipo, `acepta_avisos` y la regla «la
  cancelación exige que la confirmación haya salido», que ahora cuenta una confirmación salida por **cualquiera** de
  los dos canales;
- que `pendientes` no devuelve dos veces el mismo aviso ni lo recalcula en cada barrida.

Nada real sale: los proveedores son los dobles de `tests/avisos_apoyo.py` y el `ProveedorRegistro` del motor.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from libracore.avisos import MAX_INTENTOS, ProveedorApagado, ProveedorRegistro
from sqlalchemy import update

from app.models.enums import CanalAviso, EstadoReserva, TipoAviso
from app.models.maestros import Cliente
from app.models.reservas import Reserva
from app.servicios import avisos as servicio
from app.servicios import reservas as servicio_reservas
from app.tiempo import TZ
from tests.avisos_apoyo import Guardado, ProveedorFalso, guardados

#: El turno de todos los tests: martes 01-09-2026 a las 20:00. «Ahora» es 19:00 y la reserva se cargó 5 minutos antes.
CUANDO = datetime(2026, 9, 1, 20, 0, tzinfo=TZ)
AHORA = datetime(2026, 9, 1, 19, 0, tzinfo=TZ)

EMAIL, WHATSAPP = CanalAviso.EMAIL, CanalAviso.WHATSAPP


@pytest.fixture
def jugador(sesion, cliente, motor):
    """El cliente del conftest (teléfono `2255-123456`, que WhatsApp reconoce), con email: tiene los dos canales."""
    cliente.email = "jugador@ejemplo.com"
    sesion.commit()
    return cliente


def _confirmada(sesion, cancha, jugador, *, cuando=CUANDO) -> Reserva:
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=cuando, estado=EstadoReserva.CONFIRMADA,
    )
    sesion.commit()
    sesion.execute(update(Reserva).where(Reserva.id == reserva.id).values(created_at=AHORA - timedelta(minutes=5)))
    sesion.commit()
    sesion.expire(reserva)
    return reserva


def _barrer(sesion, proveedores, momento=AHORA):
    resumen = servicio.barrer(sesion, proveedores, momento)
    sesion.commit()
    return resumen


def _cancelar(sesion, reserva: Reserva) -> None:
    servicio_reservas.cambiar_estado(sesion, reserva.id, EstadoReserva.CANCELADA, motivo="Lluvia")
    sesion.commit()


def _por_tipo(tipo: TipoAviso) -> list[Guardado]:
    return [g for g in guardados() if g.tipo is tipo]


def _canales(tipo: TipoAviso) -> list[tuple[str, str]]:
    """`(canal, estado)` de las filas de ese tipo, en el orden en que se anotaron."""
    return [(g.canal.value, getattr(g.estado, "value", g.estado)) for g in _por_tipo(tipo)]


# ── El reparto: WhatsApp si se puede, si no mail ─────────────────────────────────────────────────────────────────────


def test_con_telefono_y_whatsapp_en_modo_registro_sale_solo_por_whatsapp_y_no_hay_mail(
    sesion, cancha, jugador, tarifa_base
):
    """El caso del humano: WhatsApp en registro anota y **no sale ningún mail**."""
    _confirmada(sesion, cancha, jugador)
    mail = ProveedorFalso(EMAIL)

    resumen = _barrer(sesion, {"email": mail, "whatsapp": ProveedorRegistro()})

    assert mail.enviados == []
    assert resumen.registrados == 1 and resumen.enviados == 0
    assert _canales(TipoAviso.CONFIRMACION) == [("whatsapp", "registrado")]
    (fila,) = guardados()
    assert fila.destino == "5492255123456" and fila.cuerpo.startswith("*Turno confirmado")


def test_con_telefono_y_whatsapp_real_sale_solo_por_whatsapp(sesion, cancha, jugador, tarifa_base):
    _confirmada(sesion, cancha, jugador)
    mail, wsp = ProveedorFalso(EMAIL), ProveedorFalso(WHATSAPP)

    resumen = _barrer(sesion, {"email": mail, "whatsapp": wsp})

    assert resumen.enviados == 1
    assert mail.enviados == []
    assert [d for d, _, _ in wsp.enviados] == ["5492255123456"]
    assert _canales(TipoAviso.CONFIRMACION) == [("whatsapp", "enviado")]


def test_sin_telefono_sale_por_mail_y_deja_anotado_por_que_no_salio_por_whatsapp(
    sesion, cancha, jugador, tarifa_base
):
    jugador.telefono = None
    sesion.commit()
    _confirmada(sesion, cancha, jugador)
    mail, wsp = ProveedorFalso(EMAIL), ProveedorFalso(WHATSAPP)

    resumen = _barrer(sesion, {"email": mail, "whatsapp": wsp})

    assert resumen.enviados == 1 and resumen.omitidos == 1
    assert wsp.enviados == [] and [d for d, _, _ in mail.enviados] == ["jugador@ejemplo.com"]
    assert _canales(TipoAviso.CONFIRMACION) == [("whatsapp", "omitido"), ("email", "enviado")]


def test_con_un_telefono_que_whatsapp_no_reconoce_sale_por_mail(sesion, cancha, jugador, tarifa_base):
    jugador.telefono = "12345"
    sesion.commit()
    _confirmada(sesion, cancha, jugador)
    mail = ProveedorFalso(EMAIL)

    _barrer(sesion, {"email": mail, "whatsapp": ProveedorRegistro()})

    assert len(mail.enviados) == 1
    assert _canales(TipoAviso.CONFIRMACION) == [("whatsapp", "omitido"), ("email", "enviado")]


def test_con_whatsapp_apagado_sale_por_mail_y_no_se_escribe_nada_de_whatsapp(sesion, cancha, jugador, tarifa_base):
    _confirmada(sesion, cancha, jugador)
    mail = ProveedorFalso(EMAIL)

    resumen = _barrer(sesion, {"email": mail, "whatsapp": ProveedorApagado()})

    assert resumen.enviados == 1 and resumen.omitidos == 0
    assert _canales(TipoAviso.CONFIRMACION) == [("email", "enviado")]


def test_si_no_hay_ningun_canal_disponible_no_se_arma_ni_se_anota_nada(sesion, cancha, jugador, tarifa_base):
    _confirmada(sesion, cancha, jugador)

    resumen = _barrer(sesion, {"email": ProveedorFalso(EMAIL, disponible=False), "whatsapp": ProveedorApagado()})

    assert str(resumen) == "enviados: 0 · fallidos: 0 · omitidos: 0"
    assert guardados() == []


def test_el_cliente_sin_telefono_ni_mail_queda_omitido_en_los_dos_y_no_se_vuelve_a_plantear(
    sesion, cancha, jugador, tarifa_base
):
    jugador.telefono, jugador.email = None, None
    sesion.commit()
    _confirmada(sesion, cancha, jugador)
    proveedores = {"email": ProveedorFalso(EMAIL), "whatsapp": ProveedorFalso(WHATSAPP)}

    primera = _barrer(sesion, proveedores)
    segunda = _barrer(sesion, proveedores, AHORA + timedelta(minutes=5))

    assert primera.omitidos == 2 and segunda.omitidos == 0 and segunda.repetidos == 0
    assert _canales(TipoAviso.CONFIRMACION) == [("whatsapp", "omitido"), ("email", "omitido")]


# ── Cuando WhatsApp lo da por perdido, cae a mail con la misma clave ────────────────────────────────────────────────


def test_un_rechazado_de_whatsapp_cae_a_mail_con_la_misma_clave(sesion, cancha, jugador, tarifa_base):
    """El número no tiene WhatsApp (permanente): el cliente igual se entera, por mail."""
    reserva = _confirmada(sesion, cancha, jugador)
    mail, wsp = ProveedorFalso(EMAIL), ProveedorFalso(WHATSAPP, rechaza="El número no tiene WhatsApp.")

    resumen = _barrer(sesion, {"email": mail, "whatsapp": wsp})

    assert resumen.rechazados == 1 and resumen.enviados == 1
    assert len(mail.enviados) == 1
    assert _canales(TipoAviso.CONFIRMACION) == [("whatsapp", "rechazado"), ("email", "enviado")]
    assert {g.clave for g in guardados()} == {f"reserva:{reserva.id}:confirmacion:-"}


def test_un_rechazado_no_vuelve_a_intentarse_ni_repite_el_mail_en_las_corridas_siguientes(
    sesion, cancha, jugador, tarifa_base
):
    _confirmada(sesion, cancha, jugador)
    mail, wsp = ProveedorFalso(EMAIL), ProveedorFalso(WHATSAPP, rechaza="El número no tiene WhatsApp.")
    proveedores = {"email": mail, "whatsapp": wsp}
    _barrer(sesion, proveedores)

    for minutos in (5, 10):
        resumen = _barrer(sesion, proveedores, AHORA + timedelta(minutes=minutos))
        assert resumen.enviados == 0 and resumen.repetidos == 0 and resumen.rechazados == 0

    assert len(mail.enviados) == 1 and wsp.enviados == []


def test_un_whatsapp_fallido_se_reintenta_y_al_agotar_los_intentos_cae_a_mail(sesion, cancha, jugador, tarifa_base):
    """Mientras le quedan intentos sigue por WhatsApp (no manda el mail a la primera falla); agotados, sale por mail."""
    _confirmada(sesion, cancha, jugador)
    mail, wsp = ProveedorFalso(EMAIL), ProveedorFalso(WHATSAPP, falla="Evolution no responde")
    proveedores = {"email": mail, "whatsapp": wsp}

    _barrer(sesion, proveedores, AHORA)
    assert mail.enviados == [], "con intentos por delante todavía no se pasa al mail"
    for i in range(1, MAX_INTENTOS):
        _barrer(sesion, proveedores, AHORA + timedelta(minutes=5 * i))

    assert len(mail.enviados) == 1
    assert _canales(TipoAviso.CONFIRMACION) == [("whatsapp", "fallido"), ("email", "enviado")]
    assert guardados()[0].intentos == MAX_INTENTOS


def test_un_whatsapp_fallido_que_se_recupera_no_manda_mail(sesion, cancha, jugador, tarifa_base):
    _confirmada(sesion, cancha, jugador)
    mail = ProveedorFalso(EMAIL)
    _barrer(sesion, {"email": mail, "whatsapp": ProveedorFalso(WHATSAPP, falla="timeout")})
    bueno = ProveedorFalso(WHATSAPP)

    resumen = _barrer(sesion, {"email": mail, "whatsapp": bueno}, AHORA + timedelta(minutes=5))

    assert resumen.enviados == 1 and len(bueno.enviados) == 1 and mail.enviados == []
    assert _canales(TipoAviso.CONFIRMACION) == [("whatsapp", "enviado")]


# ── Lo que ya salió por un canal no sale por el otro, aunque cambie la configuración ────────────────────────────────


def test_lo_que_salio_por_mail_no_sale_por_whatsapp_cuando_se_prende_whatsapp(sesion, cancha, jugador, tarifa_base):
    """Primera corrida con WhatsApp apagado (sale por mail); segunda con WhatsApp en registro y Evolution."""
    _confirmada(sesion, cancha, jugador)
    mail = ProveedorFalso(EMAIL)
    _barrer(sesion, {"email": mail, "whatsapp": ProveedorApagado()})

    for whatsapp in (ProveedorRegistro(), ProveedorFalso(WHATSAPP)):
        resumen = _barrer(sesion, {"email": mail, "whatsapp": whatsapp}, AHORA + timedelta(minutes=5))
        assert (resumen.enviados, resumen.registrados, resumen.repetidos) == (0, 0, 0)
        assert getattr(whatsapp, "enviados", []) == []

    assert len(mail.enviados) == 1
    assert _canales(TipoAviso.CONFIRMACION) == [("email", "enviado")]


def test_lo_que_salio_por_whatsapp_no_sale_por_mail_cuando_se_apaga_whatsapp(sesion, cancha, jugador, tarifa_base):
    """Al revés: la primera sale por WhatsApp; después se apaga, y el mail no se manda un aviso que ya salió."""
    _confirmada(sesion, cancha, jugador)
    mail, wsp = ProveedorFalso(EMAIL), ProveedorFalso(WHATSAPP)
    _barrer(sesion, {"email": mail, "whatsapp": wsp})

    resumen = _barrer(sesion, {"email": mail, "whatsapp": ProveedorApagado()}, AHORA + timedelta(minutes=5))

    assert (resumen.enviados, resumen.repetidos) == (0, 0)
    assert mail.enviados == [] and len(wsp.enviados) == 1
    assert _canales(TipoAviso.CONFIRMACION) == [("whatsapp", "enviado")]


def test_lo_que_solo_se_registro_en_whatsapp_sale_por_mail_si_se_apaga_whatsapp(sesion, cancha, jugador, tarifa_base):
    """Un `registrado` no entregó nada (modo prueba): si WhatsApp se apaga, el aviso no se pierde, sale por mail."""
    _confirmada(sesion, cancha, jugador)
    mail = ProveedorFalso(EMAIL)
    _barrer(sesion, {"email": mail, "whatsapp": ProveedorRegistro()})
    assert mail.enviados == []

    _barrer(sesion, {"email": mail, "whatsapp": ProveedorApagado()}, AHORA + timedelta(minutes=5))

    assert len(mail.enviados) == 1


def test_lo_que_solo_se_registro_en_whatsapp_sale_por_whatsapp_real_al_conectar_evolution(
    sesion, cancha, jugador, tarifa_base
):
    """La regla del ADR-029 sigue en pie con dos canales: registrado → real = se manda, y por WhatsApp, no por mail."""
    _confirmada(sesion, cancha, jugador)
    mail = ProveedorFalso(EMAIL)
    _barrer(sesion, {"email": mail, "whatsapp": ProveedorRegistro()})
    real = ProveedorFalso(WHATSAPP)

    resumen = _barrer(sesion, {"email": mail, "whatsapp": real}, AHORA + timedelta(minutes=5))

    assert resumen.enviados == 1 and len(real.enviados) == 1 and mail.enviados == []
    assert _canales(TipoAviso.CONFIRMACION) == [("whatsapp", "enviado")]


def test_el_barrido_no_repite_el_registro_de_whatsapp_en_cada_corrida(sesion, cancha, jugador, tarifa_base):
    """Con WhatsApp en registro y el mail disponible, el aviso queda resuelto: no es candidato en cada barrida."""
    _confirmada(sesion, cancha, jugador)
    proveedores = {"email": ProveedorFalso(EMAIL), "whatsapp": ProveedorRegistro()}
    _barrer(sesion, proveedores)

    assert servicio.pendientes(sesion, proveedores, AHORA + timedelta(minutes=5)) == []


# ── La cancelación exige que la confirmación haya salido, por cualquiera de los dos canales ─────────────────────────


def test_la_cancelacion_se_avisa_si_la_confirmacion_salio_por_mail(sesion, cancha, jugador, tarifa_base):
    reserva = _confirmada(sesion, cancha, jugador)
    mail = ProveedorFalso(EMAIL)
    _barrer(sesion, {"email": mail, "whatsapp": ProveedorApagado()})
    assert _canales(TipoAviso.CONFIRMACION) == [("email", "enviado")]
    _cancelar(sesion, reserva)

    # La cancelación sale por el canal que le toca ahora (WhatsApp, ya prendido), no por el de la confirmación.
    wsp = ProveedorFalso(WHATSAPP)
    resumen = _barrer(sesion, {"email": mail, "whatsapp": wsp}, AHORA + timedelta(minutes=10))

    assert resumen.enviados == 1 and len(wsp.enviados) == 1
    assert _canales(TipoAviso.CANCELACION) == [("whatsapp", "enviado")]


def test_la_cancelacion_se_avisa_si_la_confirmacion_salio_por_whatsapp(sesion, cancha, jugador, tarifa_base):
    reserva = _confirmada(sesion, cancha, jugador)
    wsp = ProveedorFalso(WHATSAPP)
    _barrer(sesion, {"email": ProveedorFalso(EMAIL), "whatsapp": wsp})
    _cancelar(sesion, reserva)

    # Ahora WhatsApp está apagado: la confirmación salió por WhatsApp, y la cancelación va por mail.
    mail = ProveedorFalso(EMAIL)
    resumen = _barrer(sesion, {"email": mail, "whatsapp": ProveedorApagado()}, AHORA + timedelta(minutes=10))

    assert resumen.enviados == 1 and len(mail.enviados) == 1
    assert "Motivo: Lluvia" in mail.enviados[0][2]
    assert _canales(TipoAviso.CANCELACION) == [("email", "enviado")]


def test_la_cancelacion_no_se_avisa_si_la_confirmacion_no_salio_por_ningun_canal(
    sesion, cancha, jugador, tarifa_base
):
    """🔴 Rechazada por WhatsApp y sin mail: el cliente nunca supo que tenía el turno, no se le avisa que se cayó."""
    jugador.email = None
    sesion.commit()
    reserva = _confirmada(sesion, cancha, jugador)
    proveedores = {
        "email": ProveedorFalso(EMAIL),
        "whatsapp": ProveedorFalso(WHATSAPP, rechaza="El número no tiene WhatsApp."),
    }
    _barrer(sesion, proveedores)
    _cancelar(sesion, reserva)

    resumen = _barrer(sesion, proveedores, AHORA + timedelta(minutes=10))

    assert resumen.enviados == 0
    assert _por_tipo(TipoAviso.CANCELACION) == []
    assert proveedores["email"].enviados == [] and proveedores["whatsapp"].enviados == []


def test_la_cancelacion_no_se_avisa_si_la_confirmacion_solo_se_registro_y_whatsapp_se_apago(
    sesion, cancha, jugador, tarifa_base
):
    """Un `registrado` es una confirmación que nadie recibió; si WhatsApp ya no es de prueba, no cuenta."""
    reserva = _confirmada(sesion, cancha, jugador)
    _barrer(sesion, {"email": ProveedorFalso(EMAIL, disponible=False), "whatsapp": ProveedorRegistro()})
    assert _canales(TipoAviso.CONFIRMACION) == [("whatsapp", "registrado")]
    _cancelar(sesion, reserva)
    mail = ProveedorFalso(EMAIL)

    _barrer(sesion, {"email": mail, "whatsapp": ProveedorApagado()}, AHORA + timedelta(minutes=10))

    assert _por_tipo(TipoAviso.CANCELACION) == [] and mail.enviados == []


def test_la_cancelacion_de_una_confirmacion_solo_registrada_tambien_se_registra(sesion, cancha, jugador, tarifa_base):
    """Con WhatsApp en registro, la cancelación se registra como la confirmación (consistente, sin mail)."""
    reserva = _confirmada(sesion, cancha, jugador)
    mail = ProveedorFalso(EMAIL)
    proveedores = {"email": mail, "whatsapp": ProveedorRegistro()}
    _barrer(sesion, proveedores)
    _cancelar(sesion, reserva)

    _barrer(sesion, proveedores, AHORA + timedelta(minutes=10))

    assert _canales(TipoAviso.CANCELACION) == [("whatsapp", "registrado")]
    assert mail.enviados == []


# ── Lo propio de LibraClub se mantiene ───────────────────────────────────────────────────────────────────────────────


def test_el_cliente_que_no_quiere_avisos_queda_omitido_en_cada_canal_y_no_recibe_nada(
    sesion, cancha, jugador, tarifa_base
):
    jugador.acepta_avisos = False
    sesion.commit()
    _confirmada(sesion, cancha, jugador)
    mail, wsp = ProveedorFalso(EMAIL), ProveedorFalso(WHATSAPP)
    proveedores = {"email": mail, "whatsapp": wsp}

    primera = _barrer(sesion, proveedores)
    segunda = _barrer(sesion, proveedores, AHORA + timedelta(minutes=5))

    assert primera.omitidos == 2 and segunda.omitidos == 0 and segunda.repetidos == 0
    assert mail.enviados == [] and wsp.enviados == []
    assert {(g.canal.value, g.detalle) for g in guardados()} == {
        ("email", "El cliente pidió no recibir avisos."),
        ("whatsapp", "El cliente pidió no recibir avisos."),
    }


def test_los_interruptores_por_tipo_siguen_mandando(sesion, cancha, jugador, tarifa_base):
    _confirmada(sesion, cancha, jugador)
    proveedores = {"email": ProveedorFalso(EMAIL), "whatsapp": ProveedorFalso(WHATSAPP)}

    apagado = servicio.ConfiguracionDeAvisos(confirmacion=False)
    resumen = servicio.barrer(sesion, proveedores, AHORA, config=apagado)
    sesion.commit()

    assert resumen.enviados == 0 and guardados() == []


def test_la_clave_es_la_misma_para_los_dos_canales_en_cada_tipo_de_aviso(sesion, cancha, jugador, tarifa_base):
    """Un recordatorio que cae de WhatsApp a mail conserva la clave con la anticipación: el de 24 y el de 2 horas siguen
    siendo avisos distintos, y cada uno sale una sola vez."""
    reserva = _confirmada(sesion, cancha, jugador)
    sesion.execute(update(Reserva).where(Reserva.id == reserva.id).values(created_at=CUANDO - timedelta(days=3)))
    sesion.commit()
    sesion.expire(reserva)
    proveedores = {
        "email": ProveedorFalso(EMAIL),
        "whatsapp": ProveedorFalso(WHATSAPP, rechaza="El número no tiene WhatsApp."),
    }

    _barrer(sesion, proveedores, CUANDO - timedelta(hours=20))
    _barrer(sesion, proveedores, CUANDO - timedelta(hours=1))
    _barrer(sesion, proveedores, CUANDO - timedelta(minutes=55))

    claves = sorted({g.clave for g in _por_tipo(TipoAviso.RECORDATORIO)})
    assert claves == [f"reserva:{reserva.id}:recordatorio:2", f"reserva:{reserva.id}:recordatorio:24"]
    assert len(proveedores["email"].enviados) == 2


def test_dos_clientes_cada_uno_por_su_canal(sesion, cancha, jugador, tarifa_base):
    """El reparto es por cliente, no por barrido: el que tiene teléfono va por WhatsApp y el que no, por mail."""
    sin_telefono = Cliente(nombre="Ana Sin Teléfono", email="ana@ejemplo.com")
    sesion.add(sin_telefono)
    sesion.commit()
    _confirmada(sesion, cancha, jugador)
    _confirmada(sesion, cancha, sin_telefono, cuando=CUANDO + timedelta(hours=2))
    mail, wsp = ProveedorFalso(EMAIL), ProveedorFalso(WHATSAPP)

    resumen = _barrer(sesion, {"email": mail, "whatsapp": wsp})

    assert resumen.enviados == 2
    assert [d for d, _, _ in wsp.enviados] == ["5492255123456"]
    assert [d for d, _, _ in mail.enviados] == ["ana@ejemplo.com"]


def test_un_proveedor_suelto_barre_solo_ese_canal(sesion, cancha, jugador, tarifa_base):
    """`barrer(sesion, proveedor)` = sólo por ese canal: lo usa el cron cuando sólo hay uno y los tests de un canal."""
    _confirmada(sesion, cancha, jugador)
    mail = ProveedorFalso(EMAIL)

    resumen = _barrer(sesion, mail)

    assert resumen.enviados == 1 and len(mail.enviados) == 1
    assert _canales(TipoAviso.CONFIRMACION) == [("email", "enviado")]


# ── El cron: un solo barrido con los dos canales ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def cron(engine, monkeypatch):
    """`scripts.enviar_avisos` importado como lo importa el cron (con el arranque de la app), como `test_avisos.py`."""
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
    yield modulo
    AuthBase.metadata.drop_all(engine)


def test_el_cron_hace_un_solo_barrido_con_los_dos_canales_y_una_sola_linea_de_log(cron, monkeypatch, capsys):
    """Antes barría cada canal por separado y escribía una línea por canal. Ahora un barrido, una línea."""
    proveedores = {"email": ProveedorFalso(EMAIL, disponible=False), "whatsapp": ProveedorRegistro()}
    llamadas = []

    def barrer(sesion, recibidos, *a, **k):
        llamadas.append(recibidos)
        return servicio.Resumen()

    monkeypatch.setattr(cron.servicio, "construir_proveedores", lambda config_smtp: proveedores)
    monkeypatch.setattr(cron.servicio, "barrer", barrer)

    assert cron.main() == 0

    assert llamadas == [proveedores], "un solo barrido, con los dos canales juntos"
    lineas = capsys.readouterr().out.strip().splitlines()
    assert len(lineas) == 1
    assert "avisos · canales: whatsapp · enviados: 0" in lineas[0]
