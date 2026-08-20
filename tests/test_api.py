"""El circuito completo por HTTP: dar de alta un complejo y reservar.

Los tests de servicio de al lado prueban las reglas. Este prueba que **estén
cableadas**: routers montados, dependencias de sesión puestas, schemas que
aceptan lo que el frontend va a mandar y errores traducidos a códigos.

Es la diferencia entre "la función anda" y "el alta se puede hacer".
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"


def _config() -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"],
        entorno="test",
        debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
    )


@pytest.fixture
def api(engine, sesion, monkeypatch):
    """Un cliente ya logueado.

    `https://testserver` y no `http`: la cookie de sesión de `libraauth` es
    `Secure`, y sobre http el cliente la acepta pero **no la reenvía**. El login
    daría 200 y todo lo demás 401, que se lee como "el login no anda" cuando lo
    que pasa es que la cookie nunca vuelve.

    Depende de `sesion` por su **limpieza**, no por usarla: ese fixture vacía las
    tablas del dominio antes de cada test.
    """
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(crear_app(_config()), base_url="https://testserver")
    respuesta = cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    )
    assert respuesta.status_code == 200, respuesta.text
    yield cliente
    AuthBase.metadata.drop_all(engine)


def test_salud_falla_cerrado_contra_la_base(api):
    """La sonda consulta la base: no dice `ok` sin haberla tocado."""
    for ruta in ("/salud", "/health"):
        respuesta = api.get(ruta)
        assert respuesta.status_code == 200, ruta
        assert respuesta.json()["estado"] == "ok"


def test_una_ruta_de_api_inexistente_da_404_y_no_el_index(api):
    """🔴 El control que impide el peor monitoreo: el que no puede dar rojo.

    Con la SPA horneada y sin la lista de prefijos de API, `/api/inventado`
    devolvería el `index.html` con **200**. Un chequeo apuntado a una ruta de API
    pasaría exista o no.
    """
    assert api.get("/api/inventado").status_code == 404


def test_sin_sesion_no_se_entra(engine, sesion, monkeypatch):
    """El control que hace que todos los demás signifiquen algo.

    Sin esto, los tests de abajo pasarían igual con los routers montados **sin
    ninguna dependencia de autenticación**, y el complejo quedaría abierto a
    cualquiera que supiera la URL.
    """
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    anonimo = TestClient(
        crear_app(_config(), sembrar_admin=False), base_url="https://testserver"
    )
    try:
        for ruta in ("/api/sucursales", "/api/canchas", "/api/reservas", "/admin/resumen"):
            assert anonimo.get(ruta).status_code in (401, 403), ruta
    finally:
        AuthBase.metadata.drop_all(engine)


def test_alta_completa_y_una_reserva_que_choca(api):
    """El circuito entero, como lo haría alguien dando de alta un complejo."""
    sucursal = api.post(
        "/api/sucursales", json={"nombre": "Complejo Centro", "punto_venta_arca": 1}
    )
    assert sucursal.status_code == 201, sucursal.text
    sucursal_id = sucursal.json()["id"]

    cancha = api.post(
        "/api/canchas",
        json={"sucursal_id": sucursal_id, "nombre": "Cancha 1", "deporte": "padel"},
    )
    assert cancha.status_code == 201, cancha.text
    cancha_id = cancha.json()["id"]

    cliente = api.post("/api/clientes", json={"nombre": "Juan Pérez"})
    assert cliente.status_code == 201, cliente.text
    cliente_id = cliente.json()["id"]

    tarifa = api.post(
        "/api/tarifas",
        json={
            "sucursal_id": sucursal_id,
            "nombre": "Nocturna",
            "alcance_dia": "todos",
            "hora_desde": "18:00:00",
            "hora_hasta": "23:59:00",
            "precio": "12000.00",
            "sena_porcentaje": 50,
        },
    )
    assert tarifa.status_code == 201, tarifa.text

    cuerpo = {
        "cancha_id": cancha_id,
        "cliente_id": cliente_id,
        "comienza_at": "2026-09-01T20:00:00-03:00",
    }
    primera = api.post("/api/reservas", json=cuerpo)
    assert primera.status_code == 201, primera.text
    # El precio salió del tarifario, no del cuerpo del pedido.
    assert primera.json()["precio"] == "12000.00"
    assert primera.json()["sena"] == "6000.00"

    # Y la segunda choca, con 409 y un mensaje que nombra el horario ocupado.
    segunda = api.post("/api/reservas", json=cuerpo)
    assert segunda.status_code == 409, segunda.text
    assert "20:00" in segunda.json()["detail"]


def test_una_franja_sin_tarifa_da_422_y_no_500(api):
    """Falta un dato que el operador tiene que cargar. No se rompió nada.

    Y no una reserva de $0: esa entra a la caja y descuadra el cierre, y nadie
    mira de dónde salió hasta fin de mes.
    """
    sucursal_id = api.post("/api/sucursales", json={"nombre": "Complejo Sur"}).json()["id"]
    cancha_id = api.post(
        "/api/canchas", json={"sucursal_id": sucursal_id, "nombre": "Cancha A"}
    ).json()["id"]
    cliente_id = api.post("/api/clientes", json={"nombre": "Ana"}).json()["id"]

    respuesta = api.post(
        "/api/reservas",
        json={
            "cancha_id": cancha_id,
            "cliente_id": cliente_id,
            "comienza_at": "2026-09-01T07:00:00-03:00",
        },
    )
    assert respuesta.status_code == 422, respuesta.text
    assert "tarifa" in respuesta.json()["detail"].lower()


def test_dos_sucursales_no_pueden_compartir_punto_de_venta(api):
    """La trampa de ARCA, atajada por la base y traducida a un 409 con contexto.

    La numeración de comprobantes es por `(tipo, punto_venta)` y no lleva CUIT:
    dos sucursales con el mismo punto de venta se pisan la numeración entre
    ellas, y ARCA rechaza o duplica.
    """
    assert api.post(
        "/api/sucursales", json={"nombre": "Uno", "punto_venta_arca": 5}
    ).status_code == 201
    choque = api.post("/api/sucursales", json={"nombre": "Dos", "punto_venta_arca": 5})
    assert choque.status_code == 409
    assert "punto de venta" in choque.json()["detail"].lower()

    # Control: sin punto de venta sí pueden convivir — NULL no colisiona.
    assert api.post("/api/sucursales", json={"nombre": "Tres"}).status_code == 201
    assert api.post("/api/sucursales", json={"nombre": "Cuatro"}).status_code == 201


def test_la_grilla_marca_libre_y_ocupado_con_precio(api):
    sucursal_id = api.post("/api/sucursales", json={"nombre": "Complejo Norte"}).json()["id"]
    cancha_id = api.post(
        "/api/canchas",
        json={"sucursal_id": sucursal_id, "nombre": "Cancha 1", "duracion_turno_min": 60},
    ).json()["id"]
    cliente_id = api.post("/api/clientes", json={"nombre": "Ana"}).json()["id"]
    api.post(
        "/api/tarifas",
        json={
            "sucursal_id": sucursal_id,
            "nombre": "General",
            "hora_desde": "00:00:00",
            "hora_hasta": "23:59:00",
            "precio": "9000.00",
        },
    )
    api.post(
        "/api/reservas",
        json={
            "cancha_id": cancha_id,
            "cliente_id": cliente_id,
            "comienza_at": "2026-09-01T20:00:00-03:00",
        },
    )

    grilla = api.get(f"/api/disponibilidad/cancha/{cancha_id}?dia=2026-09-01")
    assert grilla.status_code == 200, grilla.text
    turnos = grilla.json()
    assert turnos, "la grilla no puede venir vacía un día sin feriado"

    ocupados = [t for t in turnos if not t["libre"]]
    assert len(ocupados) == 1
    assert ocupados[0]["cliente"] == "Ana"
    assert ocupados[0]["estado"] == "confirmada"

    libres = [t for t in turnos if t["libre"]]
    assert libres and all(t["precio"] == "9000.00" for t in libres)


def test_el_resumen_del_panel_abre_por_sucursal(api):
    """ADR-009: el agregado sin la apertura no se puede volver a abrir.

    Un dueño con tres sucursales en una instancia y dos en otra vería cinco
    complejos aplastados en dos filas.
    """
    for nombre in ("Centro", "Norte", "Sur"):
        api.post("/api/sucursales", json={"nombre": nombre})

    resumen = api.get("/admin/resumen?desde=2026-09-01&hasta=2026-09-30")
    assert resumen.status_code == 200, resumen.text
    cuerpo = resumen.json()
    assert cuerpo["producto"] == "libraclub"
    nombres = [s["nombre"] for s in cuerpo["sucursales"]]
    # Las tres, aunque ninguna tenga reservas: un bloque ausente no es un cero,
    # y del otro lado no hay forma de distinguir "no hubo" de "no contestó".
    assert nombres == ["Centro", "Norte", "Sur"]
