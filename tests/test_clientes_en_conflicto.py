"""Los cambios de clientes por revisar: ver los dos valores y elegir cuál queda (ADR-022, tercer addendum) y, cuando
el dato de la web volvió al valor anterior y ya no choca, aplicarlos o descartarlos (cuarto addendum).

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


@pytest.fixture
def ya_no_choca(central, conflicto):
    """El mismo caso, pero alguien volvió el teléfono y el email de la web a lo que había antes (111 y a@x.com): ninguno
    choca ya, la edición sigue en revisión manual y los tres datos se aplican. Devuelve el id del cliente en la web."""
    _web(central, conflicto, telefono="111", email="a@x.com")
    assert _estado_en_inbox(central)[0] == "manual_review"
    return conflicto


#: Lo que la pantalla mostró de la web cuando ya no chocaba.
VISTOS_SIN_CHOQUE = {"telefono": "111", "email": "a@x.com", "documento": None}


def _aplicar(api_staff, **extra):
    """El `resolver` de la pantalla de una edición que ya no choca: sin elecciones, con lo que vio de la web."""
    cuerpo = {"elecciones": {}, "vistos": VISTOS_SIN_CHOQUE, **extra}
    return api_staff.post(f"{URL}/{OPERACION}/resolver", json=cuerpo)


def _descartar(api_staff, vistos=None):
    vistos = VISTOS_SIN_CHOQUE if vistos is None else vistos
    return api_staff.post(f"{URL}/{OPERACION}/descartar", json={"vistos": vistos})


def _otro_conflicto(central) -> int:
    """Ana, otro cliente de la misma PC del club, con un teléfono que choca (operaciones `club-1:3` y `club-1:4`)."""
    _subir(central, operacion_alta(alta(-2, "Ana", telefono="111"), secuencia=3))
    id_ana = central.execute("SELECT id FROM clientes WHERE nombre = 'Ana'").fetchone()[0]
    _web(central, id_ana, telefono="222")
    resultados = _subir(central, operacion_edicion(
        edicion(-2, antes={"telefono": "111"}, despues={"telefono": "333"}), secuencia=4
    ))
    assert resultados == ["rejected"]
    return id_ana


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


def test_la_que_choca_no_se_marca_como_que_ya_no_choca(api_staff, central, conflicto):
    (item,) = api_staff.get(URL).json()
    assert item["ya_no_choca"] is False and item["en_conflicto"] == 2


def test_la_que_dejo_de_chocar_sigue_en_la_lista_marcada_aparte(api_staff, central, ya_no_choca):
    """Sigue en `manual_review` pero la web volvió al valor anterior: antes no aparecía y sólo salía por la línea de
    comandos. Ahora está en la lista, marcada como que ya no choca, con los tres datos por aplicar."""
    respuesta = api_staff.get(URL)
    assert respuesta.status_code == 200, respuesta.text
    (item,) = respuesta.json()

    assert item["operacion_id"] == OPERACION and item["cliente_id"] == ya_no_choca
    assert item["ya_no_choca"] is True and item["en_conflicto"] == 0 and item["se_puede_resolver"] is True
    assert {c["campo"]: c["estado"] for c in item["campos"]} == {
        "telefono": "se_aplica", "email": "se_aplica", "documento": "se_aplica"
    }
    por_campo = {c["campo"]: c for c in item["campos"]}
    assert (por_campo["telefono"]["web"], por_campo["telefono"]["pc"]) == ("111", "333")
    assert _estado_en_inbox(central)[0] == "manual_review"


def test_la_lista_trae_las_dos_clases_y_el_conteo_las_suma(api_staff, central, ya_no_choca):
    """El aviso de Clientes y el número del menú cuentan `len(lista)`: tiene que sumar las que chocan y las que no."""
    _otro_conflicto(central)

    lista = api_staff.get(URL).json()

    assert [(e["cliente_nombre"], e["ya_no_choca"], e["en_conflicto"]) for e in lista] == [
        ("Juan Pérez", True, 0), ("Ana", False, 1),
    ]


def test_el_detalle_de_la_que_dejo_de_chocar_muestra_lo_que_se_aplica(api_staff, central, ya_no_choca):
    respuesta = api_staff.get(f"{URL}/{OPERACION}")
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == api_staff.get(URL).json()[0]
    assert respuesta.json()["ya_no_choca"] is True


def test_si_todo_ya_esta_igual_en_la_web_tambien_aparece_y_aplicarla_la_da_por_resuelta(api_staff, central, conflicto):
    _web(central, conflicto, telefono="333", email="pc@x.com", documento="30123456")
    (item,) = api_staff.get(URL).json()
    assert item["ya_no_choca"] is True and {c["estado"] for c in item["campos"]} == {"igual"}

    respuesta = _aplicar(api_staff, vistos={"telefono": "333", "email": "pc@x.com", "documento": "30123456"})

    assert respuesta.status_code == 200 and respuesta.json()["aplicados"] == []
    assert _estado_en_inbox(central)[0] == "applied"
    assert api_staff.get(URL).json() == []


def test_la_edicion_que_esperaba_su_alta_entra_sola_cuando_el_alta_se_aplica(api_staff, central):
    """Llegó antes que su alta (`SinMapeo`) y quedó en revisión; cuando el alta se aplica ya hay número definitivo y no
    choca nada: aparece como una que se puede aplicar."""
    central.execute("TRUNCATE sync_inbox, libraedge_mapeo, actividad_log RESTART IDENTITY")
    central.commit()
    assert _subir(central, operacion_edicion(edicion(-1, antes={"telefono": "1"}, despues={"telefono": "2"}))) == [
        "rejected"
    ]
    assert api_staff.get(URL).json() == []

    assert _subir(central, operacion_alta(alta(-1, "Juan Pérez", telefono="1"))) == ["accepted"]

    (item,) = api_staff.get(URL).json()
    assert item["ya_no_choca"] is True and item["cliente_nombre"] == "Juan Pérez"
    assert _aplicar(api_staff, vistos={"telefono": "1"}).status_code == 200
    cliente = central.execute("SELECT telefono FROM clientes WHERE nombre = 'Juan Pérez'").fetchone()
    assert cliente[0] == "2"


def test_las_que_la_pantalla_no_puede_mostrar_quedan_afuera(api_staff, central):
    """Sin la que se entienda no hay nada seguro que aplicar: el alta sin aplicar, un payload que no se entiende y un
    cliente que ya no existe en la web siguen por `libraedge-central revision`."""
    central.execute("TRUNCATE sync_inbox, libraedge_mapeo, actividad_log RESTART IDENTITY")
    central.commit()
    # (1) La edición llega antes que su alta: no hay número definitivo.
    assert _subir(central, operacion_edicion(edicion(-1, antes={"telefono": "1"}, despues={"telefono": "2"}))) == [
        "rejected"
    ]
    # (2) Un payload que no se entiende (un teléfono que no es texto), con su alta ya aplicada.
    assert _subir(central, operacion_alta(alta(-2, "Ana", telefono="111"), secuencia=3)) == ["accepted"]
    assert _subir(central, operacion_edicion(
        edicion(-2, antes={"telefono": "111"}, despues={"telefono": 333}), secuencia=4
    )) == ["rejected"]
    # (3) El cliente de la web ya no existe.
    assert _subir(central, operacion_alta(alta(-3, "Beto"), secuencia=5)) == ["accepted"]
    id_beto = central.execute("SELECT id FROM clientes WHERE nombre = 'Beto'").fetchone()[0]
    assert _subir(central, operacion_edicion(
        edicion(-3, antes={"telefono": None}, despues={"telefono": "5"}), secuencia=6
    )) == ["accepted"]
    central.execute("DELETE FROM clientes WHERE id = ?", (id_beto,))
    central.commit()
    assert _subir(central, operacion_edicion(
        edicion(-3, antes={"telefono": "5"}, despues={"telefono": "6"}), secuencia=7
    )) == ["rejected"]

    en_revision = central.execute("SELECT count(*) FROM sync_inbox WHERE status = 'manual_review'").fetchone()[0]
    assert en_revision == 3, "las tres siguen esperando"
    assert api_staff.get(URL).json() == []


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


# ── Aplicar una que ya no choca ──────────────────────────────────────────────


def test_aplicar_la_que_dejo_de_chocar(api_staff, central, ya_no_choca):
    respuesta = _aplicar(api_staff)
    assert respuesta.status_code == 200, respuesta.text
    assert sorted(respuesta.json()["aplicados"]) == ["documento", "email", "telefono"]

    cliente = _cliente(central, ya_no_choca)
    assert (cliente["telefono"], cliente["email"], cliente["documento"]) == ("333", "pc@x.com", "30123456")
    estado, por, resolucion = _estado_en_inbox(central)
    assert estado == "applied" and por == "encargado" and resolucion == "reintentada y aplicada"
    assert api_staff.get(URL).json() == [], "ya no está en la lista"


def test_aplicar_la_que_dejo_de_chocar_queda_en_el_log_de_actividad(api_staff, central, ya_no_choca):
    assert _aplicar(api_staff).status_code == 200
    ((usuario, accion, entidad, entidad_id, descripcion, cambios),) = _actividad(central)

    assert (usuario, accion, entidad, entidad_id) == ("encargado", "editar", "cliente", str(ya_no_choca))
    assert "Juan Pérez" in descripcion and "ya no chocaba" in descripcion
    assert json.loads(cambios) == {"telefono": ["111", "333"], "email": ["a@x.com", "pc@x.com"],
                                   "documento": [None, "30123456"]}


def test_aplicar_dos_veces_la_que_dejo_de_chocar_no_aplica_dos_veces(api_staff, central, ya_no_choca):
    assert _aplicar(api_staff).status_code == 200
    _web(central, ya_no_choca, telefono="777")

    segunda = _aplicar(api_staff)

    assert segunda.status_code == 409 and segunda.json()["detail"]["codigo"] == "ya_resuelta"
    assert _cliente(central, ya_no_choca)["telefono"] == "777"
    assert len(_actividad(central)) == 1


def test_si_volvio_a_chocar_mientras_tanto_aplicar_da_409_y_no_pisa(api_staff, central, ya_no_choca):
    """La pantalla mostró «ya no choca»; antes de guardar alguien cambió el teléfono en la web. No se aplica nada."""
    _web(central, ya_no_choca, telefono="999")

    respuesta = _aplicar(api_staff)

    assert respuesta.status_code == 409, respuesta.text
    detalle = respuesta.json()["detail"]
    assert detalle["codigo"] == "cambio_en_la_web" and "Teléfono" in detalle["mensaje"]
    cliente = _cliente(central, ya_no_choca)
    assert (cliente["telefono"], cliente["email"], cliente["documento"]) == ("999", "a@x.com", None)
    assert _estado_en_inbox(central)[0] == "manual_review" and _actividad(central) == []
    # Recargada, la pantalla ve que ahora sí choca y muestra la elección por campo.
    nuevo = api_staff.get(f"{URL}/{OPERACION}").json()
    assert nuevo["ya_no_choca"] is False
    assert {c["campo"]: c["estado"] for c in nuevo["campos"]} == {
        "telefono": "conflicto", "email": "se_aplica", "documento": "se_aplica"
    }
    sin_elegir = _aplicar(api_staff, vistos={"telefono": "999", "email": "a@x.com", "documento": None})
    assert sin_elegir.status_code == 422 and "Teléfono" in sin_elegir.json()["detail"]
    elegida = _aplicar(
        api_staff, elecciones={"telefono": "pc"}, vistos={"telefono": "999", "email": "a@x.com", "documento": None}
    )
    assert elegida.status_code == 200, elegida.text
    assert _cliente(central, ya_no_choca)["telefono"] == "333"


def test_la_que_chocaba_y_dejo_de_chocar_se_resuelve_igual_tras_recargar(api_staff, central, conflicto):
    """Al revés: la pantalla se abrió con el choque (222 / web@x.com) y la web volvió atrás. Pisar lo viejo da 409; con
    lo que muestra la pantalla recargada, se aplica."""
    _web(central, conflicto, telefono="111", email="a@x.com")

    vieja = _elegir(api_staff, central)
    assert vieja.status_code == 409 and vieja.json()["detail"]["codigo"] == "cambio_en_la_web"

    nuevo = api_staff.get(f"{URL}/{OPERACION}").json()
    assert nuevo["ya_no_choca"] is True
    assert _aplicar(api_staff).status_code == 200
    assert _cliente(central, conflicto)["telefono"] == "333"


def test_aplicar_hay_que_mandar_lo_que_vio(api_staff, central, ya_no_choca):
    assert _aplicar(api_staff, vistos={"telefono": "111"}).status_code == 422
    assert _estado_en_inbox(central)[0] == "manual_review"


# ── Descartar una que ya no choca ────────────────────────────────────────────


def test_descartar_deja_la_operacion_descartada_y_el_cliente_como_esta(api_staff, central, ya_no_choca):
    respuesta = _descartar(api_staff)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"descartada": True}

    cliente = _cliente(central, ya_no_choca)
    assert (cliente["telefono"], cliente["email"], cliente["documento"]) == ("111", "a@x.com", None)
    estado, por, resolucion = _estado_en_inbox(central)
    assert (estado, por) == ("discarded", "encargado") and resolucion.startswith("Descartada a mano desde la web")
    assert api_staff.get(URL).json() == []


def test_descartar_queda_en_el_log_de_actividad(api_staff, central, ya_no_choca):
    assert _descartar(api_staff).status_code == 200
    ((usuario, accion, entidad, entidad_id, descripcion, cambios),) = _actividad(central)
    assert (usuario, accion, entidad, entidad_id) == ("encargado", "editar", "cliente", str(ya_no_choca))
    assert "Juan Pérez" in descripcion and "descartó" in descripcion and cambios is None


def test_descartar_dos_veces_o_aplicar_una_descartada_da_409(api_staff, central, ya_no_choca):
    assert _descartar(api_staff).status_code == 200

    otra = _descartar(api_staff)
    aplicar = _aplicar(api_staff)

    assert otra.status_code == 409 and otra.json()["detail"]["codigo"] == "ya_resuelta"
    assert aplicar.status_code == 409 and aplicar.json()["detail"]["codigo"] == "ya_resuelta"
    assert _cliente(central, ya_no_choca)["telefono"] == "111", "no se aplicó nada"
    assert len(_actividad(central)) == 1


def test_una_aplicada_no_se_puede_descartar(api_staff, central, ya_no_choca):
    assert _aplicar(api_staff).status_code == 200
    respuesta = _descartar(api_staff)
    assert respuesta.status_code == 409 and respuesta.json()["detail"]["codigo"] == "ya_resuelta"
    assert _estado_en_inbox(central)[0] == "applied"


def test_descartar_si_volvio_a_chocar_da_409_y_no_descarta(api_staff, central, ya_no_choca):
    """No se tira a la basura algo que la persona no vio: si el dato volvió a chocar, primero lo ve."""
    _web(central, ya_no_choca, telefono="999")

    respuesta = _descartar(api_staff)

    assert respuesta.status_code == 409 and respuesta.json()["detail"]["codigo"] == "cambio_en_la_web"
    assert _estado_en_inbox(central)[0] == "manual_review" and _actividad(central) == []
    assert api_staff.get(f"{URL}/{OPERACION}").json()["ya_no_choca"] is False


def test_descartar_hay_que_mandar_lo_que_vio(api_staff, central, ya_no_choca):
    assert _descartar(api_staff, vistos={"telefono": "111"}).status_code == 422
    assert api_staff.post(f"{URL}/{OPERACION}/descartar", json={}).status_code == 422
    assert _estado_en_inbox(central)[0] == "manual_review"


def test_descartar_una_que_no_existe_da_404(api_staff, central, ya_no_choca):
    assert api_staff.post(f"{URL}/club-1:99/descartar", json={"vistos": {}}).status_code == 404


def test_la_pc_del_club_que_reenvia_una_descartada_recibe_el_motivo(api_staff, central, ya_no_choca):
    """El central no la vuelve a aplicar: le contesta que se descartó y por qué."""
    from app.routers.sincronizacion_offline import despachador

    assert _descartar(api_staff).status_code == 200
    reenviada = operacion_edicion(edicion(
        -1,
        antes={"telefono": "111", "email": "a@x.com", "documento": None},
        despues={"telefono": "333", "email": "pc@x.com", "documento": "30123456"},
    ))
    r = SyncReceiver(central, despachador=despachador).accept(reenviada)
    assert r.result == "rejected" and "descartada en el central" in (r.error or "")
    assert _cliente(central, ya_no_choca)["telefono"] == "111"


# ── Permisos ─────────────────────────────────────────────────────────────────


def test_hace_falta_sesion(api, central, conflicto):
    api.cookies.clear()
    assert api.get(URL).status_code in (401, 403)
    assert api.get(f"{URL}/{OPERACION}").status_code in (401, 403)
    assert api.post(f"{URL}/{OPERACION}/resolver", json={"elecciones": {}, "vistos": {}}).status_code in (401, 403)
    assert api.post(f"{URL}/{OPERACION}/descartar", json={"vistos": {}}).status_code in (401, 403)


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


def test_el_admin_tambien_puede_descartar(api, central, ya_no_choca):
    respuesta = api.post(f"{URL}/{OPERACION}/descartar", json={"vistos": VISTOS_SIN_CHOQUE})
    assert respuesta.status_code == 200, respuesta.text


def test_en_la_pc_del_club_no_se_aplica_ni_se_descarta_lo_que_ya_no_choca(
    api_staff, central, ya_no_choca, nodo_clientes
):
    assert clientes_nodo.en_un_nodo()
    assert api_staff.get(URL).json() == []

    for respuesta in (api_staff.get(f"{URL}/{OPERACION}"), _aplicar(api_staff), _descartar(api_staff)):
        assert respuesta.status_code == 409 and respuesta.json()["detail"]["codigo"] == "solo_en_el_central"
    assert _cliente(central, ya_no_choca)["telefono"] == "111", "no se aplicó nada"
    assert _estado_en_inbox(central)[0] == "manual_review" and _actividad(central) == []


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
