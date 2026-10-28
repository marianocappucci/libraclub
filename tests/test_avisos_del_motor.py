# ruff: noqa: F811  -- las fixtures importadas se piden por nombre en cada test
"""LibraClub sobre `libracore.avisos` (ADR-030; libracore ADR-090): las rutas del motor, el despacho y el nodo.

Lo que se mide acá es **el enganche**, no el motor (que tiene sus propios tests): que el router del motor esté montado
con el gate de administrador del producto, que el barrido de LibraClub despache por el proveedor que diga la
configuración —registro o Evolution— y que en un nodo no salga nada. Nada real sale: Evolution responde un
`httpx.MockTransport` y el mail es un proveedor falso.

| Ruta | Quién entra |
|---|---|
| `GET`/`PUT /api/avisos/config`, `POST /api/avisos/probar`, `GET /api/avisos/envios` (del motor) | ADMIN |
| `GET /api/avisos/tipos` | STAFF |
| `PUT /api/avisos/tipos` | ADMIN |
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from libraauth.email_sender import SmtpConfig
from libraauth.models import Base as AuthBase
from sqlalchemy import update

from app.models.enums import EstadoReserva
from app.models.reservas import Reserva
from app.servicios import avisos as servicio
from app.servicios import reservas as servicio_reservas
from app.tiempo import TZ
from tests.avisos_apoyo import ProveedorFalso, guardados
from tests.nodo_apoyo import (
    armar_app,
    cliente_logueado,
    nodo,  # noqa: F401  (fixture)
    nodo_apagado,  # noqa: F401  (fixture)
)

#: El turno de todos los tests: martes 01-09-2026 a las 20:00. «Ahora» es 19:00 y la reserva se cargó 5 minutos antes.
CUANDO = datetime(2026, 9, 1, 20, 0, tzinfo=TZ)
AHORA = datetime(2026, 9, 1, 19, 0, tzinfo=TZ)

URL_EVOLUTION = "https://evolution.ejemplo.example"
APIKEY = "apikey-de-prueba-que-no-sale-en-ningun-lado"


@pytest.fixture
def app_avisos(engine, sesion, monkeypatch, base_de_libracore):
    """La app real con un admin y un encargado, y el motor apuntando a la base del test."""
    monkeypatch.setenv("LIBRACLUB_LIBRACORE_DATABASE_URL", base_de_libracore)
    app = armar_app(engine, monkeypatch, base_de_libracore, con_staff=True)
    yield app
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def clientes(app_avisos):
    return {
        "anonimo": TestClient(app_avisos, base_url="https://testserver"),
        "staff": cliente_logueado(app_avisos, "encargado"),
        "admin": cliente_logueado(app_avisos),
    }


@pytest.fixture
def jugador(sesion, cliente):
    cliente.email = "jugador@ejemplo.com"
    sesion.commit()
    return cliente


def _confirmada(sesion, cancha, jugador) -> Reserva:
    reserva = servicio_reservas.crear(
        sesion, cancha_id=cancha.id, cliente_id=jugador.id, comienza_at=CUANDO, estado=EstadoReserva.CONFIRMADA,
    )
    sesion.commit()
    sesion.execute(update(Reserva).where(Reserva.id == reserva.id).values(created_at=AHORA - timedelta(minutes=5)))
    sesion.commit()
    sesion.expire(reserva)
    return reserva


class EvolutionSimulado:
    """El servidor de Evolution: anota cada pedido y contesta como el de verdad. Nada sale de la máquina."""

    def __init__(self) -> None:
        self.pedidos: list[httpx.Request] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        return httpx.Response(201, json={"key": {"id": "BAE5F4A1"}})

    @property
    def transporte(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


# ── Quién entra a cada ruta ─────────────────────────────────────────────────────────────────────────────────────────

#: Un pedido bien formado para cada ruta del motor: el 422 de un cuerpo mal armado llegaría antes que el 403.
PEDIDOS_DEL_MOTOR = [
    ("GET", "/api/avisos/config", None),
    ("PUT", "/api/avisos/config", {}),
    ("POST", "/api/avisos/probar", {"canal": "whatsapp", "destino": "11 5555-1234"}),
    ("GET", "/api/avisos/envios", None),
]


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), PEDIDOS_DEL_MOTOR)
def test_las_rutas_del_motor_son_de_admin(clientes, metodo, ruta, cuerpo):
    """🔴 La configuración dice con qué cuenta de WhatsApp habla el club y el registro tiene los teléfonos y los textos
    de sus clientes: ni el mostrador ni un anónimo entran. Sin el gate del producto (`require_admin`) el router del
    motor no se monta: no tiene default."""
    assert clientes["anonimo"].request(metodo, ruta, json=cuerpo).status_code == 401, ruta
    assert clientes["staff"].request(metodo, ruta, json=cuerpo).status_code == 403, ruta
    assert clientes["admin"].request(metodo, ruta, json=cuerpo).status_code not in (401, 403), ruta


def test_los_tipos_los_ve_el_mostrador_y_los_cambia_el_admin(clientes):
    assert clientes["anonimo"].get("/api/avisos/tipos").status_code == 401
    assert clientes["staff"].get("/api/avisos/tipos").status_code == 200
    assert clientes["admin"].get("/api/avisos/tipos").status_code == 200
    cuerpo = clientes["admin"].get("/api/avisos/tipos").json()
    assert clientes["anonimo"].put("/api/avisos/tipos", json=cuerpo).status_code == 401
    assert clientes["staff"].put("/api/avisos/tipos", json=cuerpo).status_code == 403
    assert clientes["admin"].put("/api/avisos/tipos", json=cuerpo).status_code == 200


def test_toda_ruta_de_avisos_tiene_una_fila_en_esta_matriz(app_avisos):
    """Una ruta nueva bajo `/api/avisos` que nadie decidió quién entra, falla acá."""
    decididas = {ruta for _, ruta, _ in PEDIDOS_DEL_MOTOR} | {"/api/avisos/tipos"}
    montadas = {ruta for ruta in app_avisos.openapi()["paths"] if ruta.startswith("/api/avisos")}
    assert montadas - decididas == set(), f"rutas de avisos sin decidir: {sorted(montadas - decididas)}"
    assert decididas - montadas == set(), f"filas de la matriz que ya no existen: {sorted(decididas - montadas)}"


# ── El despacho de punta a punta: registro y Evolution ──────────────────────────────────────────────────────────────


def test_registro_y_despues_evolution_sin_perder_ni_duplicar_nada(clientes, sesion, cancha, jugador, tarifa_base):
    """🔑 La secuencia del ADR-090: prender WhatsApp en modo registro, mirar qué saldría, conectar Evolution.

    Lo que quedó `registrado` se manda cuando llega el proveedor real —con su contador de intentos en 1—, y el barrido
    siguiente ya no lo repite. Se mide por las rutas reales (`PUT /api/avisos/config`, `GET /api/avisos/envios`) y con
    el barrido de LibraClub, y Evolution es un `httpx.MockTransport`: no sale nada.
    """
    admin = clientes["admin"]
    reserva = _confirmada(sesion, cancha, jugador)
    clave = f"reserva:{reserva.id}:confirmacion:-"
    evolution = EvolutionSimulado()

    def barrer():
        # Como el cron: los dos canales juntos. Sin SMTP el mail no está disponible, así que sólo cuenta WhatsApp.
        proveedores = servicio.construir_proveedores(lambda: SmtpConfig(), transporte=evolution.transporte)
        return servicio.barrer(sesion, proveedores, AHORA)

    # 0. Apagado (el default): no se arma ni se anota nada.
    assert str(barrer()) == "enviados: 0 · fallidos: 0 · omitidos: 0"
    assert guardados() == []

    # 1. Registro: el mensaje se arma y queda anotado, y no sale nada.
    assert admin.put("/api/avisos/config", json={"modo": "registro"}).status_code == 200
    assert barrer().registrados == 1
    (fila,) = admin.get("/api/avisos/envios").json()
    assert (fila["clave"], fila["estado"], fila["proveedor"], fila["canal"]) == (
        clave, "registrado", "registro", "whatsapp")
    assert fila["destino"] == "5492255123456" and fila["cuerpo"].startswith("*Turno confirmado: Cancha 1")
    assert evolution.pedidos == []

    # 2. Se conecta Evolution. La apikey entra por la pantalla y nunca vuelve.
    r = admin.put("/api/avisos/config", json={
        "modo": "evolution", "url": URL_EVOLUTION, "instancia": "club", "apikey": APIKEY,
    })
    assert r.status_code == 200, r.text
    assert r.json()["whatsapp"]["modo"] == "evolution" and r.json()["whatsapp"]["apikey_cargada"] is True
    assert APIKEY not in r.text and APIKEY not in admin.get("/api/avisos/config").text

    # 3. El barrido manda lo que solo se había registrado: una vez, por Evolution, con la apikey en el header.
    assert barrer().enviados == 1
    (pedido,) = evolution.pedidos
    assert str(pedido.url) == f"{URL_EVOLUTION}/message/sendText/club"
    assert pedido.headers["apikey"] == APIKEY
    cuerpo = json.loads(pedido.content)
    assert cuerpo["number"] == "5492255123456" and cuerpo["text"].startswith("*Turno confirmado: Cancha 1")
    (fila,) = admin.get("/api/avisos/envios").json()
    assert (fila["estado"], fila["proveedor"], fila["intentos"], fila["id_externo"]) == (
        "enviado", "evolution", 1, "BAE5F4A1")
    assert APIKEY not in json.dumps(fila)

    # 4. El barrido siguiente no vuelve a mandarlo.
    assert barrer().enviados == 0
    assert len(evolution.pedidos) == 1 and len(guardados()) == 1


def test_probar_el_envio_por_la_ruta_del_motor_usa_lo_guardado(clientes, monkeypatch):
    """«Probar envío» manda un texto fijo por el proveedor configurado; con WhatsApp apagado, 409 y no sale nada."""
    admin = clientes["admin"]
    r = admin.post("/api/avisos/probar", json={"canal": "whatsapp", "destino": "11 5555-1234"})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "no_disponible"

    assert admin.put("/api/avisos/config", json={"modo": "registro"}).status_code == 200
    r = admin.post("/api/avisos/probar", json={"canal": "whatsapp", "destino": "11 5555-1234"})
    assert r.status_code == 200 and r.json()["simulado"] is True
    assert guardados() == [], "una prueba no es un aviso de nadie: no pasa por el registro"


# ── El nodo no manda ────────────────────────────────────────────────────────────────────────────────────────────────


def test_en_un_nodo_la_configuracion_y_la_prueba_dan_409_y_el_registro_se_lee(clientes, nodo):
    """La apikey vive en el central y un nodo no manda: escribir o probar es `solo_en_el_central`, leer no."""
    admin = clientes["admin"]
    for metodo, ruta, cuerpo in (
        ("PUT", "/api/avisos/config", {"modo": "registro"}),
        ("POST", "/api/avisos/probar", {"canal": "whatsapp", "destino": "11 5555-1234"}),
    ):
        r = admin.request(metodo, ruta, json=cuerpo)
        assert r.status_code == 409 and r.json()["detail"]["codigo"] == "solo_en_el_central", (ruta, r.text)
    assert admin.get("/api/avisos/config").status_code == 200
    assert admin.get("/api/avisos/envios").json() == []


def test_el_barrido_en_un_nodo_no_manda_ni_anota_nada(sesion, cancha, jugador, tarifa_base, motor, nodo):
    """El nodo no corre el cron, pero si lo corrieran el motor contesta `en_nodo`: ni red ni tabla (ADR-090)."""
    _confirmada(sesion, cancha, jugador)
    mail = ProveedorFalso()

    resumen = servicio.barrer(sesion, mail, AHORA)

    assert resumen.sin_proveedor == 1 and resumen.enviados == 0
    assert mail.enviados == [] and guardados() == []


def test_el_central_si_manda_con_el_mismo_barrido(sesion, cancha, jugador, tarifa_base, motor, nodo_apagado):
    """El control del anterior: sin `LIBRAEDGE_NODE_ID` el mismo barrido manda."""
    _confirmada(sesion, cancha, jugador)
    mail = ProveedorFalso()

    resumen = servicio.barrer(sesion, mail, AHORA)

    assert resumen.enviados == 1 and len(mail.enviados) == 1
