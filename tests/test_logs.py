"""El log de actividad y el de accesos, por HTTP.

El motor es de `libraauth` y lo prueba `libraauth`. Lo que se fija acá es **lo
que decide este producto**: qué entra a la lista blanca, que el cableado esté
puesto y que el router quede detrás de `require_admin`.

🔑 El cableado del log de accesos apagaba **dos** cosas al faltar, no una: sin
`app.state.auth_events` no se anota ningún acceso y, además,
`contar_fallidos_seguro` devuelve `0`, con lo cual el corte por intentos
fallidos del login **nunca dispara**. Por eso hay un test del rate limiting acá
y no sólo del log.
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


SUCURSAL = {
    "nombre": "Complejo Registrado", "direccion": None, "localidad": None,
    "telefono": None, "email": None, "punto_venta_arca": None,
    "activa": True, "observaciones": None,
}


def test_un_alta_queda_en_el_log_de_actividad(api):
    """La prueba de que el listener está enganchado a ESTA sesión.

    Se mide por la API y no por la tabla: lo que puede fallar es el cableado
    —`configurar_auditoria` sobre el `session_factory` del producto—, y eso sólo
    se ejercita escribiendo por donde escribe el frontend.
    """
    alta = api.post("/api/sucursales", json=SUCURSAL)
    assert alta.status_code in (200, 201), alta.text

    logs = api.get("/api/logs")
    assert logs.status_code == 200, logs.text
    actividad = logs.json()["actividad"]
    nuestro = [f for f in actividad if f["entidad"] == "sucursal"]
    assert nuestro, f"no quedó registrada el alta; hay {len(actividad)} filas"
    assert nuestro[0]["accion"] == "crear"
    assert USUARIO in nuestro[0]["usuario"]


def test_una_edicion_registra_QUE_cambio(api):
    """No alcanza con "alguien editó": el diff es lo que hace útil al log."""
    fila = api.post("/api/sucursales", json=SUCURSAL).json()["id"]
    api.put(f"/api/sucursales/{fila}", json={**SUCURSAL, "nombre": "Complejo Renombrado"})

    ediciones = [
        f for f in api.get("/api/logs").json()["actividad"]
        if f["entidad"] == "sucursal" and f["accion"] == "editar"
    ]
    assert ediciones, "la edición no quedó registrada"
    # `cambios` llega **ya parseado** —un dict `{campo: [antes, después]}`—, no
    # como el JSON crudo que guarda la tabla. Se asierta sobre los dos valores:
    # un diff que sólo dijera el nuevo no serviría para "¿qué decía antes?".
    cambios = ediciones[0].get("cambios") or {}
    assert "nombre" in cambios, f"el log no dice qué campo cambió: {cambios}"
    antes, despues = cambios["nombre"]
    assert antes == "Complejo Registrado"
    assert despues == "Complejo Renombrado"


def test_lo_que_NO_entra_a_la_lista_blanca(api, cancha, cliente, tarifa_base):
    """`Serie` queda afuera a propósito, y acá se crea una DE VERDAD.

    🔴 La primera versión de este test no creaba ninguna serie: afirmaba que
    `"serie"` no estaba en el log de una pantalla donde nunca había pasado una,
    así que se cumplía sola. Se comprobó metiendo `Serie` en la lista blanca —
    el test seguía en verde. Ahora se da de alta una cancha fija y **después** se
    exige que la serie no figure, mientras que las reservas que genera sí.

    El motivo de excluirla: cada reserva que la serie produce se audita por su
    cuenta, y auditar además el molde pondría el mismo hecho dos veces — que es
    justo lo que el motor advierte sobre las tablas que ya son historial de algo.
    """
    creada = api.post(
        "/api/reservas/series",
        json={
            "cancha_id": cancha.id, "cliente_id": cliente.id, "dia_semana": 1,
            "hora": "20:00:00", "duracion_min": 90,
            "desde": "2026-09-01", "hasta": "2026-09-30",
        },
    )
    assert creada.status_code == 201, creada.text
    # 🔴 El 201 NO alcanza: una ocurrencia que choca se saltea y se informa,
    # así que una serie puede devolver 201 sin haber creado ni una reserva.
    # Sin tarifa vigente se saltean TODAS —medido: creadas=0, salteadas=5— y
    # la ausencia de `serie` en el log se cumpliría sin probar nada.
    assert creada.json()["creadas"], f"la serie no creó reservas: {creada.text}"

    entidades = {f["entidad"] for f in api.get("/api/logs").json()["actividad"]}
    # Control positivo: si esto fallara, el alta no habría escrito NADA y la
    # ausencia de `serie` no significaría que está excluida.
    assert "reserva" in entidades, f"la serie no generó reservas auditadas: {entidades}"
    assert "serie" not in entidades


def test_el_log_es_solo_de_admin(api):
    """Sin sesión, 401. Es lo que hace que el 200 de los otros signifique algo.

    Depende de `api` —aunque no lo use— porque `crear_app` se niega a levantar
    sin `LIBRACLUB_ADMIN_PASSWORD`, y ese fixture es el que la pone.
    """
    anonimo = TestClient(crear_app(_config()), base_url="https://testserver")
    assert anonimo.get("/api/logs").status_code == 401


def test_el_login_corta_por_intentos_fallidos(api, engine):
    """🔑 El rate limiting, que venía apagado sin que nada lo dijera.

    Sin `app.state.auth_events`, `contar_fallidos_seguro` devuelve 0 y este
    corte nunca ocurre. El test entra por el login real y espera el **429**.
    """
    cliente = TestClient(crear_app(_config()), base_url="https://testserver")
    codigos = [
        cliente.post(
            "/auth/login", json={"username": USUARIO, "password": "no-es-la-clave"}
        ).status_code
        for _ in range(8)
    ]
    assert 401 in codigos, f"ninguno fue rechazado por credenciales: {codigos}"
    assert 429 in codigos, (
        f"el login nunca cortó por intentos fallidos: {codigos}. "
        "Con `auth_events` sin configurar, contar_fallidos_seguro devuelve 0."
    )
