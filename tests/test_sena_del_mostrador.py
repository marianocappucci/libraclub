"""La seña de una reserva tomada por teléfono o en el mostrador tiene plazo de 24 horas (ADR-029, addendum 2026-10-28).

Antes de esto una `pendiente_pago` era una promesa sin plazo: no tenía `vence_at`, el CHECK, `cambiar_estado` y
`vencer_provisorias` sólo miraban las provisorias del portal, y el aviso de «seña por vencer» no podía existir.

Lo que se fija acá:

- **cuándo vence** (`vencimiento_de_sena`): 24 h desde que se tomó, nunca más tarde que 2 h antes del turno, con un piso
  de 30 min para el turno sobre la hora y sin plazo para un turno que ya empezó;
- **que el vencimiento nace con la reserva** (el mostrador, el cambio de estado y el central cuando sube la de un nodo);
- **que al vencer se libera** igual que una provisoria del portal, **salvo que ya haya plata adentro**;
- **que se avisa** `VENTANA_DE_SENA_DEL_MOSTRADOR` antes, una sola vez, y no a quien ya pagó;
- **que la migración no libera lo que ya existía**.

Todo con un `momento` explícito y `created_at` / `vence_at` puestos a mano: un test que dependa de la hora a la que
corre el CI no se puede reproducir.
"""

from __future__ import annotations

import os
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import Session

from app.config import Config
from app.main import crear_app
from app.models.enums import (
    AlcanceDia,
    EstadoAviso,
    EstadoReserva,
    OrigenReserva,
    TipoAviso,
)
from app.models.maestros import FranjaDeAtencion
from app.models.reservas import CanalDePago, EstadoPago, PagoDeReserva, Reserva
from app.servicios import avisos as servicio
from app.servicios import pagos as servicio_pagos
from app.servicios import reservas as servicio_reservas
from app.servicios.reservas import (
    MARGEN_DE_SENA_ANTES_DEL_TURNO,
    MOTIVO_SENA_VENCIDA,
    PLAZO_DE_SENA,
    PLAZO_MINIMO_DE_SENA,
    vencimiento_de_sena,
)
from app.tiempo import TZ
from tests.avisos_apoyo import Guardado, ProveedorFalso, borrar_guardados, guardados

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USUARIO, CLAVE = "admin", "clave-de-prueba"

#: El mostrador toma la reserva el lunes 31-08-2026 a las 10:00 para el martes 01-09 a las 20:00.
TOMADA = datetime(2026, 8, 31, 10, 0, tzinfo=TZ)
TURNO = datetime(2026, 9, 1, 20, 0, tzinfo=TZ)
#: 24 h después de tomada: el martes 10:00. Como el turno es a las 20:00, el tope de 2 h antes (18:00) no manda.
VENCE = datetime(2026, 9, 1, 10, 0, tzinfo=TZ)


@pytest.fixture
def jugador(sesion, cliente, motor):
    cliente.email = "jugador@ejemplo.com"
    sesion.commit()
    return cliente


def _tomar(sesion, monkeypatch, cancha, jugador, *, tomada=TOMADA, turno=TURNO, **resto) -> Reserva:
    """Una `pendiente_pago` del mostrador, tomada en `tomada` (se fija el reloj del servicio y `created_at`)."""
    monkeypatch.setattr(servicio_reservas, "ahora", lambda: tomada)
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=turno,
        estado=EstadoReserva.PENDIENTE_PAGO, origen=OrigenReserva.TELEFONO, **resto,
    )
    sesion.commit()
    sesion.execute(update(Reserva).where(Reserva.id == reserva.id).values(created_at=tomada))
    sesion.commit()
    sesion.expire(reserva)
    return reserva


def _avisos(sesion) -> list[Guardado]:
    return guardados()


# ── Cuándo vence ─────────────────────────────────────────────────────────


def test_la_sena_tiene_24_horas_desde_que_se_tomo():
    assert PLAZO_DE_SENA == timedelta(hours=24)
    assert vencimiento_de_sena(TOMADA, TURNO) == VENCE


def test_nunca_vence_despues_de_2_horas_antes_del_turno():
    """🔴 El turno de mañana a las 09:00 no puede seguir retenido hasta las 09:00 de pasado: se libera con el
    partido por empezar y nadie lo puede revender."""
    turno = TOMADA + timedelta(hours=20)  # mañana a las 06:00

    assert vencimiento_de_sena(TOMADA, turno) == turno - MARGEN_DE_SENA_ANTES_DEL_TURNO


@pytest.mark.parametrize(
    ("falta_para_el_turno", "vence_en"),
    [
        (timedelta(hours=26), timedelta(hours=24)),  # el plazo entero entra
        (timedelta(hours=24, minutes=1), timedelta(hours=22, minutes=1)),  # manda el tope del turno
        (timedelta(hours=5), timedelta(hours=3)),
        (timedelta(hours=2, minutes=30), timedelta(minutes=30)),  # justo el piso
        (timedelta(hours=1), timedelta(minutes=30)),  # sobre la hora: el piso, no «ya vencida»
        (timedelta(minutes=20), timedelta(minutes=20)),  # el piso no pasa del inicio del turno
    ],
)
def test_los_bordes_del_plazo(falta_para_el_turno, vence_en):
    assert vencimiento_de_sena(TOMADA, TOMADA + falta_para_el_turno) == TOMADA + vence_en


def test_el_vencimiento_jamas_queda_despues_del_turno():
    for minutos in range(1, 60 * 30, 7):
        turno = TOMADA + timedelta(minutes=minutos)
        assert TOMADA < vencimiento_de_sena(TOMADA, turno) <= turno


def test_un_turno_que_ya_empezo_no_tiene_plazo():
    """Es el mostrador cargando algo que pasó: vencerlo cancelaría un partido que ya se jugó."""
    assert vencimiento_de_sena(TOMADA, TOMADA) is None
    assert vencimiento_de_sena(TOMADA, TOMADA - timedelta(hours=3)) is None


def test_el_piso_es_de_media_hora():
    assert PLAZO_MINIMO_DE_SENA == timedelta(minutes=30)


# ── Nace con su vencimiento ──────────────────────────────────────────────


def test_una_reserva_pendiente_de_pago_nace_con_vencimiento(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    reserva = _tomar(sesion, monkeypatch, cancha, jugador)

    assert reserva.estado is EstadoReserva.PENDIENTE_PAGO
    assert reserva.vence_at == VENCE


def test_una_confirmada_no_vence(sesion, monkeypatch, cancha, jugador, tarifa_base):
    monkeypatch.setattr(servicio_reservas, "ahora", lambda: TOMADA)
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=TURNO,
        estado=EstadoReserva.CONFIRMADA,
    )

    assert reserva.vence_at is None


def test_la_provisoria_del_portal_sigue_con_sus_15_minutos(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    """El control: lo del mostrador no cambia la retención del portal."""
    monkeypatch.setattr(servicio_reservas, "ahora", lambda: TOMADA)
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=TURNO,
        estado=EstadoReserva.PROVISORIA, origen=OrigenReserva.PORTAL,
    )

    assert reserva.vence_at == TOMADA + timedelta(minutes=15)


def test_confirmar_la_sena_saca_el_vencimiento(sesion, monkeypatch, cancha, jugador, tarifa_base):
    """Pagar la seña es confirmar: una confirmada con `vence_at` la levantaría el barrido y el jugador perdería el
    turno que pagó."""
    reserva = _tomar(sesion, monkeypatch, cancha, jugador)

    servicio_reservas.cambiar_estado(sesion, reserva.id, EstadoReserva.CONFIRMADA)

    assert reserva.vence_at is None


def test_una_provisoria_que_pasa_a_pendiente_de_pago_recibe_el_plazo_desde_ese_momento(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    monkeypatch.setattr(servicio_reservas, "ahora", lambda: TOMADA)
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=TURNO,
        estado=EstadoReserva.PROVISORIA, origen=OrigenReserva.PORTAL,
    )
    monkeypatch.setattr(servicio_reservas, "ahora", lambda: TOMADA + timedelta(hours=1))

    servicio_reservas.cambiar_estado(sesion, reserva.id, EstadoReserva.PENDIENTE_PAGO)

    assert reserva.vence_at == VENCE + timedelta(hours=1)


# ── Al vencer, se libera ─────────────────────────────────────────────────


def test_al_vencer_la_sena_se_libera_el_turno(sesion, monkeypatch, cancha, jugador, tarifa_base):
    reserva = _tomar(sesion, monkeypatch, cancha, jugador)

    cuantas = servicio_reservas.vencer_provisorias(sesion, VENCE)
    sesion.commit()
    sesion.refresh(reserva)

    assert cuantas == 1
    assert reserva.estado is EstadoReserva.CANCELADA
    assert reserva.motivo == MOTIVO_SENA_VENCIDA
    assert reserva.vence_at is None
    # El turno volvió a la grilla: otra persona lo puede tomar.
    otra = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=TURNO,
        estado=EstadoReserva.CONFIRMADA,
    )
    assert otra.id != reserva.id


def test_un_minuto_antes_no_se_libera(sesion, monkeypatch, cancha, jugador, tarifa_base):
    reserva = _tomar(sesion, monkeypatch, cancha, jugador)

    assert servicio_reservas.vencer_provisorias(sesion, VENCE - timedelta(minutes=1)) == 0
    sesion.refresh(reserva)

    assert reserva.estado is EstadoReserva.PENDIENTE_PAGO and reserva.vence_at == VENCE


def test_la_provisoria_del_portal_se_sigue_liberando_en_la_misma_pasada(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    """Misma vía: una sola llamada libera las dos y devuelve cuántas fueron."""
    del_mostrador = _tomar(sesion, monkeypatch, cancha, jugador)
    provisoria = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=TURNO + timedelta(days=1),
        estado=EstadoReserva.PROVISORIA, origen=OrigenReserva.PORTAL,
    )
    sesion.commit()

    cuantas = servicio_reservas.vencer_provisorias(sesion, VENCE + timedelta(days=2))
    sesion.commit()
    sesion.refresh(del_mostrador)
    sesion.refresh(provisoria)

    assert cuantas == 2
    assert del_mostrador.estado is EstadoReserva.CANCELADA and provisoria.estado is EstadoReserva.CANCELADA
    assert provisoria.motivo == "Vencida sin confirmar"


def test_una_pendiente_de_pago_sin_vencimiento_no_se_toca_nunca(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    """Las anteriores al plazo de 24 h (y las de un camino que no lo pone) quedan como estaban."""
    reserva = _tomar(sesion, monkeypatch, cancha, jugador)
    reserva.vence_at = None
    sesion.commit()

    assert servicio_reservas.vencer_provisorias(sesion, VENCE + timedelta(days=365)) == 0
    sesion.refresh(reserva)

    assert reserva.estado is EstadoReserva.PENDIENTE_PAGO


def test_una_confirmada_con_vencimiento_viejo_no_se_libera(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    """El barrido mira el estado: pagar la seña (confirmar) es lo que lo frena, aunque `vence_at` quedara puesto."""
    reserva = _tomar(sesion, monkeypatch, cancha, jugador)
    reserva.estado = EstadoReserva.CONFIRMADA
    sesion.commit()

    assert servicio_reservas.vencer_provisorias(sesion, VENCE + timedelta(hours=1)) == 0


def test_con_un_pago_aprobado_no_se_libera_y_se_le_saca_el_vencimiento(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    """🔴 Si ya pagó, no se libera: cancelar se quedaría con la plata de alguien."""
    reserva = _tomar(sesion, monkeypatch, cancha, jugador)
    sesion.add(PagoDeReserva(
        reserva_id=reserva.id, monto=Decimal("5000.00"), estado=EstadoPago.APROBADO,
        referencia=servicio_pagos.nueva_referencia(reserva.id), canal=CanalDePago.MOSTRADOR,
    ))
    sesion.commit()

    assert servicio_reservas.vencer_provisorias(sesion, VENCE + timedelta(hours=1)) == 0
    sesion.refresh(reserva)

    assert reserva.estado is EstadoReserva.PENDIENTE_PAGO
    assert reserva.vence_at is None, "pasó su plazo pero pagó: se resuelve a mano, ya no es una reserva que venza"


def test_si_no_se_puede_consultar_la_caja_no_se_libera_nada(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    """Lo que no se sabe cuenta como que hay plata: se equivoca para el lado que no pierde la cancha de nadie."""
    reserva = _tomar(sesion, monkeypatch, cancha, jugador)

    def caja_caida(_ids):
        raise RuntimeError("la caja no contesta")

    monkeypatch.setattr(servicio_reservas, "cobrado_en_caja", caja_caida)

    assert servicio_reservas.vencer_provisorias(sesion, VENCE + timedelta(hours=1)) == 0
    sesion.refresh(reserva)

    assert reserva.estado is EstadoReserva.PENDIENTE_PAGO and reserva.vence_at == VENCE


# ── Con plata en la caja (necesita la base de LibraCore) ─────────────────


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    cliente = TestClient(
        crear_app(
            Config(
                database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
                directorio_de_datos="/tmp/libraclub-test-datos",
                libracore_database_url=base_de_libracore,
            )
        ),
        base_url="https://testserver",
    )
    assert cliente.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


def _tomada_por_la_api_y_senada(api, sesion, sucursal, cancha, jugador, abrir_caja, monto="2500") -> Reserva:
    """Una `pendiente_pago` creada por el endpoint del mostrador, con una seña (parcial) cobrada en la caja."""
    r = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": jugador.id, "comienza_at": TURNO.isoformat(),
        "duracion_min": 90, "estado": "pendiente_pago", "origen": "telefono",
    })
    assert r.status_code == 201, r.text
    reserva = sesion.get(Reserva, r.json()["id"])
    # El reloj real corre en otra fecha que el del test: se ponen a mano los dos instantes que importan.
    sesion.execute(update(Reserva).where(Reserva.id == reserva.id).values(created_at=TOMADA, vence_at=VENCE))
    sesion.commit()
    assert abrir_caja(api, sucursal).status_code == 201
    cobro = api.post(
        f"/api/reservas/{reserva.id}/cobros", json={"monto": monto, "medio_pago": "efectivo"}
    )
    assert cobro.status_code == 201, cobro.text
    sesion.expire(reserva)
    return reserva


def test_con_plata_en_la_caja_no_se_libera_aunque_sea_una_sena_a_medias(
    api, sesion, sucursal, cancha, jugador, tarifa_base, abrir_caja
):
    """🔴 Una seña a medias sigue siendo plata de alguien, y cancelar obligaría a devolverla: lo decide una persona."""
    reserva = _tomada_por_la_api_y_senada(api, sesion, sucursal, cancha, jugador, abrir_caja)

    assert servicio_reservas.vencer_provisorias(sesion, VENCE + timedelta(hours=1)) == 0
    sesion.commit()
    sesion.refresh(reserva)

    assert reserva.estado is EstadoReserva.PENDIENTE_PAGO and reserva.vence_at is None


def test_sin_plata_en_la_caja_la_misma_reserva_si_se_libera(
    api, sesion, sucursal, cancha, jugador, tarifa_base, abrir_caja
):
    """El control del anterior: con la caja disponible y vacía, vence."""
    r = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": jugador.id, "comienza_at": TURNO.isoformat(),
        "duracion_min": 90, "estado": "pendiente_pago", "origen": "telefono",
    })
    reserva = sesion.get(Reserva, r.json()["id"])
    sesion.execute(update(Reserva).where(Reserva.id == reserva.id).values(created_at=TOMADA, vence_at=VENCE))
    sesion.commit()
    assert abrir_caja(api, sucursal).status_code == 201

    assert servicio_reservas.vencer_provisorias(sesion, VENCE + timedelta(hours=1)) == 1
    sesion.commit()
    sesion.refresh(reserva)

    assert reserva.estado is EstadoReserva.CANCELADA


def test_a_quien_ya_senio_no_se_le_avisa_que_se_libera(
    api, sesion, sucursal, cancha, jugador, tarifa_base, abrir_caja
):
    _tomada_por_la_api_y_senada(api, sesion, sucursal, cancha, jugador, abrir_caja)
    proveedor = ProveedorFalso()

    resumen = servicio.barrer(sesion, proveedor, VENCE - timedelta(hours=2))

    assert resumen.enviados == 0 and proveedor.enviados == []


# ── El aviso ─────────────────────────────────────────────────────────────


def test_avisa_tres_horas_antes_con_fecha_y_con_lo_que_falta_pagar(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    reserva = _tomar(sesion, monkeypatch, cancha, jugador)
    proveedor = ProveedorFalso()

    resumen = servicio.barrer(sesion, proveedor, VENCE - timedelta(hours=2, minutes=50))
    sesion.commit()

    assert resumen.enviados == 1
    (destino, asunto, cuerpo) = proveedor.enviados[0]
    assert destino == "jugador@ejemplo.com"
    assert asunto == "Tu turno se libera el 01-09-2026 10:00: Cancha 1, 01-09-2026 20:00"
    assert "reservado hasta el 01-09-2026 10:00 esperando la seña" in cuerpo
    assert "Seña a pagar: $5.000,00" in cuerpo
    assert "respondé este mail" in cuerpo
    assert "Mis reservas" not in cuerpo, "esa pantalla es del portal; la seña del mostrador no se completa ahí"
    (guardado,) = _avisos(sesion)
    assert guardado.tipo is TipoAviso.SENA_POR_VENCER and guardado.reserva_id == reserva.id
    assert guardado.estado is EstadoAviso.ENVIADO


def test_no_avisa_si_falta_mas_que_la_ventana(sesion, monkeypatch, cancha, jugador, tarifa_base):
    _tomar(sesion, monkeypatch, cancha, jugador)

    assert servicio.barrer(sesion, ProveedorFalso(), VENCE - timedelta(hours=3, minutes=1)).enviados == 0


def test_no_avisa_un_turno_que_ya_se_libero(sesion, monkeypatch, cancha, jugador, tarifa_base):
    """«Se libera en unas horas» cuando ya se liberó es peor que no mandar nada."""
    _tomar(sesion, monkeypatch, cancha, jugador)

    assert servicio.barrer(sesion, ProveedorFalso(), VENCE + timedelta(minutes=1)).enviados == 0


def test_no_avisa_dos_veces(sesion, monkeypatch, cancha, jugador, tarifa_base):
    _tomar(sesion, monkeypatch, cancha, jugador)
    proveedor = ProveedorFalso()

    servicio.barrer(sesion, proveedor, VENCE - timedelta(hours=2))
    sesion.commit()
    servicio.barrer(sesion, proveedor, VENCE - timedelta(hours=1))
    sesion.commit()

    assert len(proveedor.enviados) == 1


def test_una_sena_confirmada_no_se_avisa(sesion, monkeypatch, cancha, jugador, tarifa_base):
    reserva = _tomar(sesion, monkeypatch, cancha, jugador)
    servicio_reservas.cambiar_estado(sesion, reserva.id, EstadoReserva.CONFIRMADA)
    sesion.commit()

    # Otros avisos sí pueden salir (el recordatorio de 24 h de una confirmada): lo que no sale es el de la seña.
    servicio.barrer(sesion, ProveedorFalso(), VENCE - timedelta(hours=2))
    sesion.commit()

    assert TipoAviso.SENA_POR_VENCER not in {a.tipo for a in _avisos(sesion)}


def test_con_un_pago_aprobado_no_se_avisa(sesion, monkeypatch, cancha, jugador, tarifa_base):
    reserva = _tomar(sesion, monkeypatch, cancha, jugador)
    sesion.add(PagoDeReserva(
        reserva_id=reserva.id, monto=Decimal("5000.00"), estado=EstadoPago.APROBADO,
        referencia=servicio_pagos.nueva_referencia(reserva.id), canal=CanalDePago.MOSTRADOR,
    ))
    sesion.commit()

    assert servicio.barrer(sesion, ProveedorFalso(), VENCE - timedelta(hours=2)).enviados == 0


def test_el_plazo_corto_de_un_turno_sobre_la_hora_no_avisa_a_los_segundos(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    """Se toma a las 19:00 un turno de las 20:00: tiene 30 minutos. «Se libera en media hora», recién cortado el
    teléfono, es ruido: el aviso sólo sale si el plazo era más largo que su ventana."""
    tomada = datetime(2026, 9, 1, 19, 0, tzinfo=TZ)
    reserva = _tomar(sesion, monkeypatch, cancha, jugador, tomada=tomada)
    assert reserva.vence_at == tomada + timedelta(minutes=30)

    assert servicio.barrer(sesion, ProveedorFalso(), tomada + timedelta(minutes=2)).enviados == 0


def test_el_cron_cada_5_minutos_avisa_una_vez_y_entre_2h55_y_3h_antes(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    """El mismo método que el del aviso del portal: se simula el cron en sus cinco fases posibles."""
    reserva = _tomar(sesion, monkeypatch, cancha, jugador)
    for fase in range(5):
        borrar_guardados(sesion)
        proveedor = ProveedorFalso()
        salio_a = []
        momento = VENCE - timedelta(hours=4) + timedelta(minutes=fase)
        while momento < VENCE:
            if servicio.barrer(sesion, proveedor, momento).enviados:
                salio_a.append(VENCE - momento)
            sesion.commit()
            momento += timedelta(minutes=5)
        assert len(salio_a) == 1, f"fase {fase}: salió {len(salio_a)} veces"
        assert timedelta(hours=2, minutes=55) <= salio_a[0] <= timedelta(hours=3), f"fase {fase}: {salio_a[0]}"
    assert reserva.id


def test_apagar_el_aviso_de_sena_lo_apaga_tambien_para_el_mostrador(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    from app.servicios.avisos import ConfiguracionDeAvisos, guardar_configuracion

    _tomar(sesion, monkeypatch, cancha, jugador)
    guardar_configuracion(sesion, ConfiguracionDeAvisos(sena_por_vencer=False))
    sesion.commit()

    assert servicio.barrer(sesion, ProveedorFalso(), VENCE - timedelta(hours=2)).enviados == 0


# ── El central y los conflictos ──────────────────────────────────────────


def test_el_central_le_pone_el_vencimiento_a_la_reserva_que_sube_de_un_nodo(
    sesion, cancha, jugador, tarifa_base
):
    """El nodo no manda `vence_at`: lo decide el central, contado desde que el nodo tomó la reserva (`creada_at`)."""
    pytest.importorskip("libraedge")
    from libracore.db import core as libracore_core

    from app.servicios import reservas_nodo
    from tests.conftest import url_del_core
    from tests.reservas_nodo_apoyo import (
        aplicar,
        payload_creada,
        preparar_tablas_de_libraedge,
    )

    preparar_tablas_de_libraedge(sesion)
    conn = libracore_core.conectar(url_del_core())
    try:
        aplicar(conn, reservas_nodo.TIPO_RESERVA_CREADA, payload_creada(
            cancha.id, jugador.id, reserva_id=-1, estado="pendiente_pago", desde=TURNO,
            hasta=TURNO + timedelta(minutes=90), creada_at=TOMADA.isoformat(),
        ))
        aplicar(conn, reservas_nodo.TIPO_RESERVA_CREADA, payload_creada(
            cancha.id, jugador.id, reserva_id=-2, estado="confirmada", desde=TURNO + timedelta(days=1),
            hasta=TURNO + timedelta(days=1, minutes=90), creada_at=TOMADA.isoformat(),
        ), secuencia=2)
    finally:
        conn.rollback()
        conn.close()

    sesion.expire_all()
    senia, confirmada = sesion.scalars(select(Reserva).order_by(Reserva.id)).all()
    assert senia.estado is EstadoReserva.PENDIENTE_PAGO and senia.vence_at == VENCE
    assert confirmada.estado is EstadoReserva.CONFIRMADA and confirmada.vence_at is None


def test_la_reserva_del_nodo_que_choca_queda_sin_vencimiento_hasta_resolverse(
    sesion, cancha, jugador, tarifa_base
):
    """Una `en_conflicto` no ocupa la cancha: no tiene qué liberar."""
    pytest.importorskip("libraedge")
    from libracore.db import core as libracore_core

    from app.servicios import reservas_nodo
    from tests.conftest import url_del_core
    from tests.reservas_nodo_apoyo import aplicar, payload_creada, preparar_tablas_de_libraedge

    servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=TURNO, precio=Decimal("1")
    )
    sesion.commit()
    preparar_tablas_de_libraedge(sesion)
    conn = libracore_core.conectar(url_del_core())
    try:
        aplicar(conn, reservas_nodo.TIPO_RESERVA_CREADA, payload_creada(
            cancha.id, jugador.id, reserva_id=-1, estado="pendiente_pago", desde=TURNO,
            hasta=TURNO + timedelta(minutes=90), creada_at=TOMADA.isoformat(),
        ))
    finally:
        conn.rollback()
        conn.close()

    sesion.expire_all()
    (_, perdedora) = sesion.scalars(select(Reserva).order_by(Reserva.id)).all()
    assert perdedora.estado is EstadoReserva.EN_CONFLICTO and perdedora.vence_at is None


def test_al_resolver_un_conflicto_la_sena_recibe_un_plazo_nuevo_sobre_el_horario_nuevo(
    sesion, monkeypatch, cancha, jugador, tarifa_base
):
    """El conflicto lo causó el club (se vendió dos veces la cancha): el plazo no le corre al jugador."""
    from app.servicios import conflictos

    reserva = _tomar(sesion, monkeypatch, cancha, jugador)
    reserva.estado = EstadoReserva.EN_CONFLICTO
    reserva.estado_previo = EstadoReserva.PENDIENTE_PAGO
    reserva.vence_at = None
    sesion.commit()
    ahora_de_resolver = TOMADA + timedelta(days=3)
    monkeypatch.setattr(conflictos, "ahora", lambda: ahora_de_resolver)
    nuevo = ahora_de_resolver + timedelta(days=5, hours=2)

    conflictos.mover(sesion, reserva.id, comienza_at=nuevo)
    sesion.commit()

    assert reserva.estado is EstadoReserva.PENDIENTE_PAGO
    assert reserva.vence_at == ahora_de_resolver + PLAZO_DE_SENA


# ── La agenda y el detalle ven hasta cuándo ──────────────────────────────


def test_la_agenda_trae_hasta_cuando_tiene_para_pagar(api, sesion, sucursal, cancha, jugador, tarifa_base):
    sesion.add(FranjaDeAtencion(
        sucursal_id=sucursal.id, alcance_dia=AlcanceDia.TODOS, abre=time(0, 0), cierra=time(0, 0),
    ))
    sesion.commit()
    r = api.post("/api/reservas", json={
        "cancha_id": cancha.id, "cliente_id": jugador.id, "comienza_at": TURNO.isoformat(),
        "duracion_min": 90, "estado": "pendiente_pago", "origen": "telefono",
    })
    assert r.status_code == 201, r.text
    reserva = r.json()
    sesion.execute(update(Reserva).where(Reserva.id == reserva["id"]).values(vence_at=VENCE))
    sesion.commit()

    detalle = api.get(f"/api/reservas/{reserva['id']}")
    semana = api.get(f"/api/disponibilidad/semana?sucursal_id={sucursal.id}&desde=2026-08-31")

    assert datetime.fromisoformat(detalle.json()["vence_at"]) == VENCE
    assert semana.status_code == 200, semana.text
    turnos = semana.json()["canchas"][str(cancha.id)]["2026-09-01"]
    # Una reserva de 90 minutos se dibuja en cada casillero que toca: todos traen el mismo vencimiento.
    ocupados = [t for t in turnos if t["reserva_id"] == reserva["id"]]
    assert ocupados and all(datetime.fromisoformat(t["vence_at"]) == VENCE for t in ocupados)
    libres = [t for t in turnos if t["libre"]]
    assert libres and all(t["vence_at"] is None for t in libres)


# ── La migración no libera lo que ya existía ─────────────────────────────


def _alembic() -> AlembicConfig:
    cfg = AlembicConfig(os.path.join(RAIZ, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(RAIZ, "migrations"))
    return cfg


def _indice(motor) -> str:
    with motor.connect() as conexion:
        return conexion.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_reservas_vence_at'")
        ).scalar_one()


def test_la_migracion_no_libera_ni_le_pone_vencimiento_a_las_pendientes_que_ya_existen(
    base_temporal, monkeypatch
):
    """🔴 Una `pendiente_pago` tomada hace tres semanas con un «pagás cuando vengas» no puede liberarse sola el día
    del despliegue, y una de un turno ya pasado no puede vencer de golpe. Quedan como estaban: sin plazo."""
    url = base_temporal("mig0017")
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _alembic()
    motor = create_engine(url, future=True)
    try:
        command.upgrade(cfg, "0016_avisos_y_promociones")
        assert "provisoria" in _indice(motor) and "pendiente_pago" not in _indice(motor)
        with motor.begin() as conexion:
            conexion.execute(text("INSERT INTO sucursales (nombre, punto_venta_arca) VALUES ('S', 1)"))
            conexion.execute(text(
                "INSERT INTO canchas (sucursal_id, nombre, deporte, duracion_turno_min) VALUES (1, 'C', 'padel', 90)"
            ))
            conexion.execute(text("INSERT INTO clientes (nombre, acepta_avisos) VALUES ('J', true)"))
            # Una de un turno futuro y una cuyo turno ya pasó: las dos `pendiente_pago` de antes del plazo.
            for dia in ("2030-01-01", "2026-01-01"):
                conexion.execute(text(
                    "INSERT INTO reservas (cancha_id, cliente_id, estado, origen, comienza_at, termina_at, created_at) "
                    f"VALUES (1, 1, 'pendiente_pago', 'telefono', '{dia} 20:00-03', '{dia} 21:30-03', "
                    "'2025-12-01 10:00-03')"
                ))

        command.upgrade(cfg, "head")

        assert "pendiente_pago" in _indice(motor), "el índice del barrido cubre ahora también a la seña del mostrador"
        asi_quedaron = [("pendiente_pago", None, None)] * 2
        consulta = text("SELECT estado, vence_at, motivo FROM reservas ORDER BY id")
        with motor.connect() as conexion:
            assert [tuple(f) for f in conexion.execute(consulta).all()] == asi_quedaron

        # Y aunque el barrido corra dentro de un siglo, no las toca: no tienen plazo.
        with Session(motor) as sesion:
            assert servicio_reservas.vencer_provisorias(sesion, datetime(2126, 1, 1, tzinfo=TZ)) == 0
            sesion.commit()
        with motor.connect() as conexion:
            assert [tuple(f) for f in conexion.execute(consulta).all()] == asi_quedaron
    finally:
        motor.dispose()


def test_la_migracion_0017_es_reversible(base_temporal, monkeypatch):
    url = base_temporal("mig0017b")
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _alembic()
    motor = create_engine(url, future=True)
    try:
        command.upgrade(cfg, "head")
        assert "pendiente_pago" in _indice(motor)
        command.downgrade(cfg, "0016_avisos_y_promociones")
        assert "pendiente_pago" not in _indice(motor)
        command.upgrade(cfg, "head")
        assert "pendiente_pago" in _indice(motor)
    finally:
        motor.dispose()
