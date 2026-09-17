"""El cierre diario por sucursal: preview, cerrar, listar y los dos tickets.

Fase 2 de producto sobre el motor de LibraCore v1.98.0 (ADR-011): acá se
monta `build_cierre_diario_router`, se resuelve el nombre de la sucursal
—que vive del lado del DOMINIO, no de LibraCore— y se decide quién puede
cerrar. Lo que prueba LibraCore es el cálculo del cierre en sí (los totales,
la foto por turno/caja/sucursal, la numeración); lo que se fija acá es lo que
es de este producto: que el gate sea admin-o-staff, que el ticket muestre el
nombre de la sucursal y que el día cerrado bloquee abrir un turno con un
mensaje entendible.
"""

from __future__ import annotations

import io
import os
import re

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from pypdf import PdfReader

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"


def _url_core() -> str:
    url = os.environ["DATABASE_URL"]
    base, _, nombre = url.rpartition("/")
    return f"{base}/{nombre}_core".replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture
def base_de_libracore():
    url = _url_core()
    servidor, _, nombre = url.rpartition("/")
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{nombre}"')
    yield url
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')


def _config(url_core: str | None) -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos", libracore_database_url=url_core,
    )


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    crear_schema_de_auth(engine)
    cliente = TestClient(crear_app(_config(base_de_libracore)), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


def _staff(api, engine, base_de_libracore, usuario: str, clave: str):
    """Un cajero (`staff`) con sesión propia. Devuelve su cliente."""
    r = api.post("/api/usuarios", json={
        "username": usuario, "name": usuario.title(), "password": clave, "role": "staff"})
    assert r.status_code in (200, 201), r.text
    cliente = TestClient(crear_app(_config(base_de_libracore)), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": usuario, "password": clave}
    ).status_code == 200, "no se pudo iniciar sesión como el cajero"
    return cliente


def _texto_del_pdf(contenido: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(contenido)).pages)


def _abrir_y_cerrar_turno(api, sucursal, monto_inicial="1000", cobro="5000",
                          declarado="6000", nombre_caja=None):
    """Abre una caja de esta sede (creándola si hace falta), cobra y cierra el
    turno del usuario de `api`. Devuelve el turno cerrado."""
    cajas = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()
    if nombre_caja is not None or not cajas:
        alta = api.post("/api/cajas", json={
            "nombre": nombre_caja or "Mostrador", "sucursal_id": sucursal.id,
        })
        assert alta.status_code == 201, alta.text
        caja = alta.json()
    else:
        caja = cajas[0]
    r = api.post("/api/caja/turnos", json={
        "monto_inicial": monto_inicial, "caja_id": caja["id"],
    })
    assert r.status_code == 201, r.text
    turno = r.json()
    if cobro:
        c = api.post("/api/caja/cobros", json={
            "monto": cobro, "concepto": "Cancha 1", "medio_pago": "efectivo",
        })
        assert c.status_code == 200, c.text
    cerrado = api.post(f"/api/caja/turnos/{turno['id']}/cerrar",
                       json={"monto_declarado": declarado})
    assert cerrado.status_code == 200, cerrado.text
    return cerrado.json()


# ── Cerrar el día ────────────────────────────────────────────────────────


def test_cerrar_el_dia_con_dos_cajeros_y_dos_medios(api, engine, base_de_libracore, sucursal):
    """El caso normal: dos turnos, cada uno con su propio medio de pago."""
    _abrir_y_cerrar_turno(api, sucursal, monto_inicial="1000", cobro="5000",
                          declarado="6000", nombre_caja="Mostrador")

    cajero2 = _staff(api, engine, base_de_libracore, "cajero2", "clave-c2")
    caja2 = api.post("/api/cajas", json={
        "nombre": "Buffet", "sucursal_id": sucursal.id,
    }).json()
    abierto = cajero2.post("/api/caja/turnos", json={
        "monto_inicial": "0", "caja_id": caja2["id"],
    })
    assert abierto.status_code == 201, abierto.text
    cajero2.post("/api/caja/cobros", json={
        "monto": "9000", "concepto": "Buffet", "medio_pago": "transferencia",
    })
    cerrado2 = cajero2.post(f"/api/caja/turnos/{abierto.json()['id']}/cerrar",
                            json={"monto_declarado": "0"})
    assert cerrado2.status_code == 200, cerrado2.text

    r = api.post("/api/cierre-diario/cerrar", json={"sucursal_id": sucursal.id})
    assert r.status_code == 200, r.text
    cierre = r.json()
    assert cierre["numero"] == 1
    assert len(cierre["turnos"]) == 2
    assert cierre["monto_esperado_total"] == 6000.0  # 1000 inicial + 5000 efectivo
    assert cierre["monto_declarado_total"] == 6000.0
    assert cierre["diferencia_total"] == 0.0
    medios = {m["medio_pago"]: m for m in cierre["medios"]}
    assert medios["efectivo"]["neto"] == 5000.0
    assert medios["transferencia"]["neto"] == 9000.0


def test_un_turno_abierto_bloquea_el_cierre_con_422(api, sucursal, abrir_caja):
    abrir_caja(api, sucursal, "0")
    r = api.post("/api/cierre-diario/cerrar", json={"sucursal_id": sucursal.id})
    assert r.status_code == 422, r.text
    assert "abierto" in r.json()["detail"]


def test_cerrar_dos_veces_el_mismo_dia_da_409(api, sucursal):
    _abrir_y_cerrar_turno(api, sucursal)
    primero = api.post("/api/cierre-diario/cerrar", json={"sucursal_id": sucursal.id})
    assert primero.status_code == 200, primero.text

    segundo = api.post("/api/cierre-diario/cerrar", json={"sucursal_id": sucursal.id})
    assert segundo.status_code == 409, segundo.text


def test_un_staff_puede_cerrar_el_dia(api, engine, base_de_libracore, sucursal):
    """Pedido del humano (2026-09-13): el cierre lo puede hacer el admin O un
    cajero — en LibraClub el cajero es el rol `staff`."""
    cajero = _staff(api, engine, base_de_libracore, "cajero-cierre", "clave-cc")
    caja = api.post("/api/cajas", json={
        "nombre": "Mostrador", "sucursal_id": sucursal.id,
    }).json()
    abierto = cajero.post("/api/caja/turnos", json={
        "monto_inicial": "0", "caja_id": caja["id"],
    })
    assert abierto.status_code == 201, abierto.text
    cerrado = cajero.post(f"/api/caja/turnos/{abierto.json()['id']}/cerrar",
                          json={"monto_declarado": "0"})
    assert cerrado.status_code == 200, cerrado.text

    r = cajero.post("/api/cierre-diario/cerrar", json={"sucursal_id": sucursal.id})
    assert r.status_code == 200, r.text


def test_el_listado_trae_QUIEN_CERRO(api, sucursal):
    """El listado muestra quién cerró: `cerrado_por_nombre` lo trae el motor
    (`listar_cierres`, libracore v1.98.1). Antes de esa versión venía sin
    nombre, y LibraClub lo agregaba con un endpoint propio que tapaba al del
    motor en la misma ruta; este test es el que asegura que sacarlo no dejó
    un id crudo en la columna que más importa."""
    _abrir_y_cerrar_turno(api, sucursal)
    api.post("/api/cierre-diario/cerrar", json={"sucursal_id": sucursal.id})

    r = api.get(f"/api/cierre-diario?sucursal_id={sucursal.id}")
    assert r.status_code == 200, r.text
    listado = r.json()
    assert len(listado) == 1
    # 🔑 Si el JOIN no encontrara al usuario, el motor deja escrito
    # "usuario #<id>" — el negativo de que la resolución de verdad ocurrió.
    assert not listado[0]["cerrado_por_nombre"].startswith("usuario #"), listado[0]


def test_preview_muestra_los_turnos_abiertos_y_los_cerrados(api, sucursal, abrir_caja):
    """El preview no cierra nada — lo que muestra es lo que cerrar() haría."""
    _abrir_y_cerrar_turno(api, sucursal, nombre_caja="Mostrador")
    abrir_caja(api, sucursal, "0")

    r = api.get(f"/api/cierre-diario/preview?sucursal_id={sucursal.id}")
    assert r.status_code == 200, r.text
    preview = r.json()
    assert len(preview["turnos_abiertos"]) == 1
    assert len(preview["turnos"]) == 1
    assert preview["puede_cerrar"] is False
    assert preview["ya_cerrado"] is False


# ── El ticket ────────────────────────────────────────────────────────────


def test_el_ticket_del_cierre_es_pdf_con_sucursal_y_fecha(api, sucursal):
    _abrir_y_cerrar_turno(api, sucursal)
    cierre = api.post(
        "/api/cierre-diario/cerrar", json={"sucursal_id": sucursal.id, "fecha": "2026-09-01"},
    ).json()

    r = api.get(f"/api/cierre-diario/{cierre['id']}/ticket")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    texto = _texto_del_pdf(r.content)
    assert sucursal.nombre in texto
    assert "01-09-2026" in texto, texto


def test_el_ticket_del_turno_responde_pdf_con_sucursal_y_fecha(api, sucursal):
    turno = _abrir_y_cerrar_turno(api, sucursal)

    r = api.get(f"/api/cierre-diario/turno/{turno['id']}/ticket")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    texto = _texto_del_pdf(r.content)
    assert sucursal.nombre in texto
    # Sin fecha fija acá (el turno se abre y cierra "ahora"): se valida el
    # FORMATO `dd-mm-aaaa`, no un valor puntual.
    assert re.search(r"\b\d{2}-\d{2}-\d{4}\b", texto), texto


def test_el_ticket_de_un_turno_abierto_da_409(api, sucursal, abrir_caja):
    abrir_caja(api, sucursal, "0")
    turno = api.get("/api/caja/turnos/actual").json()["turno"]
    r = api.get(f"/api/cierre-diario/turno/{turno['id']}/ticket")
    assert r.status_code == 409, r.text


# ── El día cerrado bloquea abrir un turno ──────────────────────────────────


def test_con_el_dia_cerrado_no_se_abre_un_turno_y_el_error_es_entendible(
    api, sucursal,
):
    """🔴 Antes de mapear `DiaCerradoError`, esto llegaba como 500: el motor
    levanta la excepción desde `create_turno()` y `app/routers/caja.py` sólo
    atrapaba `TurnoYaAbierto`."""
    _abrir_y_cerrar_turno(api, sucursal, nombre_caja="Mostrador")
    cerrar = api.post("/api/cierre-diario/cerrar", json={"sucursal_id": sucursal.id})
    assert cerrar.status_code == 200, cerrar.text

    caja = api.get(f"/api/cajas?sucursal_id={sucursal.id}").json()[0]
    r = api.post("/api/caja/turnos", json={"monto_inicial": "0", "caja_id": caja["id"]})
    assert r.status_code == 409, r.text
    assert "cerrado" in r.json()["detail"].lower()


# ── Quién puede cerrar ──────────────────────────────────────────────────────
#
# Sólo existen dos roles en este producto (`admin`, `staff` — ver
# `app/routers/usuarios.py`, `Rol`), y las dos pueden cerrar por decisión del
# humano (2026-09-13). No hay, entonces, un tercer rol legítimo con el que dar
# de alta un usuario "sin permiso" para probar el rechazo por API — el gate
# real (`autorizar_cierre=Depends(require_staff)`, en `app/main.py`) se
# verificó por mutación manual: sacándolo del montaje, este archivo entero
# sigue en verde en `test_un_staff_puede_cerrar_el_dia` (porque staff igual
# puede pasar sin el gate: el módulo entero ya exige `require_staff` como
# `usuario_actual`) pero un test que diera de alta un tercer rol y esperara
# 403 se pondría rojo si existiera — documentado en el reporte de esta tarea
# como lo que queda dudoso, no simulado acá con un rol que el producto no
# tiene.
