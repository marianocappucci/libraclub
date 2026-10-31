"""La migración `0018_avisos_al_motor`: los avisos de LibraClub pasan a `avisos_envios` sin repetirse (ADR-030).

Lo que se mide, y por qué importa:

- **Que se lleva todo con la clave que va a calcular el barrido nuevo**: si la clave no coincide, el primer barrido
  nuevo le reenvía a cada cliente lo que el viejo ya le mandó (la confirmación de las últimas 2 horas y los
  recordatorios de las próximas 24).
- **Que no se pierde nada ni se pisa**: idempotente, `avisos` queda intacta, y sin la tabla del motor falla en vez de
  dejar los avisos sin llevar.
- **El modo de WhatsApp**: se lleva una vez al motor y la columna vieja deja de ser obligatoria.

Corre la cadena de verdad (`alembic upgrade`) sobre una base descartable, con un avisos de antes cargado a mano.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from libracore import config_manager
from libracore.avisos import ProveedorRegistro
from sqlalchemy import update

from app.models.avisos import Aviso
from app.models.enums import CanalAviso, EstadoAviso, EstadoReserva, TipoAviso
from app.models.reservas import Reserva
from app.servicios import avisos as servicio
from app.servicios import reservas as servicio_reservas
from app.tiempo import TZ
from tests.avisos_apoyo import ProveedorFalso, guardados

RAIZ = Path(__file__).resolve().parent.parent
ANTERIOR = "0017_sena_del_mostrador_vence"

CUANDO = datetime(2026, 9, 1, 20, 0, tzinfo=TZ)


def _migracion():
    """El módulo de la revisión por su ruta (el nombre empieza con un número: no se importa con `import`)."""
    spec = importlib.util.spec_from_file_location("m0018", RAIZ / "migrations" / "versions" / "0018_avisos_al_motor.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _alembic() -> AlembicConfig:
    cfg = AlembicConfig(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    return cfg


def _libpq(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


# ── Una base de antes: la cadena en la 0017, con los avisos que mandó el barrido viejo ──────────────────────────────


@pytest.fixture
def base_de_antes(base_temporal, monkeypatch):
    """Una base descartable en la `0017`, con el motor ya migrado (`avisos_envios`) y avisos de antes cargados.

    Dos reservas y seis filas de `avisos` en todos los estados que el registro viejo conocía, de los dos canales.
    """
    url = base_temporal("avisos")
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(_alembic(), ANTERIOR)
    _crear_el_motor(url)
    with psycopg.connect(_libpq(url), autocommit=True) as con:
        con.execute("INSERT INTO sucursales (nombre) VALUES ('Centro')")
        con.execute("INSERT INTO canchas (sucursal_id, nombre) SELECT id, 'Cancha 1' FROM sucursales")
        con.execute("INSERT INTO clientes (nombre, email, acepta_avisos) VALUES ('Ana', 'ana@ejemplo.com', true)")
        for dias in (1, 3):
            con.execute(
                "INSERT INTO reservas (cancha_id, cliente_id, estado, comienza_at, termina_at) "
                "SELECT c.id, k.id, 'confirmada', now() + make_interval(days => %s), "
                "now() + make_interval(days => %s) + interval '90 minutes' FROM canchas c, clientes k",
                (dias, dias),
            )
        legado = [
            # (reserva, tipo, canal, horas_antes, estado, destino, asunto, cuerpo, detalle, intentos, enviado)
            (1, "confirmacion", "email", None, "enviado", "ana@ejemplo.com", "Turno OK", "Hola Ana", None, 1, 1),
            (1, "recordatorio", "email", 24, "fallido", "ana@ejemplo.com", "Te esperamos", "Hola", "550 casilla", 2, 0),
            (1, "recordatorio", "email", 2, "enviado", "ana@ejemplo.com", "Te esperamos", "Hola", None, 1, 1),
            (1, "confirmacion", "whatsapp", None, "registrado", "5491155551234", None, "*Turno*", "Registrado", 1, 0),
            (2, "sena_por_vencer", "whatsapp", None, "omitido", "", None, None, "Sin teléfono.", 1, 0),
            (2, "cancelacion", "email", None, "omitido", "", None, None, "El cliente no tiene email.", 1, 0),
        ]
        for fila in legado:
            con.execute(
                "INSERT INTO avisos (reserva_id, tipo, canal, horas_antes, estado, destino, asunto, cuerpo, detalle, "
                "intentos, enviado_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "CASE WHEN %s = 1 THEN '2026-09-01 22:30:00+00'::timestamptz END)",
                (*fila[:10], fila[10]),
            )
    return url


def _crear_el_motor(url: str) -> None:
    """Lo que hace `libracore-migrar` antes que esta cadena: el schema del motor, con `avisos_envios` (0032)."""
    from libracore.db import core as libracore_core
    from libracore.db.schema import init_core_schema

    conn = libracore_core.conectar(_libpq(url))
    try:
        init_core_schema(conn)
        conn.commit()
    finally:
        conn.close()


def _filas(url: str, sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(_libpq(url)) as con:
        return con.execute(sql, params).fetchall()


def test_la_0018_lleva_cada_aviso_con_su_clave_su_estado_y_sus_intentos(base_de_antes):
    command.upgrade(_alembic(), "head")

    llevadas = _filas(
        base_de_antes,
        "SELECT canal, clave, tipo, estado, intentos, destino, asunto, cuerpo, detalle, proveedor, enviado_at "
        "FROM avisos_envios ORDER BY id",
    )
    assert llevadas == [
        ("email", "reserva:1:confirmacion:-", "confirmacion", "enviado", 1, "ana@ejemplo.com", "Turno OK",
         "Hola Ana", "", "smtp", "2026-09-01 19:30:00"),
        ("email", "reserva:1:recordatorio:24", "recordatorio", "fallido", 2, "ana@ejemplo.com", "Te esperamos",
         "Hola", "550 casilla", "smtp", ""),
        ("email", "reserva:1:recordatorio:2", "recordatorio", "enviado", 1, "ana@ejemplo.com", "Te esperamos",
         "Hola", "", "smtp", "2026-09-01 19:30:00"),
        ("whatsapp", "reserva:1:confirmacion:-", "confirmacion", "registrado", 1, "5491155551234", "",
         "*Turno*", "Registrado", "registro", ""),
        ("whatsapp", "reserva:2:sena_por_vencer:-", "sena_por_vencer", "omitido", 1, "", "", "", "Sin teléfono.",
         "", ""),
        ("email", "reserva:2:cancelacion:-", "cancelacion", "omitido", 1, "", "", "", "El cliente no tiene email.",
         "", ""),
    ]


def test_la_clave_de_la_migracion_es_la_que_calcula_el_barrido_nuevo(base_de_antes):
    """🔴 Lo que ata las dos puntas: si la clave que escribe la `0018` y la de `clave_de` divergen, el primer barrido
    nuevo reenvía todo lo que el viejo ya mandó."""
    command.upgrade(_alembic(), "head")

    claves = {c for (c,) in _filas(base_de_antes, "SELECT clave FROM avisos_envios")}
    assert claves == {
        servicio.clave_de(1, TipoAviso.CONFIRMACION), servicio.clave_de(1, TipoAviso.RECORDATORIO, 24),
        servicio.clave_de(1, TipoAviso.RECORDATORIO, 2), servicio.clave_de(2, TipoAviso.SENA_POR_VENCER),
        servicio.clave_de(2, TipoAviso.CANCELACION),
    }


def test_la_0018_no_toca_avisos_y_se_puede_correr_dos_veces(base_de_antes):
    sql_avisos = "SELECT id, reserva_id, tipo, canal, estado, intentos FROM avisos ORDER BY id"
    antes = _filas(base_de_antes, sql_avisos)
    command.upgrade(_alembic(), "head")
    primera = _filas(base_de_antes, "SELECT * FROM avisos_envios ORDER BY id")

    command.downgrade(_alembic(), ANTERIOR)
    command.upgrade(_alembic(), "head")

    assert _filas(base_de_antes, sql_avisos) == antes
    assert _filas(base_de_antes, "SELECT * FROM avisos_envios ORDER BY id") == primera, "ni duplica ni pisa"
    assert len(primera) == 6


def test_la_0018_no_pisa_lo_que_el_barrido_nuevo_ya_escribio(base_de_antes):
    """Si el motor ya tiene una clave (otro proceso, un reintento de la migración), `ON CONFLICT DO NOTHING`."""
    with psycopg.connect(_libpq(base_de_antes), autocommit=True) as con:
        con.execute(
            "INSERT INTO avisos_envios (canal, clave, estado, intentos, detalle) "
            "VALUES ('email', 'reserva:1:confirmacion:-', 'rechazado', 1, 'lo escribió el barrido nuevo')"
        )

    command.upgrade(_alembic(), "head")

    assert _filas(base_de_antes, "SELECT estado, detalle FROM avisos_envios WHERE clave = 'reserva:1:confirmacion:-' "
                                 "AND canal = 'email'") == [("rechazado", "lo escribió el barrido nuevo")]
    assert _filas(base_de_antes, "SELECT count(*) FROM avisos_envios") == [(6,)]


def test_sin_la_tabla_del_motor_y_con_avisos_la_0018_falla_y_no_deja_nada_a_medias(base_de_antes):
    """Seguir sin `avisos_envios` dejaría los avisos sin llevar, en silencio: el primer barrido nuevo los reenvía."""
    with psycopg.connect(_libpq(base_de_antes), autocommit=True) as con:
        con.execute("DROP TABLE avisos_envios")

    with pytest.raises(RuntimeError, match="libracore-migrar"):
        command.upgrade(_alembic(), "head")

    assert _filas(base_de_antes, "SELECT version_num FROM alembic_version_libraclub") == [(ANTERIOR,)]
    assert _filas(base_de_antes, "SELECT is_nullable FROM information_schema.columns "
                                 "WHERE table_name = 'config_avisos' AND column_name = 'whatsapp'") == [("NO",)]


def test_sin_la_tabla_del_motor_y_sin_avisos_la_0018_sigue(base_temporal, monkeypatch):
    """Una base nueva (o la de la suite, donde el motor arma su schema al arrancar la app): no hay nada que llevar."""
    url = base_temporal("nueva")
    monkeypatch.setenv("DATABASE_URL", url)

    command.upgrade(_alembic(), "head")

    assert _filas(url, "SELECT version_num FROM alembic_version_libraclub") == [("0018_avisos_al_motor",)]


# ── El modo de WhatsApp ─────────────────────────────────────────────────────────────────────────────────────────────


def _con_modo_viejo(url: str, modo: str) -> None:
    with psycopg.connect(_libpq(url), autocommit=True) as con:
        con.execute(
            "INSERT INTO config_avisos (id, whatsapp, avisar_confirmacion, avisar_recordatorio, avisar_cancelacion, "
            "avisar_sena_por_vencer) VALUES (1, %s, true, false, true, true)", (modo,),
        )


def test_el_modo_registro_viejo_pasa_al_motor_una_vez(base_de_antes):
    _con_modo_viejo(base_de_antes, "registro")
    assert config_manager.load_sin_demo()["avisos_whatsapp_modo"] == "apagado", "el control: arranca apagado"

    command.upgrade(_alembic(), "head")

    assert config_manager.load_sin_demo()["avisos_whatsapp_modo"] == "registro"
    # Lo demás de la fila (los tipos) no se toca, y la columna vieja deja de ser obligatoria.
    assert _filas(base_de_antes, "SELECT avisar_recordatorio, whatsapp::text FROM config_avisos") == [
        (False, "registro")]
    assert _filas(base_de_antes, "SELECT is_nullable FROM information_schema.columns "
                                 "WHERE table_name = 'config_avisos' AND column_name = 'whatsapp'") == [("YES",)]


def test_el_modo_apagado_viejo_no_enciende_nada(base_de_antes):
    _con_modo_viejo(base_de_antes, "apagado")

    command.upgrade(_alembic(), "head")

    assert config_manager.load_sin_demo()["avisos_whatsapp_modo"] == "apagado"


def test_si_el_motor_ya_tiene_un_modo_propio_manda_el_del_motor(base_de_antes):
    """El humano ya lo eligió en la pantalla nueva: el valor viejo no lo pisa."""
    _con_modo_viejo(base_de_antes, "registro")
    config_manager.save({**config_manager.load_sin_demo(), "avisos_whatsapp_modo": "evolution"})

    command.upgrade(_alembic(), "head")

    assert config_manager.load_sin_demo()["avisos_whatsapp_modo"] == "evolution"


def test_si_no_se_puede_escribir_la_config_la_migracion_sigue(base_de_antes, monkeypatch):
    """Llevar el modo es una comodidad: no puede tumbar el deploy. El peor caso es WhatsApp apagado (lo seguro)."""
    _con_modo_viejo(base_de_antes, "registro")
    monkeypatch.setattr(config_manager, "CONFIG_PATH", os.path.join("/no/existe/para/nada", "config.json"))

    command.upgrade(_alembic(), "head")

    assert _filas(base_de_antes, "SELECT version_num FROM alembic_version_libraclub") == [("0018_avisos_al_motor",)]


def test_bajar_la_0018_devuelve_la_columna_obligatoria_con_apagado_en_las_filas_nuevas(base_de_antes):
    command.upgrade(_alembic(), "head")
    with psycopg.connect(_libpq(base_de_antes), autocommit=True) as con:
        # Lo que escribe el código nuevo: la fila de tipos sin el modo.
        con.execute("INSERT INTO config_avisos (id, avisar_confirmacion, avisar_recordatorio, avisar_cancelacion, "
                    "avisar_sena_por_vencer) VALUES (1, true, true, true, true)")

    command.downgrade(_alembic(), ANTERIOR)

    assert _filas(base_de_antes, "SELECT whatsapp::text FROM config_avisos") == [("apagado",)]
    assert _filas(base_de_antes, "SELECT is_nullable FROM information_schema.columns "
                                 "WHERE table_name = 'config_avisos' AND column_name = 'whatsapp'") == [("NO",)]


# ── El barrido viejo y el nuevo no se pisan ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def jugador(sesion, cliente, motor):
    cliente.email = "jugador@ejemplo.com"
    sesion.commit()
    return cliente


def _reserva_ya_avisada_por_el_barrido_viejo(
    sesion, cancha, jugador, momento: datetime, *, por_mail: bool = True
) -> Reserva:
    """Una reserva confirmada hace 5 minutos cuya confirmación el barrido VIEJO ya mandó (fila en `avisos`).

    `por_mail=False` es la misma reserva sin la fila de mail: para armar a mano qué más pasó con ella."""
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=CUANDO, estado=EstadoReserva.CONFIRMADA,
    )
    sesion.commit()
    sesion.execute(update(Reserva).where(Reserva.id == reserva.id).values(created_at=momento - timedelta(minutes=5)))
    if por_mail:
        sesion.add(Aviso(
            reserva_id=reserva.id, tipo=TipoAviso.CONFIRMACION, canal=CanalAviso.EMAIL, estado=EstadoAviso.ENVIADO,
            destino="jugador@ejemplo.com", asunto="Turno confirmado", cuerpo="Hola Juan", intentos=1,
        ))
    sesion.commit()
    sesion.expire(reserva)
    return reserva


def test_sin_llevar_los_avisos_el_barrido_nuevo_repite_lo_que_el_viejo_ya_mando(sesion, cancha, jugador, tarifa_base):
    """El control de los de abajo: es lo que la `0018` evita. Sin ella, el cliente recibe la confirmación dos veces."""
    momento = CUANDO - timedelta(hours=10)
    _reserva_ya_avisada_por_el_barrido_viejo(sesion, cancha, jugador, momento)
    mail = ProveedorFalso()

    resumen = servicio.barrer(sesion, mail, momento)

    assert resumen.enviados == 1, "repite: el barrido nuevo no sabe de la tabla vieja"


def test_con_los_avisos_llevados_el_barrido_nuevo_no_repite_nada(sesion, cancha, jugador, tarifa_base):
    momento = CUANDO - timedelta(hours=10)
    _reserva_ya_avisada_por_el_barrido_viejo(sesion, cancha, jugador, momento)
    assert _migracion().llevar_los_avisos(sesion.connection()) == 1
    sesion.commit()
    mail = ProveedorFalso()

    resumen = servicio.barrer(sesion, mail, momento)

    assert resumen.enviados == 0 and mail.enviados == []
    (fila,) = guardados()
    assert fila.estado is EstadoAviso.ENVIADO and fila.clave.startswith("reserva:")


def test_la_cancelacion_se_avisa_si_la_confirmacion_la_mando_el_barrido_viejo(sesion, cancha, jugador, tarifa_base):
    """La cancelación exige que la confirmación haya salido: la que mandó el barrido viejo tiene que contar."""
    momento = CUANDO - timedelta(hours=10)
    reserva = _reserva_ya_avisada_por_el_barrido_viejo(sesion, cancha, jugador, momento)
    _migracion().llevar_los_avisos(sesion.connection())
    sesion.commit()
    servicio_reservas.cambiar_estado(sesion, reserva.id, EstadoReserva.CANCELADA, motivo="Lluvia")
    sesion.commit()
    mail = ProveedorFalso()

    resumen = servicio.barrer(sesion, mail, momento + timedelta(minutes=10))

    assert resumen.enviados == 1
    (destino, asunto, _) = mail.enviados[0]
    assert destino == "jugador@ejemplo.com" and asunto.startswith("Turno cancelado")


def _registrado_en_whatsapp_por_el_barrido_viejo(sesion, reserva: Reserva) -> None:
    sesion.add(Aviso(
        reserva_id=reserva.id, tipo=TipoAviso.CONFIRMACION, canal=CanalAviso.WHATSAPP, estado=EstadoAviso.REGISTRADO,
        destino="5492255123456", cuerpo="*Turno confirmado*", intentos=1,
    ))
    sesion.commit()
    _migracion().llevar_los_avisos(sesion.connection())
    sesion.commit()


def test_lo_registrado_por_el_barrido_viejo_se_manda_con_un_proveedor_real_y_no_con_otro_de_prueba(
    sesion, cancha, jugador, tarifa_base
):
    """La regla del ADR-029 sobrevive a la migración: un `registrado` cierra el tema sólo para un proveedor simulado."""
    momento = CUANDO - timedelta(hours=10)
    reserva = _reserva_ya_avisada_por_el_barrido_viejo(sesion, cancha, jugador, momento, por_mail=False)
    _registrado_en_whatsapp_por_el_barrido_viejo(sesion, reserva)

    de_prueba = servicio.barrer(sesion, ProveedorRegistro(), momento)
    real = ProveedorFalso(CanalAviso.WHATSAPP)
    de_verdad = servicio.barrer(sesion, real, momento)

    assert de_prueba.registrados == 0, "otro proveedor de prueba no lo vuelve a anotar"
    assert de_verdad.enviados == 1 and len(real.enviados) == 1, "el real sí lo manda"
    assert [f.estado for f in guardados() if f.canal is CanalAviso.WHATSAPP] == [EstadoAviso.ENVIADO]


def test_lo_que_el_barrido_viejo_mando_por_mail_no_se_manda_ahora_por_whatsapp(sesion, cancha, jugador, tarifa_base):
    """Un aviso, un canal: el barrido viejo mandaba por los dos, y una confirmación que ya salió por mail y quedó
    `registrada` en WhatsApp no se manda por WhatsApp cuando se conecta Evolution. El cliente ya la recibió."""
    momento = CUANDO - timedelta(hours=10)
    reserva = _reserva_ya_avisada_por_el_barrido_viejo(sesion, cancha, jugador, momento)
    _registrado_en_whatsapp_por_el_barrido_viejo(sesion, reserva)
    real = ProveedorFalso(CanalAviso.WHATSAPP)

    resumen = servicio.barrer(sesion, {"email": ProveedorFalso(), "whatsapp": real}, momento)

    assert resumen.enviados == 0 and real.enviados == []
