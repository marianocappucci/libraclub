"""Los torneos por HTTP: cableado, roles y códigos de error.

`test_torneos.py` prueba las reglas contra el servicio. Éste prueba que **estén
cableadas**: router montado, schemas que aceptan lo que el frontend va a mandar,
excepciones traducidas a códigos, y sobre todo **quién puede hacer qué**.

🔑 La mitad de estos tests corren como `staff` y no como admin. Con todo hecho
desde admin, un endpoint que quedó abierto de más se ve igual que uno bien
cerrado.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.tiempo import a_local
from tests.test_api import _config, api, api_staff  # noqa: F401  (fixtures)

HOY = date(2026, 9, 5)


@pytest.fixture
def complejo(api):  # noqa: F811
    """Una sucursal con dos canchas y tarifa, ya cargadas por la API."""
    sucursal = api.post("/api/sucursales", json={"nombre": "Centro"}).json()
    canchas = [
        api.post(
            "/api/canchas",
            json={
                "sucursal_id": sucursal["id"],
                "nombre": f"Cancha {numero}",
                "deporte": "padel",
                "duracion_turno_min": 90,
            },
        ).json()
        for numero in (1, 2)
    ]
    api.post(
        "/api/tarifas",
        json={
            "sucursal_id": sucursal["id"],
            "nombre": "General",
            "alcance_dia": "todos",
            "hora_desde": "00:00",
            "hora_hasta": "23:59",
            "precio": "10000.00",
            "sena_porcentaje": 50,
        },
    )
    return sucursal, canchas


def _crear(api, sucursal, **extra):  # noqa: F811
    cuerpo = {
        "sucursal_id": sucursal["id"],
        "nombre": extra.pop("nombre", "Apertura"),
        "deporte": "padel",
        "formato": "eliminacion",
        "desde": HOY.isoformat(),
        "sets_para_ganar": 2,
        **extra,
    }
    return api.post("/api/torneos", json=cuerpo)


def _inscribir(api, torneo_id, cuantos, sembrados=0):  # noqa: F811
    for numero in range(1, cuantos + 1):
        respuesta = api.post(
            f"/api/torneos/{torneo_id}/competidores",
            json={
                "nombre": f"Pareja {numero}",
                "siembra": numero if numero <= sembrados else None,
                "integrantes": [
                    {"nombre": f"Jugador {numero}A", "telefono": "2255-100200"},
                    {"nombre": f"Jugador {numero}B", "telefono": None},
                ],
            },
        )
        assert respuesta.status_code == 201, respuesta.text


# ── Cableado ────────────────────────────────────────────────────────────────


def test_el_circuito_completo(api, complejo):  # noqa: F811
    """De crear el torneo a tener campeón, todo por HTTP."""
    sucursal, canchas = complejo
    torneo = _crear(api, sucursal).json()
    assert torneo["estado"] == "armado"

    _inscribir(api, torneo["id"], 4)
    competidores = api.get(f"/api/torneos/{torneo['id']}/competidores").json()
    assert len(competidores) == 4
    assert competidores[0]["integrantes"][0]["nombre"] == "Jugador 1A"

    sorteado = api.post(f"/api/torneos/{torneo['id']}/sortear?semilla=8")
    assert sorteado.status_code == 200, sorteado.text
    assert sorteado.json()["estado"] == "sorteado"
    assert sorteado.json()["semilla"] == 8

    fixture = api.get(f"/api/torneos/{torneo['id']}/fixture").json()
    assert fixture["rondas"] == 2
    assert len(fixture["partidos"]) == 3
    instancias = {p["instancia"] for p in fixture["partidos"]}
    assert instancias == {"Semifinal", "Final"}

    # Cancha y horario a una semifinal.
    semi = next(p for p in fixture["partidos"] if p["instancia"] == "Semifinal")
    programado = api.post(
        f"/api/torneos/partidos/{semi['id']}/programar",
        json={
            "cancha_id": canchas[0]["id"],
            "comienza_at": f"{HOY.isoformat()}T20:00:00",
        },
    )
    assert programado.status_code == 200, programado.text
    assert programado.json()["cancha"] == "Cancha 1"
    # 🔑 Se manda **sin offset** y tiene que quedar en las 20:00 **del
    # complejo**. La API contesta en UTC —23:00Z— y eso está bien; lo que este
    # assert protege es que el servidor no haya leído el naive como UTC, que es
    # el error que pondría el partido tres horas antes. Ver `_con_zona`.
    assert a_local(
        datetime.fromisoformat(programado.json()["comienza_at"])
    ).strftime("%d-%m-%Y %H:%M") == f"{HOY:%d-%m-%Y} 20:00"

    # 🔑 El bloqueo existe en la agenda de verdad, no sólo en el torneo.
    reservas = api.get(
        "/api/reservas",
        params={"cancha_id": canchas[0]["id"], "desde": f"{HOY.isoformat()}T00:00:00"},
    ).json()
    assert any(r["estado"] == "bloqueo" for r in reservas)

    for partido in [p for p in fixture["partidos"] if p["instancia"] == "Semifinal"]:
        respuesta = api.post(
            f"/api/torneos/partidos/{partido['id']}/resultado",
            json={"parciales": [{"puntos_a": 6, "puntos_b": 4},
                                {"puntos_a": 6, "puntos_b": 3}]},
        )
        assert respuesta.status_code == 200, respuesta.text

    fixture = api.get(f"/api/torneos/{torneo['id']}/fixture").json()
    final = next(p for p in fixture["partidos"] if p["instancia"] == "Final")
    assert final["competidor_a"] and final["competidor_b"], "el cuadro no avanzó"

    api.post(
        f"/api/torneos/partidos/{final['id']}/resultado",
        json={"parciales": [{"puntos_a": 6, "puntos_b": 0},
                            {"puntos_a": 6, "puntos_b": 1}]},
    )
    lista = api.get("/api/torneos").json()
    fila = next(t for t in lista if t["id"] == torneo["id"])
    assert fila["estado"] == "finalizado"
    assert fila["campeon"] == final["competidor_a"]
    assert (fila["partidos"], fila["jugados"]) == (3, 3)


def test_la_lista_dice_cuantos_faltan_programar(api, complejo):  # noqa: F811
    """Es lo que le avisa al encargado que le queda trabajo."""
    sucursal, canchas = complejo
    torneo = _crear(api, sucursal).json()
    _inscribir(api, torneo["id"], 4)
    api.post(f"/api/torneos/{torneo['id']}/sortear")
    fila = next(t for t in api.get("/api/torneos").json() if t["id"] == torneo["id"])
    assert fila["sin_programar"] == 3

    fixture = api.get(f"/api/torneos/{torneo['id']}/fixture").json()
    api.post(
        f"/api/torneos/partidos/{fixture['partidos'][0]['id']}/programar",
        json={"cancha_id": canchas[0]["id"],
              "comienza_at": f"{HOY.isoformat()}T20:00:00"},
    )
    fila = next(t for t in api.get("/api/torneos").json() if t["id"] == torneo["id"])
    assert fila["sin_programar"] == 2


def test_un_torneo_de_eliminacion_no_tiene_tabla(api, complejo):  # noqa: F811
    """Devolver una tabla vacía con todos en cero haría creer que hay algo que
    mirar."""
    sucursal, _ = complejo
    torneo = _crear(api, sucursal).json()
    _inscribir(api, torneo["id"], 4)
    api.post(f"/api/torneos/{torneo['id']}/sortear")
    assert api.get(f"/api/torneos/{torneo['id']}/posiciones").json() == []


def test_la_liga_devuelve_una_tabla(api, complejo):  # noqa: F811
    sucursal, _ = complejo
    torneo = _crear(api, sucursal, formato="liga", sets_para_ganar=1).json()
    _inscribir(api, torneo["id"], 4)
    api.post(f"/api/torneos/{torneo['id']}/sortear")
    tablas = api.get(f"/api/torneos/{torneo['id']}/posiciones").json()
    assert len(tablas) == 1
    assert tablas[0]["nombre"] is None
    assert len(tablas[0]["filas"]) == 4


# ── Códigos de error ────────────────────────────────────────────────────────


def test_dos_partidos_en_la_misma_cancha_y_hora_dan_409(api, complejo):  # noqa: F811
    sucursal, canchas = complejo
    torneo = _crear(api, sucursal).json()
    _inscribir(api, torneo["id"], 4)
    api.post(f"/api/torneos/{torneo['id']}/sortear?semilla=3")
    partidos = api.get(f"/api/torneos/{torneo['id']}/fixture").json()["partidos"]
    semis = [p for p in partidos if p["instancia"] == "Semifinal"]
    cuerpo = {"cancha_id": canchas[0]["id"],
              "comienza_at": f"{HOY.isoformat()}T20:00:00"}
    assert api.post(
        f"/api/torneos/partidos/{semis[0]['id']}/programar", json=cuerpo
    ).status_code == 200
    choque = api.post(f"/api/torneos/partidos/{semis[1]['id']}/programar", json=cuerpo)
    assert choque.status_code == 409
    assert "cancha" in choque.json()["detail"].lower()


def test_un_resultado_imposible_da_422(api, complejo):  # noqa: F811
    sucursal, _ = complejo
    torneo = _crear(api, sucursal).json()
    _inscribir(api, torneo["id"], 4)
    api.post(f"/api/torneos/{torneo['id']}/sortear?semilla=3")
    partidos = api.get(f"/api/torneos/{torneo['id']}/fixture").json()["partidos"]
    semi = next(p for p in partidos if p["instancia"] == "Semifinal")
    respuesta = api.post(
        f"/api/torneos/partidos/{semi['id']}/resultado",
        json={"parciales": [{"puntos_a": 6, "puntos_b": 6}]},
    )
    assert respuesta.status_code == 422
    assert "empatado" in respuesta.json()["detail"]


def test_sortear_dos_veces_da_409(api, complejo):  # noqa: F811
    sucursal, _ = complejo
    torneo = _crear(api, sucursal).json()
    _inscribir(api, torneo["id"], 4)
    api.post(f"/api/torneos/{torneo['id']}/sortear")
    assert api.post(f"/api/torneos/{torneo['id']}/sortear").status_code == 409


def test_un_torneo_por_zonas_sin_parametros_no_entra(api, complejo):  # noqa: F811
    """El CHECK de la base lo rechazaría con un 500; el validador da un 422."""
    sucursal, _ = complejo
    respuesta = _crear(api, sucursal, formato="zonas")
    assert respuesta.status_code == 422
    assert "zonas" in respuesta.text


def test_una_eliminacion_con_parametros_de_zona_tampoco(api, complejo):  # noqa: F811
    sucursal, _ = complejo
    respuesta = _crear(api, sucursal, cantidad_zonas=2, clasifican_por_zona=2)
    assert respuesta.status_code == 422


def test_un_torneo_que_no_existe_da_404(api):  # noqa: F811
    assert api.get("/api/torneos/9999").status_code == 404
    assert api.get("/api/torneos/9999/fixture").status_code == 404
    assert api.post("/api/torneos/9999/sortear").status_code == 404


def test_la_ruta_de_partidos_no_se_come_la_de_torneos(api, complejo):  # noqa: F811
    """🔑 `GET /api/torneos/{id}` matchea cualquier segmento único.

    Si `/api/torneos/partidos/...` tuviera un solo segmento entraría por ahí con
    `torneo_id="partidos"` y contestaría un 422 confuso. Es la misma trampa que
    documenta `routers/reservas.py` con `/series/listado`.
    """
    assert api.post("/api/torneos/partidos/9999/liberar").status_code == 404
    assert api.delete("/api/torneos/competidores/9999").status_code == 404


# ── Roles ───────────────────────────────────────────────────────────────────


def test_el_encargado_no_define_ni_sortea_el_torneo(api, api_staff, complejo):  # noqa: F811
    """Definir y sortear son del dueño: cambian lo que el complejo prometió."""
    sucursal, _ = complejo
    assert _crear(api_staff, sucursal, nombre="Del encargado").status_code == 403

    torneo = _crear(api, sucursal).json()
    _inscribir(api, torneo["id"], 4)
    assert api_staff.post(f"/api/torneos/{torneo['id']}/sortear").status_code == 403
    assert api_staff.post(f"/api/torneos/{torneo['id']}/cancelar").status_code == 403
    assert api_staff.post(f"/api/torneos/{torneo['id']}/playoff").status_code == 403
    assert api_staff.put(
        f"/api/torneos/{torneo['id']}",
        json={"nombre": "Otro", "desde": HOY.isoformat(), "hasta": None,
              "observaciones": None},
    ).status_code == 403


def test_el_encargado_si_inscribe_programa_y_carga_resultados(api, api_staff, complejo):  # noqa: F811, E501
    """🔑 El control del test de arriba.

    Sin esto, cerrar todo el router con `require_admin` también lo haría pasar —
    y el mostrador no podría cargar un resultado durante el torneo, que es
    exactamente lo que tiene que poder hacer.
    """
    sucursal, canchas = complejo
    torneo = _crear(api, sucursal).json()

    assert api_staff.post(
        f"/api/torneos/{torneo['id']}/competidores", json={"nombre": "Pareja X"}
    ).status_code == 201
    assert api_staff.get(f"/api/torneos/{torneo['id']}/competidores").status_code == 200
    _inscribir(api, torneo["id"], 3)
    api.post(f"/api/torneos/{torneo['id']}/sortear?semilla=3")

    partidos = api_staff.get(f"/api/torneos/{torneo['id']}/fixture").json()["partidos"]
    semi = next(p for p in partidos if p["competidor_a"] and p["competidor_b"])
    assert api_staff.post(
        f"/api/torneos/partidos/{semi['id']}/programar",
        json={"cancha_id": canchas[0]["id"],
              "comienza_at": f"{HOY.isoformat()}T20:00:00"},
    ).status_code == 200
    assert api_staff.post(
        f"/api/torneos/partidos/{semi['id']}/liberar"
    ).status_code == 200
    assert api_staff.post(
        f"/api/torneos/partidos/{semi['id']}/resultado",
        json={"parciales": [{"puntos_a": 6, "puntos_b": 4},
                            {"puntos_a": 6, "puntos_b": 2}]},
    ).status_code == 200
    assert api_staff.delete(
        f"/api/torneos/partidos/{semi['id']}/resultado"
    ).status_code == 200


def test_sin_sesion_no_se_ve_nada(complejo):  # noqa: F811
    """El torneo es del backoffice: los teléfonos de los integrantes están ahí.

    En el portal público la regla es la contraria y por eso existe
    `servicios/partidos.py`, que nunca devuelve contacto a quien no juega.
    """
    from fastapi.testclient import TestClient

    from app.main import crear_app

    anonimo = TestClient(crear_app(_config()), base_url="https://testserver")
    assert anonimo.get("/api/torneos").status_code == 401
    assert anonimo.get("/api/torneos/1/competidores").status_code == 401


# ── Zonas por HTTP ──────────────────────────────────────────────────────────


def test_zonas_y_playoff_por_http(api, complejo):  # noqa: F811
    sucursal, _ = complejo
    torneo = _crear(
        api, sucursal, formato="zonas", cantidad_zonas=2, clasifican_por_zona=2
    ).json()
    _inscribir(api, torneo["id"], 8, sembrados=2)
    api.post(f"/api/torneos/{torneo['id']}/sortear?semilla=5")

    tablas = api.get(f"/api/torneos/{torneo['id']}/posiciones").json()
    assert [t["nombre"] for t in tablas] == ["Zona A", "Zona B"]

    # El playoff no se larga con los grupos sin terminar.
    assert api.post(f"/api/torneos/{torneo['id']}/playoff").status_code == 409

    fixture = api.get(f"/api/torneos/{torneo['id']}/fixture").json()
    assert all(p["zona"] for p in fixture["partidos"])
    for partido in fixture["partidos"]:
        gana_a = partido["competidor_a_id"] < partido["competidor_b_id"]
        parciales = [(6, 4), (6, 3)] if gana_a else [(4, 6), (3, 6)]
        api.post(
            f"/api/torneos/partidos/{partido['id']}/resultado",
            json={"parciales": [{"puntos_a": a, "puntos_b": b} for a, b in parciales]},
        )

    largado = api.post(f"/api/torneos/{torneo['id']}/playoff")
    assert largado.status_code == 200, largado.text
    fixture = api.get(f"/api/torneos/{torneo['id']}/fixture").json()
    llaves = [p for p in fixture["partidos"] if p["etapa"] == "llaves"]
    assert len(llaves) == 3
    assert {p["instancia"] for p in llaves} == {"Semifinal", "Final"}


def test_cancelar_libera_las_canchas_por_http(api, complejo):  # noqa: F811
    sucursal, canchas = complejo
    torneo = _crear(api, sucursal).json()
    _inscribir(api, torneo["id"], 4)
    api.post(f"/api/torneos/{torneo['id']}/sortear?semilla=3")
    partidos = api.get(f"/api/torneos/{torneo['id']}/fixture").json()["partidos"]
    semis = [p for p in partidos if p["instancia"] == "Semifinal"]
    for numero, partido in enumerate(semis):
        api.post(
            f"/api/torneos/partidos/{partido['id']}/programar",
            json={"cancha_id": canchas[numero]["id"],
                  "comienza_at": f"{HOY.isoformat()}T20:00:00"},
        )

    respuesta = api.post(f"/api/torneos/{torneo['id']}/cancelar")
    assert respuesta.status_code == 200
    assert respuesta.json()["canchas_liberadas"] == 2

    # 🔑 Las canchas quedan vendibles de verdad, no sólo marcadas.
    desde = f"{HOY.isoformat()}T00:00:00"
    hasta = f"{(HOY + timedelta(days=1)).isoformat()}T00:00:00"
    ocupadas = api.get(
        "/api/reservas", params={"desde": desde, "hasta": hasta}
    ).json()
    assert ocupadas == []
