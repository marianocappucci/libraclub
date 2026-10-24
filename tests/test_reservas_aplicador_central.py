"""El central aplica lo que el nodo dio: `reserva.creada` y `reserva.estado` (ADR-022).

Sin choque la reserva entra con su id y queda mapeada. **Con choque gana la que ya estaba** (llegó primero al
central): la del nodo se guarda `en_conflicto`, sin ocupar la cancha. Es idempotente, porque el outbox entrega al
menos una vez, y todo lo que no se puede aplicar es un `ValueError` (revisión manual) y no un `IntegrityError`, que
el receptor leería como «duplicado» y la reserva se perdería pareciendo un reintento.
"""

# Los fixtures (`nodo`, `central`, `api_staff`) se importan de otro módulo y se piden por nombre en cada test: ruff
# lo lee como «redefinición de un import sin usar» (F811). La suite pone un `noqa` por test; acá, uno por archivo.
# ruff: noqa: E402, F811

from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("libraedge", reason="libraedge todavía no es dependencia de LibraClub (lo suma el PR 11)")

from libracommerce.erp.offline import VinculoNoSincronizado
from libraedge.mapeo import SinMapeo, anotar_mapeo, traducir_id
from libraedge.sync.despacho import Despachador

from app.models.enums import EstadoReserva
from app.models.maestros import Cliente
from app.servicios import reservas as servicio
from app.servicios import reservas_nodo
from app.servicios.reservas_nodo import (
    NOTA_JUGADA_EN_EL_NODO,
    TIPO_RESERVA_CREADA,
    TIPO_RESERVA_ESTADO,
    ReservaDelNodoError,
    ReservaDelNodoInvalida,
)
from tests.reservas_nodo_apoyo import (  # noqa: F401  (fixture)
    NODO,
    a_las,
    aplicar,
    central,
    operacion,
    payload_creada,
    payload_estado,
)
from tests.test_api import api_staff  # noqa: F401  (fixture)


def _filas(conn) -> list[tuple]:
    """`(id, estado, conflicto_con_id, estado_previo, cliente_id)` de todas las reservas del central."""
    return [
        tuple(f) for f in conn.execute(
            "SELECT id, estado, conflicto_con_id, estado_previo, cliente_id FROM reservas ORDER BY id"
        ).fetchall()
    ]


def _una_de_la_web(sesion, cancha, cliente, hora=20):
    """Una reserva que ya estaba en el central: la que tomó la web (id positivo, secuencia de la base)."""
    reserva = servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(hora), precio=Decimal("10000.00")
    )
    sesion.commit()
    return reserva


# ── Sin choque ───────────────────────────────────────────────────────────────


def test_sin_choque_la_reserva_entra_con_su_id_y_el_mapeo(sesion, central, cancha, cliente):
    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, reserva_id=-3))

    filas = _filas(central)
    assert len(filas) == 1
    id_central, estado, conflicto_con, estado_previo, cliente_id = filas[0]
    assert id_central > 0
    assert (estado, conflicto_con, estado_previo, cliente_id) == ("confirmada", None, None, cliente.id)
    assert traducir_id(central, NODO, "reservas", -3) == id_central


def test_la_reserva_conserva_lo_que_el_nodo_dijo(sesion, central, cancha, cliente):
    aplicar(
        central, TIPO_RESERVA_CREADA,
        payload_creada(cancha.id, cliente.id, reserva_id=-1, observaciones="Trae pelotas", origen="telefono"),
    )
    sesion.expire_all()
    from app.models.reservas import Reserva

    reserva = sesion.query(Reserva).one()
    assert reserva.origen.value == "telefono"
    assert reserva.observaciones == "Trae pelotas"
    assert (reserva.precio, reserva.sena) == (10000, 5000)
    assert reserva.comienza_at == a_las(20) and reserva.termina_at == a_las(21, 30)
    assert reserva.created_at.isoformat().startswith("2026-09-01T10:00:00")  # cuándo se dio en el club


def test_ocupa_la_cancha_como_cualquier_otra(sesion, central, cancha, cliente):
    """Lo que entra sin choque es una reserva del central: de ahí en más la web no puede tomar ese horario."""
    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, reserva_id=-1))
    with pytest.raises(servicio.Superpuesta):
        servicio.crear(
            sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20, 30), precio=Decimal("1")
        )


# ── Con choque: gana la primera ──────────────────────────────────────────────


def test_con_choque_gana_la_que_ya_estaba_y_la_del_nodo_queda_en_conflicto(sesion, central, cancha, cliente):
    """🔑 La decisión del humano (2026-10-22): gana la que llegó primero al central."""
    ganadora = _una_de_la_web(sesion, cancha, cliente)

    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, reserva_id=-1))

    (id_ganadora, estado_g, *_), (id_nueva, estado_n, conflicto_con, estado_previo, _) = _filas(central)
    assert (id_ganadora, estado_g) == (ganadora.id, "confirmada"), "la que estaba no se toca"
    assert estado_n == "en_conflicto"
    assert conflicto_con == ganadora.id
    assert estado_previo == "confirmada"
    assert traducir_id(central, NODO, "reservas", -1) == id_nueva, "queda mapeada: el nodo tiene que saber cuál es"


def test_la_que_pierde_conserva_el_estado_con_que_se_dio(sesion, central, cancha, cliente):
    _una_de_la_web(sesion, cancha, cliente)
    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, estado="pendiente_pago"))
    assert _filas(central)[1][1:4] == ("en_conflicto", _filas(central)[0][0], "pendiente_pago")


def test_un_choque_parcial_tambien_es_un_conflicto(sesion, central, cancha, cliente):
    _una_de_la_web(sesion, cancha, cliente, hora=20)  # 20:00 a 21:30
    aplicar(
        central, TIPO_RESERVA_CREADA,
        payload_creada(cancha.id, cliente.id, reserva_id=-1, desde=a_las(21), hasta=a_las(22, 30)),
    )
    assert _filas(central)[1][1] == "en_conflicto"


def test_un_turno_pegado_no_es_un_conflicto(sesion, central, cancha, cliente):
    _una_de_la_web(sesion, cancha, cliente, hora=20)
    aplicar(
        central, TIPO_RESERVA_CREADA,
        payload_creada(cancha.id, cliente.id, reserva_id=-1, desde=a_las(21, 30), hasta=a_las(23)),
    )
    assert _filas(central)[1][1] == "confirmada"


def test_entre_dos_nodos_gana_el_primero_que_llega(sesion, central, cancha, cliente):
    """Dos clubes (o dos PC del mismo) dieron la misma cancha sin verse: el orden en que llegan decide."""
    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, reserva_id=-1), node_id="club-1")
    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, reserva_id=-1), node_id="club-2")

    (primera, estado_1, *_), (segunda, estado_2, conflicto_con, *_) = _filas(central)
    assert (estado_1, estado_2, conflicto_con) == ("confirmada", "en_conflicto", primera)
    assert traducir_id(central, "club-1", "reservas", -1) == primera
    assert traducir_id(central, "club-2", "reservas", -1) == segunda


def test_la_reserva_en_conflicto_no_bloquea_la_cancha(sesion, central, cancha, cliente):
    """Sin bloquear la cancha: si la ganadora se cancela, el horario se puede volver a dar aunque el conflicto siga."""
    ganadora = _una_de_la_web(sesion, cancha, cliente)
    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, reserva_id=-1))
    servicio.cambiar_estado(sesion, ganadora.id, EstadoReserva.CANCELADA)
    sesion.commit()

    nueva = servicio.crear(
        sesion, cancha_id=cancha.id, cliente_id=cliente.id, comienza_at=a_las(20), precio=Decimal("1")
    )
    sesion.commit()
    assert nueva.estado is EstadoReserva.CONFIRMADA


# ── Idempotencia ─────────────────────────────────────────────────────────────


def test_entregada_dos_veces_sin_choque_queda_una_sola(sesion, central, cancha, cliente):
    payload = payload_creada(cancha.id, cliente.id, reserva_id=-1)
    aplicar(central, TIPO_RESERVA_CREADA, payload)
    antes = _filas(central)
    aplicar(central, TIPO_RESERVA_CREADA, payload)
    assert _filas(central) == antes
    assert central.execute("SELECT count(*) FROM libraedge_mapeo").fetchone()[0] == 1


def test_entregada_dos_veces_con_choque_queda_una_sola_en_conflicto(sesion, central, cancha, cliente):
    _una_de_la_web(sesion, cancha, cliente)
    payload = payload_creada(cancha.id, cliente.id, reserva_id=-1)
    aplicar(central, TIPO_RESERVA_CREADA, payload)
    antes = _filas(central)
    aplicar(central, TIPO_RESERVA_CREADA, payload)
    assert _filas(central) == antes and len(antes) == 2


def test_si_la_ganadora_se_cancela_el_reintento_no_la_resucita(sesion, central, cancha, cliente):
    """Una entrega repetida no re-evalúa el choque: la reserva ya tiene su lugar (en conflicto) y su mapeo."""
    ganadora = _una_de_la_web(sesion, cancha, cliente)
    payload = payload_creada(cancha.id, cliente.id, reserva_id=-1)
    aplicar(central, TIPO_RESERVA_CREADA, payload)
    servicio.cambiar_estado(sesion, ganadora.id, EstadoReserva.CANCELADA)
    sesion.commit()
    aplicar(central, TIPO_RESERVA_CREADA, payload)
    assert [f[1] for f in _filas(central)] == ["cancelada", "en_conflicto"]


def test_un_id_provisorio_reusado_para_otra_reserva_va_a_revision_manual(sesion, central, cancha, cliente):
    """Una PC reemplazada con el mismo `node_id` que arrancó la secuencia de cero: el -1 de ahora no es el de antes."""
    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, reserva_id=-1))
    with pytest.raises(ReservaDelNodoError, match="reusó el id provisorio"):
        aplicar(
            central, TIPO_RESERVA_CREADA,
            payload_creada(cancha.id, cliente.id, reserva_id=-1, desde=a_las(18), hasta=a_las(19, 30)),
        )
    assert len(_filas(central)) == 1


# ── El cliente ───────────────────────────────────────────────────────────────


def test_un_cliente_dado_de_alta_en_el_nodo_se_traduce_con_el_mapeo(sesion, central, cancha, cliente):
    """Si el nodo da de alta clientes del dominio con id provisorio, la reserva los trae y el central los traduce."""
    anotar_mapeo(central, NODO, "clientes", -5, cliente.id)
    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, -5, reserva_id=-1))
    assert _filas(central)[0][4] == cliente.id


def test_un_cliente_provisorio_sin_alta_aplicada_va_a_revision_manual(sesion, central, cancha, cliente):
    with pytest.raises(VinculoNoSincronizado):
        aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, -5, reserva_id=-1))
    assert _filas(central) == []


# ── Lo que no se puede aplicar: ValueError, nunca IntegrityError ─────────────


@pytest.mark.parametrize(
    ("cambio", "texto"),
    [
        ({"cancha_id": 99999}, "no existe"),
        ({"cliente_id": 99999}, "no existe en el central"),
        ({"reserva_id": 7}, "no es un id provisorio"),
        ({"reserva_id": True}, "no es un entero"),
        ({"version": 2}, "versión"),
        ({"estado": "jugada"}, "no se puede dar en un nodo"),
        ({"estado": "provisoria"}, "no se puede dar en un nodo"),
        ({"estado": "inventado"}, "desconocido"),
        ({"origen": "inventado"}, "origen"),
        ({"comienza_at": "2026-09-01T20:00:00"}, "zona horaria"),
        ({"comienza_at": "mañana"}, "ISO 8601"),
        ({"termina_at": "2026-09-01T19:00:00-03:00"}, "termina antes de empezar"),
        ({"precio": "-1"}, "importe"),
        ({"sena": "20000.00"}, "supera el precio"),
    ],
)
def test_lo_que_no_se_entiende_es_un_ValueError_y_no_escribe_nada(sesion, central, cancha, cliente, cambio, texto):
    payload = {**payload_creada(cancha.id, cliente.id), **cambio}
    with pytest.raises(ValueError, match=texto):
        aplicar(central, TIPO_RESERVA_CREADA, payload)
    central.rollback()
    assert _filas(central) == []
    assert central.execute("SELECT count(*) FROM libraedge_mapeo").fetchone()[0] == 0


def test_un_schema_desconocido_se_rechaza(sesion, central, cancha, cliente):
    with pytest.raises(ReservaDelNodoInvalida, match="schema 2"):
        reservas_nodo.aplicar_reserva_creada(
            central, operacion(TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id), schema_version=2)
        )


def test_el_tipo_equivocado_se_rechaza(sesion, central, cancha, cliente):
    with pytest.raises(ReservaDelNodoInvalida, match="se esperaba reserva.creada"):
        reservas_nodo.aplicar_reserva_creada(
            central, operacion(TIPO_RESERVA_ESTADO, payload_estado(-1, "cancelada"))
        )


# ── reserva.estado ───────────────────────────────────────────────────────────


def _creada_en_el_nodo(sesion, central, cancha, cliente, reserva_id=-1) -> int:
    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, reserva_id=reserva_id))
    return traducir_id(central, NODO, "reservas", reserva_id)


def test_el_nodo_cancela_su_reserva_y_el_central_la_cancela(sesion, central, cancha, cliente):
    id_central = _creada_en_el_nodo(sesion, central, cancha, cliente)
    aplicar(central, TIPO_RESERVA_ESTADO, payload_estado(-1, "cancelada", "No viene"), secuencia=2)
    assert _filas(central) == [(id_central, "cancelada", None, None, cliente.id)]
    assert central.execute("SELECT motivo FROM reservas").fetchone()[0] == "No viene"


def test_el_nodo_marca_jugada_su_reserva(sesion, central, cancha, cliente):
    id_central = _creada_en_el_nodo(sesion, central, cancha, cliente)
    aplicar(central, TIPO_RESERVA_ESTADO, payload_estado(-1, "jugada"), secuencia=2)
    assert _filas(central)[0][:2] == (id_central, "jugada")


def test_reserva_estado_es_idempotente(sesion, central, cancha, cliente):
    _creada_en_el_nodo(sesion, central, cancha, cliente)
    aplicar(central, TIPO_RESERVA_ESTADO, payload_estado(-1, "cancelada"), secuencia=2)
    antes = _filas(central)
    aplicar(central, TIPO_RESERVA_ESTADO, payload_estado(-1, "cancelada"), secuencia=2)
    assert _filas(central) == antes


def test_reserva_estado_sin_su_reserva_creada_es_revision_manual(sesion, central, cancha, cliente):
    """El `reserva.creada` quedó en revisión manual: lo que depende de ella no se aplica sobre nada."""
    with pytest.raises(SinMapeo):
        aplicar(central, TIPO_RESERVA_ESTADO, payload_estado(-1, "cancelada"), secuencia=2)


def test_una_transicion_invalida_va_a_revision_manual(sesion, central, cancha, cliente):
    _creada_en_el_nodo(sesion, central, cancha, cliente)
    aplicar(central, TIPO_RESERVA_ESTADO, payload_estado(-1, "cancelada"), secuencia=2)
    with pytest.raises(ReservaDelNodoError, match="no es una transición válida"):
        aplicar(central, TIPO_RESERVA_ESTADO, payload_estado(-1, "jugada"), secuencia=3)


def test_cancelar_desde_el_nodo_una_reserva_en_conflicto_la_resuelve(sesion, central, cancha, cliente):
    _una_de_la_web(sesion, cancha, cliente)
    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, reserva_id=-1))
    aplicar(central, TIPO_RESERVA_ESTADO, payload_estado(-1, "cancelada"), secuencia=2)
    assert _filas(central)[1][1:4] == ("cancelada", None, None)


def test_marcar_jugada_desde_el_nodo_una_en_conflicto_no_la_saca_del_conflicto(sesion, central, cancha, cliente):
    """Jugada ocuparía una cancha que otra reserva ya tiene: se queda `en_conflicto`, con una nota, una sola vez."""
    _una_de_la_web(sesion, cancha, cliente)
    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, reserva_id=-1))
    aplicar(central, TIPO_RESERVA_ESTADO, payload_estado(-1, "jugada"), secuencia=2)
    aplicar(central, TIPO_RESERVA_ESTADO, payload_estado(-1, "jugada"), secuencia=2)

    assert _filas(central)[1][1] == "en_conflicto"
    notas = central.execute("SELECT observaciones FROM reservas WHERE estado = 'en_conflicto'").fetchone()[0]
    assert notas.count(NOTA_JUGADA_EN_EL_NODO) == 1


def test_el_cambio_de_estado_traduce_el_id_definitivo_tambien(sesion, central, cancha, cliente):
    """Una reserva del nodo que ya bajó con su id definitivo (positivo) se cambia con ese id, sin mapeo."""
    id_central = _creada_en_el_nodo(sesion, central, cancha, cliente)
    aplicar(central, TIPO_RESERVA_ESTADO, payload_estado(id_central, "cancelada"), secuencia=2)
    assert _filas(central)[0][1] == "cancelada"


# ── El registro en el despachador ────────────────────────────────────────────


def test_registrar_en_el_despachador_deja_los_dos_tipos(sesion):
    despachador = reservas_nodo.registrar_en(Despachador())
    for tipo in (TIPO_RESERVA_CREADA, TIPO_RESERVA_ESTADO):
        assert despachador.versiones(tipo) == (1,)
    assert despachador.resolver(operacion(TIPO_RESERVA_CREADA, payload_creada(1, 1))) is not None


def test_registrar_dos_veces_falla_al_arrancar(sesion):
    """Es la regla del `Despachador`: dos productos que registren el mismo tipo se enteran al arrancar."""
    despachador = reservas_nodo.registrar_en(Despachador())
    with pytest.raises(Exception, match="reserva.creada"):
        reservas_nodo.registrar_en(despachador)


def test_el_cliente_del_dominio_no_se_confunde_con_clients_de_libracore(sesion, central, cancha, cliente):
    """La reserva apunta a `clientes` (dominio) y el mapeo se anota en la tabla `clientes`, no en `clients`."""
    assert sesion.query(Cliente).count() == 1
    anotar_mapeo(central, NODO, "clientes", -2, cliente.id)
    assert traducir_id(central, NODO, "clientes", -2) == cliente.id


def test_el_conflicto_que_arma_el_aplicador_se_lista_y_se_resuelve_por_la_api(
    api_staff, sesion, central, cancha, cliente
):
    """De punta a punta en el central: el nodo sube la reserva, choca, el mostrador la ve y la mueve."""
    ganadora = _una_de_la_web(sesion, cancha, cliente)
    aplicar(central, TIPO_RESERVA_CREADA, payload_creada(cancha.id, cliente.id, reserva_id=-1))

    (item,) = api_staff.get("/api/reservas-en-conflicto").json()
    assert item["reserva"]["conflicto_con_id"] == ganadora.id and item["ganadora"]["id"] == ganadora.id

    movida = api_staff.post(
        f"/api/reservas-en-conflicto/{item['reserva']['id']}/resolver",
        json={"accion": "mover", "comienza_at": a_las(22).isoformat()},
    )
    assert movida.status_code == 200, movida.text
    assert movida.json()["estado"] == "confirmada"
    assert api_staff.get("/api/reservas-en-conflicto").json() == []
