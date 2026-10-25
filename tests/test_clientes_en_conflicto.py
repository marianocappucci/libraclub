"""Los cambios de clientes en conflicto: ver los dos valores y elegir cuál queda (ADR-022, tercer addendum).

Se arma el conflicto como en la vida real: el alta y la edición de la PC del club pasan por el receptor real del central
(`SyncReceiver` con el despachador de la app) y la edición, que choca con lo que alguien cambió en la web, queda en
revisión manual. Se recorre por HTTP, que es lo que ve el mostrador.
"""

# Los fixtures se importan de otros módulos y se piden por nombre en cada test: ruff lo lee como «redefinición de un
# import sin usar» (F811). La suite pone un `noqa` por test; acá, uno por archivo.
# ruff: noqa: F811

from __future__ import annotations

import json

import pytest
from libraedge.sync.receiver import SyncReceiver
from sqlalchemy import text

from app.servicios import clientes_nodo
from tests.clientes_nodo_apoyo import alta, edicion, nodo_clientes, operacion_alta, operacion_edicion  # noqa: F401
from tests.reservas_nodo_apoyo import central  # noqa: F401  (fixture)
from tests.test_api import api, api_staff  # noqa: F401  (fixtures)

URL = "/api/clientes-en-conflicto"
OPERACION = "club-1:2"


def _subir(central, *operaciones) -> list[str]:
    """Pasa las operaciones por el receptor real del central, en orden."""
    from app.routers.sincronizacion_offline import despachador

    resultados = []
    for operacion in operaciones:
        r = SyncReceiver(central, despachador=despachador).accept(operacion)
        central.commit()
        resultados.append(r.result)
    return resultados


def _web(central, id_cliente: int, **campos) -> None:
    """Alguien edita al cliente en la web."""
    asignaciones = ", ".join(f"{c} = ?" for c in campos)
    central.execute(f"UPDATE clientes SET {asignaciones} WHERE id = ?", (*campos.values(), id_cliente))
    central.commit()


def _cliente(central, id_cliente: int) -> dict:
    fila = central.execute(
        "SELECT nombre, telefono, email, documento, observaciones, activo FROM clientes WHERE id = ?", (id_cliente,)
    ).fetchone()
    return dict(zip(("nombre", "telefono", "email", "documento", "observaciones", "activo"), fila, strict=True))


def _estado_en_inbox(central, operacion_id: str = OPERACION) -> tuple:
    return tuple(central.execute(
        "SELECT status, resuelto_por, resolucion FROM sync_inbox WHERE operation_id = ?", (operacion_id,)
    ).fetchone())


def _actividad(central) -> list[tuple]:
    return [tuple(f) for f in central.execute(
        "SELECT usuario, accion, entidad, entidad_id, descripcion, cambios FROM actividad_log ORDER BY id"
    ).fetchall()]


@pytest.fixture
def conflicto(central):
    """Juan Pérez se dio de alta en la PC del club (teléfono 111, email a@x.com). Antes de que subiera la corrección
    de la PC (teléfono 333, email pc@x.com, documento 30123456), en la web le cambiaron el teléfono (222) y el email
    (web@x.com). Choca en teléfono y en email; el documento no chocaba. Devuelve el id del cliente en la web."""
    central.execute("TRUNCATE sync_inbox, libraedge_mapeo, actividad_log RESTART IDENTITY")
    central.commit()
    resultados = _subir(central, operacion_alta(alta(-1, "Juan Pérez", telefono="111", email="a@x.com")))
    assert resultados == ["accepted"]
    id_cliente = central.execute("SELECT id FROM clientes WHERE nombre = 'Juan Pérez'").fetchone()[0]
    _web(central, id_cliente, telefono="222", email="web@x.com")
    resultados = _subir(central, operacion_edicion(edicion(
        -1,
        antes={"telefono": "111", "email": "a@x.com", "documento": None},
        despues={"telefono": "333", "email": "pc@x.com", "documento": "30123456"},
    )))
    assert resultados == ["rejected"], "la edición tiene que quedar en revisión manual"
    assert _estado_en_inbox(central)[0] == "manual_review"
    return id_cliente


def _elegir(api_staff, central, **extra):
    """El cuerpo de un `resolver` como lo manda la pantalla: lo que ve hoy la web en cada campo y la elección."""
    cuerpo = {
        "elecciones": {"telefono": "pc", "email": "web"},
        "vistos": {"telefono": "222", "email": "web@x.com", "documento": None},
    }
    cuerpo.update(extra)
    return api_staff.post(f"{URL}/{OPERACION}/resolver", json=cuerpo)


# ── Listar y mostrar los dos cambios ─────────────────────────────────────────


def test_sin_ediciones_en_revision_la_lista_esta_vacia(api_staff, central):
    central.execute("TRUNCATE sync_inbox")
    central.commit()
    respuesta = api_staff.get(URL)
    assert respuesta.status_code == 200 and respuesta.json() == []


def test_la_lista_trae_la_edicion_en_conflicto_con_los_dos_valores(api_staff, central, conflicto):
    respuesta = api_staff.get(URL)
    assert respuesta.status_code == 200, respuesta.text
    (item,) = respuesta.json()

    assert item["operacion_id"] == OPERACION
    assert item["cliente_id"] == conflicto and item["cliente_nombre"] == "Juan Pérez"
    assert item["en_conflicto"] == 2 and item["se_puede_resolver"] is True
    por_campo = {c["campo"]: c for c in item["campos"]}
    assert por_campo["telefono"] == {
        "campo": "telefono", "etiqueta": "Teléfono", "estado": "conflicto", "antes": "111", "web": "222", "pc": "333"
    }
    assert (por_campo["email"]["web"], por_campo["email"]["pc"], por_campo["email"]["antes"]) == (
        "web@x.com", "pc@x.com", "a@x.com"
    )
    # El documento no chocaba: la web no lo había tocado. Se aplica solo.
    assert por_campo["documento"]["estado"] == "se_aplica"
    assert (por_campo["documento"]["web"], por_campo["documento"]["pc"]) == (None, "30123456")


def test_el_detalle_muestra_lo_mismo(api_staff, central, conflicto):
    respuesta = api_staff.get(f"{URL}/{OPERACION}")
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == api_staff.get(URL).json()[0]


def test_una_edicion_sin_choque_no_es_un_conflicto(api_staff, central):
    """Sólo cambió el teléfono en la PC y la web no lo tocó: el aplicador la aplica sola, no queda en revisión."""
    central.execute("TRUNCATE sync_inbox, libraedge_mapeo, actividad_log RESTART IDENTITY")
    central.commit()
    _subir(central, operacion_alta(alta(-1, "Ana", telefono="111")))
    assert _subir(central, operacion_edicion(edicion(-1, antes={"telefono": "111"}, despues={"telefono": "333"}))) == [
        "accepted"
    ]
    assert api_staff.get(URL).json() == []


def test_una_edicion_que_espera_su_alta_no_aparece(api_staff, central):
    """Sin el alta aplicada no hay número definitivo (`SinMapeo`): eso no es un conflicto de datos."""
    central.execute("TRUNCATE sync_inbox, libraedge_mapeo, actividad_log RESTART IDENTITY")
    central.commit()
    assert _subir(central, operacion_edicion(edicion(-1, antes={"telefono": "1"}, despues={"telefono": "2"}))) == [
        "rejected"
    ]
    assert api_staff.get(URL).json() == []
    assert api_staff.get(f"{URL}/{OPERACION}").status_code == 404


def test_un_id_que_no_existe_da_404(api_staff, central, conflicto):
    assert api_staff.get(f"{URL}/club-1:99").status_code == 404
    assert api_staff.post(f"{URL}/club-1:99/resolver", json={"elecciones": {}, "vistos": {}}).status_code == 404


# ── Resolver ─────────────────────────────────────────────────────────────────


def test_elegir_mixto_un_campo_de_cada_lado_y_aplicar_lo_que_no_chocaba(api_staff, central, conflicto):
    respuesta = _elegir(api_staff, central)
    assert respuesta.status_code == 200, respuesta.text
    assert sorted(respuesta.json()["aplicados"]) == ["documento", "telefono"]

    cliente = _cliente(central, conflicto)
    assert cliente["telefono"] == "333", "elegí la PC"
    assert cliente["email"] == "web@x.com", "elegí la web: queda como estaba"
    assert cliente["documento"] == "30123456", "no chocaba: se aplica"
    assert api_staff.get(URL).json() == [], "ya no está en la lista"


def test_dejar_todo_como_esta_en_la_web_igual_cierra_la_edicion(api_staff, central, conflicto):
    respuesta = _elegir(api_staff, central, elecciones={"telefono": "web", "email": "web"})
    assert respuesta.status_code == 200, respuesta.text
    cliente = _cliente(central, conflicto)
    assert (cliente["telefono"], cliente["email"]) == ("222", "web@x.com")
    assert cliente["documento"] == "30123456"
    assert api_staff.get(URL).json() == []


def test_elegir_todo_de_la_pc(api_staff, central, conflicto):
    respuesta = _elegir(api_staff, central, elecciones={"telefono": "pc", "email": "pc"})
    assert respuesta.status_code == 200, respuesta.text
    cliente = _cliente(central, conflicto)
    assert (cliente["telefono"], cliente["email"]) == ("333", "pc@x.com")


def test_la_operacion_queda_resuelta_en_libraedge_y_el_nodo_recibe_duplicate(api_staff, central, conflicto):
    assert _elegir(api_staff, central).status_code == 200
    estado, por, resolucion = _estado_en_inbox(central)
    assert estado == "applied" and por == "encargado" and resolucion == "reintentada y aplicada"
    # La PC del club la reenvía (`libraedge-nodo revision reenviar`): el central ya la tiene y no la vuelve a aplicar.
    _web(central, conflicto, telefono="999")
    reenviada = operacion_edicion(edicion(
        -1,
        antes={"telefono": "111", "email": "a@x.com", "documento": None},
        despues={"telefono": "333", "email": "pc@x.com", "documento": "30123456"},
    ))
    assert _subir(central, reenviada) == ["duplicate"]
    assert _cliente(central, conflicto)["telefono"] == "999"


def test_queda_en_el_log_de_actividad_quien_eligio_que(api_staff, central, conflicto):
    assert _elegir(api_staff, central).status_code == 200
    ((usuario, accion, entidad, entidad_id, descripcion, cambios),) = _actividad(central)

    assert (usuario, accion, entidad, entidad_id) == ("encargado", "editar", "cliente", str(conflicto))
    assert "Juan Pérez" in descripcion
    assert "Teléfono: lo de la PC" in descripcion and "Email: lo de la web" in descripcion
    # Sólo lo que de verdad cambió, de lo que había en la web a lo que quedó.
    assert json.loads(cambios) == {"telefono": ["222", "333"], "documento": [None, "30123456"]}


def test_resolver_dos_veces_no_aplica_dos_veces(api_staff, central, conflicto):
    assert _elegir(api_staff, central).status_code == 200
    _web(central, conflicto, telefono="777")

    segunda = _elegir(api_staff, central)

    assert segunda.status_code == 409, segunda.text
    assert segunda.json()["detail"]["codigo"] == "ya_resuelta"
    assert _cliente(central, conflicto)["telefono"] == "777", "la segunda no pisó nada"
    assert len(_actividad(central)) == 1, "ni anotó otra vez"
    assert api_staff.get(f"{URL}/{OPERACION}").status_code == 409


def test_si_el_cliente_cambio_otra_vez_en_la_web_avisa_y_no_pisa(api_staff, central, conflicto):
    """La pantalla mostró teléfono 222; mientras elegían, alguien lo cambió a 444. No se aplica nada."""
    _web(central, conflicto, telefono="444")

    respuesta = _elegir(api_staff, central)

    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"]["codigo"] == "cambio_en_la_web"
    assert "Teléfono" in respuesta.json()["detail"]["mensaje"]
    cliente = _cliente(central, conflicto)
    assert (cliente["telefono"], cliente["email"], cliente["documento"]) == ("444", "web@x.com", None)
    assert _estado_en_inbox(central)[0] == "manual_review", "sigue esperando"
    assert _actividad(central) == []
    # Recargada, la pantalla ve lo de ahora y se puede elegir.
    nuevo = api_staff.get(f"{URL}/{OPERACION}").json()
    assert {c["campo"]: c["web"] for c in nuevo["campos"]}["telefono"] == "444"
    otra = _elegir(api_staff, central, vistos={"telefono": "444", "email": "web@x.com", "documento": None})
    assert otra.status_code == 200, otra.text
    assert _cliente(central, conflicto)["telefono"] == "333"


def test_un_campo_que_no_chocaba_y_cambio_en_la_web_tambien_frena(api_staff, central, conflicto):
    _web(central, conflicto, documento="11111111")
    respuesta = _elegir(api_staff, central)
    assert respuesta.status_code == 409 and respuesta.json()["detail"]["codigo"] == "cambio_en_la_web"
    assert _cliente(central, conflicto)["documento"] == "11111111"


def test_hay_que_elegir_en_todos_los_campos_que_chocan(api_staff, central, conflicto):
    respuesta = _elegir(api_staff, central, elecciones={"telefono": "pc"})
    assert respuesta.status_code == 422 and "Email" in respuesta.json()["detail"]
    assert _cliente(central, conflicto)["telefono"] == "222"
    assert _estado_en_inbox(central)[0] == "manual_review"


def test_no_se_elige_donde_no_hay_conflicto(api_staff, central, conflicto):
    respuesta = _elegir(api_staff, central, elecciones={"telefono": "pc", "email": "web", "documento": "pc"})
    assert respuesta.status_code == 422 and "Documento" in respuesta.json()["detail"]


def test_la_eleccion_es_la_web_o_la_pc(api_staff, central, conflicto):
    respuesta = _elegir(api_staff, central, elecciones={"telefono": "otra", "email": "web"})
    assert respuesta.status_code == 422


def test_la_pantalla_tiene_que_mandar_lo_que_vio(api_staff, central, conflicto):
    respuesta = _elegir(api_staff, central, vistos={"telefono": "222"})
    assert respuesta.status_code == 422
    assert _cliente(central, conflicto)["telefono"] == "222"


def test_una_baja_elegida_a_mano(api_staff, central):
    """También se eligen los campos de sí/no: la PC lo dio de baja y la web lo había dejado activo con otro nombre."""
    central.execute("TRUNCATE sync_inbox, libraedge_mapeo, actividad_log RESTART IDENTITY")
    central.commit()
    _subir(central, operacion_alta(alta(-1, "Ana")))
    id_cliente = central.execute("SELECT id FROM clientes").fetchone()[0]
    _web(central, id_cliente, nombre="Ana María")
    _subir(central, operacion_edicion(edicion(
        -1, antes={"nombre": "Ana", "activo": True}, despues={"nombre": "Anita", "activo": False}
    )))
    (item,) = api_staff.get(URL).json()
    assert {c["campo"]: c["estado"] for c in item["campos"]} == {"nombre": "conflicto", "activo": "se_aplica"}

    respuesta = api_staff.post(f"{URL}/{OPERACION}/resolver", json={
        "elecciones": {"nombre": "web"}, "vistos": {"nombre": "Ana María", "activo": True},
    })
    assert respuesta.status_code == 200, respuesta.text
    cliente = _cliente(central, id_cliente)
    assert cliente["nombre"] == "Ana María" and cliente["activo"] is False


# ── Permisos ─────────────────────────────────────────────────────────────────


def test_hace_falta_sesion(api, central, conflicto):
    api.cookies.clear()
    assert api.get(URL).status_code in (401, 403)
    assert api.get(f"{URL}/{OPERACION}").status_code in (401, 403)
    assert api.post(f"{URL}/{OPERACION}/resolver", json={"elecciones": {}, "vistos": {}}).status_code in (401, 403)


def test_el_admin_tambien_puede(api, central, conflicto):
    respuesta = api.post(f"{URL}/{OPERACION}/resolver", json={
        "elecciones": {"telefono": "web", "email": "web"},
        "vistos": {"telefono": "222", "email": "web@x.com", "documento": None},
    })
    assert respuesta.status_code == 200, respuesta.text


def test_en_la_pc_del_club_la_lista_viene_vacia_y_resolver_da_409(api_staff, central, conflicto, nodo_clientes):
    assert clientes_nodo.en_un_nodo()
    assert api_staff.get(URL).json() == []

    detalle = api_staff.get(f"{URL}/{OPERACION}")
    assert detalle.status_code == 409 and detalle.json()["detail"]["codigo"] == "solo_en_el_central"
    resolver = _elegir(api_staff, central)
    assert resolver.status_code == 409 and resolver.json()["detail"]["codigo"] == "solo_en_el_central"
    assert _cliente(central, conflicto)["telefono"] == "222", "no se aplicó nada"
    assert _estado_en_inbox(central)[0] == "manual_review"


def test_el_servicio_no_toca_la_consulta_sin_tablas_de_libraedge(sesion):
    """Una base sin `sync_inbox` (una instalación vieja) no tira error: no hay nada para revisar."""
    from app.servicios import ediciones_en_conflicto

    sesion.execute(text("DROP TABLE IF EXISTS sync_inbox"))
    sesion.commit()
    try:
        assert ediciones_en_conflicto.listar(sesion) == []
    finally:
        from libraedge.db.schema import init_schema

        from app.servicios import reservas_nodo

        init_schema(reservas_nodo.conexion_de_la_sesion(sesion))
        sesion.commit()
