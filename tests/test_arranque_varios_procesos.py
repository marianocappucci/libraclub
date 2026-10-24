"""El arranque de LibraClub con varios procesos (`uvicorn --workers N`; hoy N = 1).

El candado y sus 2 workers de verdad los prueba el motor (`libracore/tests/test_varios_procesos.py`). Lo que se cuida
acá es que **las siembras del arranque estén adentro del candado**: sin `una_vez_al_arrancar`, dos workers que
arrancan juntos contestan los dos «no existe» y crean el admin (o la caja de cada sucursal) dos veces.
"""

from __future__ import annotations

import contextlib
import threading
import time

import psycopg
import pytest
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth

from app import main as principal
from app.servicios import facturacion
from tests.test_api import CLAVE, USUARIO, _config


@pytest.fixture
def base_de_auth(engine, sesion, monkeypatch):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    yield
    AuthBase.metadata.drop_all(engine)


def test_las_siembras_del_arranque_corren_adentro_de_una_vez_al_arrancar(base_de_auth, monkeypatch):
    eventos = []

    @contextlib.contextmanager
    def espia(nombre, **kw):
        eventos.append(("entra", nombre, kw.get("destino")))
        try:
            yield
        finally:
            eventos.append(("sale", nombre))

    monkeypatch.setattr(principal, "una_vez_al_arrancar", espia)
    monkeypatch.setattr(principal, "ensure_default_admin", lambda *a, **k: eventos.append("ensure_default_admin"))
    monkeypatch.setattr(principal, "ensure_demo_user", lambda *a, **k: eventos.append("ensure_demo_user"))

    config = _config()
    principal.crear_app(config)

    # Las cajas iniciales (`asegurar_cajas_de_todas`) sólo corren si la instancia factura: acá no hay base de LibraCore.
    assert eventos == [
        ("entra", "libraclub-sembrar", config.database_url), "ensure_default_admin", "ensure_demo_user",
        ("sale", "libraclub-sembrar"),
    ]


# ── El esquema del core y del buffet: dos arranques a la vez no se esperan entre sí ─────────────────────────────────


@pytest.fixture
def core_aislado(monkeypatch):
    """`configurar()` deja apuntados `libracore.db.core` y `_hay_base`: globales del proceso. Se restauran."""
    from libracore.db import core as libracore_core

    for nombre in ("_db_path", "_database_url", "_timeout", "_extra_pragmas"):
        monkeypatch.setattr(libracore_core, nombre, getattr(libracore_core, nombre))
    monkeypatch.setattr(facturacion, "_hay_base", facturacion._hay_base)


def _libpq(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _arrancar_en_hilos(url: str, hilos: dict[str, threading.Thread], resultados: dict, tope: float) -> float:
    """Corre los hilos y devuelve cuánto tardaron. Un hilo que no termina en `tope` s es un arranque colgado."""
    inicio = time.monotonic()
    for hilo in hilos.values():
        hilo.start()
    for nombre, hilo in hilos.items():
        hilo.join(timeout=max(tope - (time.monotonic() - inicio), 0.1))
        assert not hilo.is_alive(), f"el arranque {nombre} sigue colgado a los {tope:.0f} s"
    return time.monotonic() - inicio


def _un_arranque(url: str, nombre: str, resultados: dict) -> None:
    try:
        resultados[nombre] = facturacion.configurar(_libpq(url), url_del_dominio=url)
    except Exception as e:  # noqa: BLE001 - el test quiere ver QUÉ murió, no sólo que algo murió
        resultados[nombre] = e


def test_dos_arranques_a_la_vez_sobre_una_base_sin_venta_links_terminan_sanos(
    base_temporal, core_aislado, monkeypatch,
):
    """El primer arranque tras un release que suma una tabla con FK al core, con dos workers: los dos terminan.

    🔴 **El defecto (medido en la demo, 2026-10-24: `TimeoutError: 'libracommerce.esquema' ... 120 s`).**
    `configurar()` son dos transacciones: la 1ª toma el candado del core y después el de LibraCommerce
    (`init_core_schema` + `init_commerce_schema`, que commitea al final y suelta los dos); la 2ª
    (`crear_venta_links` + `cierre_diario.crear_tablas`) toma **sólo** el de LibraCommerce y ahí hace `CREATE TABLE ...
    REFERENCES turnos_caja`, que pide `SHARE ROW EXCLUSIVE` sobre la tabla del core. Si el otro worker está en su 1ª
    transacción, con el `UPDATE turnos_caja ...` de `init_core_schema` (un `ROW EXCLUSIVE` que dura hasta su commit),
    queda un ciclo: A tiene el candado de LibraCommerce y espera la tabla; B tiene la tabla y espera el candado.
    PostgreSQL **no lo ve** —el candado se reintenta con `pg_try_advisory_xact_lock`, nadie queda en una cola de
    bloqueos— y el ciclo dura hasta que B se rinde a los 120 s y el worker muere.

    La coreografía fuerza ese orden (en la vida real es una ventana de milisegundos, y por eso en dev, con un solo
    worker, no pasa): B entra a su 1ª transacción justo cuando A empieza la 2ª. El arreglo es que el esquema se arme
    **de a un arranque por vez** (`una_vez_al_arrancar`), como VentaLibra y Contalibra: B no llega a su 1ª transacción
    hasta que A terminó las dos.
    """
    from libracore import candados

    # El motor espera 120 s antes de rendirse; acá 6 alcanzan para distinguir «esperó» de «quedó colgado».
    monkeypatch.setitem(candados.esperar_candado_de_transaccion.__kwdefaults__, "espera", 6.0)

    url = base_temporal("venta_links")
    a_termino_su_1ra = threading.Event()
    b_esta_en_su_1ra = threading.Event()
    original = facturacion.init_commerce_schema

    def coordinado(conn):
        if threading.current_thread().name == "arranque-B":
            # B ya corrió `init_core_schema`: tiene el candado del core y sus `ROW EXCLUSIVE`. Le da un respiro a A para
            # que entre a su 2ª transacción y tome el candado de LibraCommerce antes de pedirlo.
            b_esta_en_su_1ra.set()
            time.sleep(1.0)
            return original(conn)
        original(conn)
        a_termino_su_1ra.set()
        # Con el arreglo B no llega acá mientras A no termine: se sigue sin él, a los 2 s.
        b_esta_en_su_1ra.wait(timeout=2.0)

    monkeypatch.setattr(facturacion, "init_commerce_schema", coordinado)

    resultados: dict = {}

    def _b():
        a_termino_su_1ra.wait(timeout=30)
        _un_arranque(url, "B", resultados)

    hilos = {
        "A": threading.Thread(target=_un_arranque, args=(url, "A", resultados), name="arranque-A"),
        "B": threading.Thread(target=_b, name="arranque-B"),
    }
    duracion = _arrancar_en_hilos(url, hilos, resultados, tope=60)

    assert resultados == {"A": True, "B": True}, resultados
    assert duracion < 20, f"los dos arranques tardaron {duracion:.1f} s"
    with psycopg.connect(_libpq(url)) as con:
        assert con.execute("SELECT to_regclass('public.venta_links')").fetchone()[0] is not None
        # Y la caja por defecto, una sola: el `if get_default_caja_id() is None` del final también va adentro.
        assert con.execute("SELECT count(*) FROM cajas WHERE es_default = 1").fetchone()[0] == 1


def test_tres_arranques_a_la_vez_dejan_una_sola_caja_por_defecto(base_temporal, core_aislado):
    """Sin coreografía: tres arranques sobre una base vacía terminan sanos y con una sola caja predeterminada."""
    url = base_temporal("tres_arranques")
    resultados: dict = {}
    salida = threading.Barrier(3)

    def _al_unisono(nombre):
        salida.wait(timeout=10)
        _un_arranque(url, nombre, resultados)

    hilos = {n: threading.Thread(target=_al_unisono, args=(n,), name=f"arranque-{n}") for n in "ABC"}
    duracion = _arrancar_en_hilos(url, hilos, resultados, tope=60)

    assert resultados == {"A": True, "B": True, "C": True}, resultados
    assert duracion < 30, f"los tres arranques tardaron {duracion:.1f} s"
    with psycopg.connect(_libpq(url)) as con:
        assert con.execute("SELECT count(*) FROM cajas WHERE es_default = 1").fetchone()[0] == 1
