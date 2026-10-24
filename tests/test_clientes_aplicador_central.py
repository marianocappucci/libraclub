"""El central aplica lo que el nodo dio de alta: `cliente_club.alta` (ADR-022, addendum del 2026-10-24).

El aplicador asigna el id definitivo, anota el mapeo `(nodo, 'clientes', id provisorio) -> id` y **no duplica a una
persona que el central ya tiene** (por `documento`, `cuit` o `email`; nunca por el nombre). Es idempotente, porque el
outbox entrega al menos una vez, y todo lo que no se puede aplicar es un `ValueError` (revisión manual), no un
`IntegrityError` que el receptor leería como «duplicado».

Y la reserva de un cliente provisorio se materializa con el id definitivo: `reservas_nodo.aplicar_reserva_creada`
traduce el `cliente_id` negativo con el mismo mapeo, siempre que el alta se haya aplicado antes (el outbox lo
garantiza).
"""

# Los fixtures se importan de otros módulos y se piden por nombre en cada test: ruff lo lee como «redefinición de un
# import sin usar» (F811). La suite pone un `noqa` por test; acá, uno por archivo.
# ruff: noqa: F811

from __future__ import annotations

import pytest
from libracommerce.erp.offline import VinculoNoSincronizado
from libraedge.mapeo import anotar_mapeo, traducir_id
from libraedge.sync.despacho import Despachador

from app.models.maestros import Cliente
from app.servicios import clientes_nodo, reservas_nodo
from app.servicios.clientes_nodo import TIPO_CLIENTE_ALTA, AltaDeClienteInvalida, ClienteDelNodoError
from tests.clientes_nodo_apoyo import NODO, alta, operacion_alta
from tests.reservas_nodo_apoyo import (  # noqa: F401  (fixture)
    a_las,
    central,
    operacion,
    payload_creada,
)
from tests.reservas_nodo_apoyo import aplicar as aplicar_reserva
from tests.test_api import api_staff  # noqa: F401  (fixtures)
from tests.test_clientes_en_el_nodo import nodo_con_outbox  # noqa: F401  (fixture)


def aplicar(conn, payload: dict, **kw) -> None:
    """Aplica un `cliente_club.alta` como el receptor: en la transacción de `conn`, que se confirma al final."""
    clientes_nodo.aplicar_cliente_alta(conn, operacion_alta(payload, **kw))
    conn.commit()


def _clientes(conn) -> list[tuple]:
    """`(id, nombre, email, documento, cuit, activo, acepta_avisos)` de todos los clientes del central."""
    return [
        tuple(f) for f in conn.execute(
            "SELECT id, nombre, email, documento, cuit, activo, acepta_avisos FROM clientes ORDER BY id"
        ).fetchall()
    ]


def _del_central(conn, nombre: str, *, email=None, documento=None, cuit=None, activo=True) -> int:
    """Un cliente que ya estaba en el central (lo cargó la web, el portal u otro mostrador)."""
    id_ = conn.execute(
        "INSERT INTO clientes (nombre, email, documento, cuit, activo, acepta_avisos) VALUES (?, ?, ?, ?, ?, TRUE)",
        (nombre, email, documento, cuit, activo),
    ).lastrowid
    conn.commit()
    return id_


# ── El alta nueva ────────────────────────────────────────────────────────────


def test_el_alta_crea_al_cliente_con_su_id_y_el_mapeo(sesion, central):
    aplicar(central, alta(-3, "Juan Pérez", telefono="11 5555 1234", email="juan@example.com", documento="30123456"))

    ((id_central, nombre, email, documento, cuit, activo, avisos),) = _clientes(central)
    assert id_central > 0, "el id lo asigna el central, no el nodo"
    assert (nombre, email, documento, cuit, activo, avisos) == (
        "Juan Pérez", "juan@example.com", "30123456", None, True, True
    )
    assert traducir_id(central, NODO, "clientes", -3) == id_central


def test_el_alta_conserva_lo_que_el_nodo_dijo(sesion, central):
    aplicar(central, alta(-1, "Ana", acepta_avisos=False, observaciones="Pidió que no le escriban"))

    fila = central.execute("SELECT acepta_avisos, observaciones, telefono, created_at FROM clientes").fetchone()
    assert fila[0] is False and fila[1] == "Pidió que no le escriban"
    assert str(fila[3].year) == "2026", "la fecha en que se dio el alta, no la de la llegada"


def test_aplicarla_dos_veces_no_duplica_nada(sesion, central):
    """El outbox entrega al menos una vez."""
    for _ in range(3):
        aplicar(central, alta(-1, "Juan Pérez", documento="30123456"))
    assert len(_clientes(central)) == 1
    n = central.execute("SELECT count(*) FROM libraedge_mapeo WHERE tabla = 'clientes'").fetchone()[0]
    assert n == 1


def test_dos_altas_distintas_son_dos_clientes(sesion, central):
    aplicar(central, alta(-1, "Uno"))
    aplicar(central, alta(-2, "Dos"))
    assert [c[1] for c in _clientes(central)] == ["Uno", "Dos"]
    assert traducir_id(central, NODO, "clientes", -1) != traducir_id(central, NODO, "clientes", -2)


def test_el_mismo_id_provisorio_de_otro_nodo_es_otro_cliente(sesion, central):
    """Cada nodo tiene su secuencia de ids provisorios: el -1 de uno no es el -1 de otro."""
    aplicar(central, alta(-1, "Del club 1"), node_id="club-1")
    aplicar(central, alta(-1, "Del club 2"), node_id="club-2")
    assert [c[1] for c in _clientes(central)] == ["Del club 1", "Del club 2"]


# ── No duplicar a quien el central ya tiene ──────────────────────────────────


def test_por_documento_usa_al_que_ya_estaba_y_no_toca_sus_datos(sesion, central):
    existente = _del_central(central, "Juan Pérez", documento="30123456", email="juan@viejo.com")

    aplicar(central, alta(-1, "Juancho", documento="30.123.456", email="otro@example.com"))

    assert _clientes(central) == [(existente, "Juan Pérez", "juan@viejo.com", "30123456", None, True, True)]
    assert traducir_id(central, NODO, "clientes", -1) == existente


def test_por_cuit_usa_al_que_ya_estaba(sesion, central):
    existente = _del_central(central, "Padel SA", cuit="30-71234567-8")
    aplicar(central, alta(-1, "Padel S.A.", cuit="30712345678"))
    assert len(_clientes(central)) == 1
    assert traducir_id(central, NODO, "clientes", -1) == existente


def test_por_email_usa_al_que_ya_estaba_sin_mirar_mayusculas(sesion, central):
    """Es lo que ata a una persona con su cuenta del portal."""
    existente = _del_central(central, "Ana López", email="ana@example.com")
    aplicar(central, alta(-1, "Ana", email="  Ana@Example.com "))
    assert len(_clientes(central)) == 1
    assert traducir_id(central, NODO, "clientes", -1) == existente


def test_el_documento_manda_sobre_el_email(sesion, central):
    """Si el documento y el email apuntan a clientes distintos, gana el documento (la clave más fuerte)."""
    por_email = _del_central(central, "Por email", email="juan@example.com")
    por_documento = _del_central(central, "Por documento", documento="30123456")
    assert por_email < por_documento

    aplicar(central, alta(-1, "Juan", documento="30123456", email="juan@example.com"))

    assert traducir_id(central, NODO, "clientes", -1) == por_documento


def test_el_mismo_email_con_otro_documento_no_es_la_misma_persona(sesion, central):
    """Una familia comparte el email: si los dos traen documento y es distinto, son dos personas."""
    padre = _del_central(central, "Padre", email="familia@example.com", documento="20111222")

    aplicar(central, alta(-1, "Hijo", email="familia@example.com", documento="45999888"))

    assert len(_clientes(central)) == 2
    assert traducir_id(central, NODO, "clientes", -1) != padre


def test_el_mismo_email_sin_documento_de_un_lado_si_es_la_misma_persona(sesion, central):
    """El choque necesita los dos documentos: si uno no lo tiene, el email decide."""
    existente = _del_central(central, "Padre", email="familia@example.com", documento="20111222")
    aplicar(central, alta(-1, "Papá", email="familia@example.com"))
    assert traducir_id(central, NODO, "clientes", -1) == existente


def test_no_se_deduplica_por_el_nombre(sesion, central):
    """Dos «Juan Pérez» sin documento ni email son dos clientes: fusionar por el nombre es peor que duplicar."""
    existente = _del_central(central, "Juan Pérez")
    aplicar(central, alta(-1, "Juan Pérez", telefono="11 5555 1234"))
    assert len(_clientes(central)) == 2
    assert traducir_id(central, NODO, "clientes", -1) != existente


def test_un_cliente_dado_de_baja_no_se_reutiliza(sesion, central):
    baja = _del_central(central, "Juan Pérez", documento="30123456", activo=False)
    aplicar(central, alta(-1, "Juan Pérez", documento="30123456"))
    assert len(_clientes(central)) == 2
    assert traducir_id(central, NODO, "clientes", -1) != baja


def test_un_cliente_provisorio_no_cuenta_como_uno_del_central(sesion, central):
    """En la base de un nodo conviven los provisorios (negativos) y los del espejo: el aplicador sólo corre en el
    central, pero si encontrara un provisorio no lo mapearía a sí mismo."""
    central.execute(
        "INSERT INTO clientes (id, nombre, documento, activo, acepta_avisos) "
        "VALUES (-9, 'Provisorio', '30123456', TRUE, TRUE)"
    )
    central.commit()
    aplicar(central, alta(-1, "Juan Pérez", documento="30123456"))
    assert traducir_id(central, NODO, "clientes", -1) > 0


def test_dos_altas_del_nodo_de_la_misma_persona_son_un_solo_cliente(sesion, central):
    """Se dio de alta dos veces en el mismo corte de conexión (dos ids provisorios): una sola persona en el central."""
    aplicar(central, alta(-1, "Juan Pérez", documento="30123456"))
    aplicar(central, alta(-2, "Juan P.", documento="30.123.456"), secuencia=2)
    assert len(_clientes(central)) == 1
    assert traducir_id(central, NODO, "clientes", -1) == traducir_id(central, NODO, "clientes", -2)


def test_dedup_del_reintento_es_idempotente_y_no_mueve_el_mapeo(sesion, central):
    existente = _del_central(central, "Juan Pérez", documento="30123456")
    for _ in range(2):
        aplicar(central, alta(-1, "Juancho", documento="30123456"))
    assert len(_clientes(central)) == 1
    assert traducir_id(central, NODO, "clientes", -1) == existente


# ── Lo que no se puede aplicar es revisión manual ────────────────────────────


def test_un_id_provisorio_reusado_por_otra_persona_es_revision_manual(sesion, central):
    """Una PC reemplazada con el mismo `node_id` que arrancó la secuencia de cero: las reservas al -1 irían a otra
    persona. No se pisa nada."""
    aplicar(central, alta(-1, "Juan Pérez", documento="30123456"))

    with pytest.raises(ClienteDelNodoError, match="reusó el id provisorio"):
        aplicar(central, alta(-1, "María Gómez", documento="27888999"), secuencia=2)

    central.rollback()
    assert [c[1] for c in _clientes(central)] == ["Juan Pérez"]


def test_el_mismo_id_provisorio_con_los_mismos_datos_pero_otro_nombre_es_la_misma_persona(sesion, central):
    aplicar(central, alta(-1, "Juan Pérez", documento="30123456"))
    aplicar(central, alta(-1, "Juan Perez", documento="30.123.456"), secuencia=2)
    assert len(_clientes(central)) == 1


def test_un_alta_mapeada_a_un_cliente_que_ya_no_existe_es_revision_manual(sesion, central):
    anotar_mapeo(central, NODO, "clientes", -1, 987654)
    central.commit()
    with pytest.raises(ClienteDelNodoError, match="ya no existe"):
        aplicar(central, alta(-1, "Juan"))


@pytest.mark.parametrize(
    ("cambio", "fragmento"),
    [
        ({"cliente_id": 5}, "no es un id provisorio"),
        ({"cliente_id": 0}, "no es un id provisorio"),
        ({"cliente_id": True}, "no es un id provisorio"),
        ({"cliente_id": "-1"}, "no es un id provisorio"),
        ({"nombre": ""}, "no trae nombre"),
        ({"nombre": "   "}, "no trae nombre"),
        ({"nombre": None}, "no trae nombre"),
        ({"nombre": 5}, "no es un texto"),
        ({"nombre": "x" * 121}, "pasa de 120"),
        ({"documento": "9" * 21}, "pasa de 20"),
        ({"cuit": "9" * 14}, "pasa de 13"),
        ({"activo": "si"}, "no es un booleano"),
        ({"acepta_avisos": None}, "no es un booleano"),
        ({"observaciones": 7}, "no es un texto"),
        ({"creada_at": "ayer"}, "no es una fecha"),
        ({"creada_at": "2026-09-01T10:00:00"}, "no trae zona"),
        ({"version": 2}, "desconocida"),
    ],
)
def test_un_payload_que_no_se_entiende_es_un_value_error_y_no_escribe_nada(sesion, central, cambio, fragmento):
    with pytest.raises(AltaDeClienteInvalida, match=fragmento):
        aplicar(central, {**alta(-1), **cambio})
    central.rollback()
    assert _clientes(central) == []
    assert issubclass(AltaDeClienteInvalida, ValueError)


def test_un_schema_o_un_tipo_desconocido_se_rechaza(sesion, central):
    with pytest.raises(AltaDeClienteInvalida, match="schema 2"):
        aplicar(central, alta(-1), schema_version=2)
    with pytest.raises(AltaDeClienteInvalida, match="se esperaba"):
        aplicar(central, alta(-1), tipo="cliente.alta")
    assert _clientes(central) == []


# ── La reserva de un cliente provisorio se materializa con el id definitivo ──


def test_la_reserva_de_un_cliente_provisorio_se_materializa_con_el_id_definitivo(sesion, central, cancha):
    aplicar(central, alta(-5, "Juan Pérez", documento="30123456"))
    cliente_central = traducir_id(central, NODO, "clientes", -5)

    aplicar_reserva(central, reservas_nodo.TIPO_RESERVA_CREADA, payload_creada(cancha.id, -5, reserva_id=-7))

    fila = central.execute("SELECT id, cliente_id, estado FROM reservas").fetchone()
    assert fila[0] > 0 and fila[1] == cliente_central > 0 and fila[2] == "confirmada"
    assert traducir_id(central, NODO, "reservas", -7) == fila[0]


def test_la_reserva_de_un_cliente_que_ya_existia_queda_a_nombre_del_existente(sesion, central, cancha):
    """Con la deduplicación, la reserva que el nodo tomó a «Juancho» queda en la ficha de «Juan Pérez»."""
    existente = _del_central(central, "Juan Pérez", documento="30123456")
    aplicar(central, alta(-5, "Juancho", documento="30123456"))

    aplicar_reserva(central, reservas_nodo.TIPO_RESERVA_CREADA, payload_creada(cancha.id, -5, reserva_id=-7))

    assert central.execute("SELECT cliente_id FROM reservas").fetchone()[0] == existente
    assert len(_clientes(central)) == 1


def test_una_reserva_antes_que_el_alta_se_rechaza_y_entra_al_reintentar_en_orden(sesion, central, cancha):
    """Sin el alta aplicada la reserva no queda a nombre de nadie: `VinculoNoSincronizado` (revisión manual). Resuelta
    el alta, el reintento la aplica."""
    with pytest.raises(VinculoNoSincronizado):
        aplicar_reserva(central, reservas_nodo.TIPO_RESERVA_CREADA, payload_creada(cancha.id, -5, reserva_id=-7))
    central.rollback()
    assert central.execute("SELECT count(*) FROM reservas").fetchone()[0] == 0

    aplicar(central, alta(-5, "Juan Pérez"))
    aplicar_reserva(central, reservas_nodo.TIPO_RESERVA_CREADA, payload_creada(cancha.id, -5, reserva_id=-7))

    assert central.execute("SELECT count(*) FROM reservas").fetchone()[0] == 1


def test_una_reserva_de_un_cliente_del_central_no_necesita_alta(sesion, central, cancha, cliente):
    """Un `cliente_id` positivo ya es del central (el nodo lo vio por el espejo): pasa igual."""
    aplicar_reserva(central, reservas_nodo.TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, reserva_id=-7))
    assert central.execute("SELECT cliente_id FROM reservas").fetchone()[0] == cliente.id


# ── Del nodo al central, de punta a punta ────────────────────────────────────


def test_del_nodo_al_central_el_alta_y_la_reserva_suben_en_orden_y_quedan_enlazadas(
    api_staff, sesion, central, cancha, tarifa_base, nodo_con_outbox
):
    """Lo que el mostrador hace sin conexión —dar de alta a quien llama y tomarle el turno— y lo que el central recibe,
    en el orden del outbox: el cliente con su id definitivo y la reserva atada a él. La base de la suite hace de las
    dos puntas (el nodo tiene los negativos; el central, los positivos)."""
    from libraedge.db.repository import NodeRepository

    cliente = api_staff.post("/api/clientes", json={"nombre": "Juan Pérez", "documento": "30123456"}).json()
    reserva = api_staff.post(
        "/api/reservas",
        json={"cancha_id": cancha.id, "cliente_id": cliente["id"], "comienza_at": a_las(20).isoformat()},
    ).json()
    assert cliente["id"] < 0 and reserva["id"] < 0 and reserva["cliente_id"] == cliente["id"]

    operaciones = NodeRepository(reservas_nodo.conexion_de_la_sesion(sesion)).list_pending_operations(10)
    assert [o.operation_type for o in operaciones] == ["cliente_club.alta", "reserva.creada"]
    sesion.commit()

    despachador = reservas_nodo.registrar_en(clientes_nodo.registrar_en(Despachador()))
    for o in operaciones:
        despachador(central, o)
    central.commit()

    id_cliente = traducir_id(central, "club-1", "clientes", cliente["id"])
    id_reserva = traducir_id(central, "club-1", "reservas", reserva["id"])
    assert id_cliente > 0 and id_reserva > 0
    assert central.execute("SELECT cliente_id FROM reservas WHERE id = ?", (id_reserva,)).fetchone()[0] == id_cliente
    assert central.execute("SELECT nombre FROM clientes WHERE id = ?", (id_cliente,)).fetchone()[0] == "Juan Pérez"


# ── El despachador ───────────────────────────────────────────────────────────


def test_registrar_en_suma_el_tipo_sin_chocar_con_el_de_libracommerce():
    """`cliente_club.alta` y no `cliente.alta`: ese ya lo registra `libracommerce.erp.offline.registrar_en`."""
    from libracommerce.erp.offline import registrar_en as registrar_libracommerce

    despachador = Despachador()
    registrar_libracommerce(despachador)
    assert "cliente.alta" in despachador.tipos(), "el control: el tipo de los `clients` ya está registrado"

    clientes_nodo.registrar_en(despachador)
    reservas_nodo.registrar_en(despachador)

    assert {TIPO_CLIENTE_ALTA, "cliente.alta", "reserva.creada", "reserva.estado"} <= set(despachador.tipos())
    assert despachador.versiones(TIPO_CLIENTE_ALTA) == (1,)
    with pytest.raises(ValueError, match="ya hay un manejador"):
        clientes_nodo.registrar_en(despachador)


def test_el_aplicador_no_toca_los_clientes_de_libracore(sesion, central):
    """Los `clients` de LibraCore tienen su propia alta y su propio mapeo (`clients`): acá no se mezclan."""
    aplicar(central, alta(-1, "Juan"))
    tablas = {f[0] for f in central.execute("SELECT DISTINCT tabla FROM libraedge_mapeo").fetchall()}
    assert tablas == {"clientes"}
    assert central.execute("SELECT count(*) FROM clients").fetchone()[0] == 0
    assert Cliente.__tablename__ == "clientes"
    assert operacion  # noqa: B015  (el helper de reservas sigue importable junto a éste)
