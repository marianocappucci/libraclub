"""La configuración de ARCA, y la base de LibraCore que la sostiene.

Todavía no se emite ningún comprobante: lo que estos tests fijan es el
**cableado** —que la base de LibraCore sea la suya y no la del dominio, que la
config persista, y que una instancia sin configurar lo diga en vez de romperse—.

🔴 La separación de bases es lo que más importa acá y lo que peor falla:
`init_core_schema()` crea `usuarios` y `auth_log`, que este producto ya tiene con
la forma de `libraauth`. Compartiendo base **nada falla en el arranque** y el
problema aparece meses después, en la primera factura.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"


def _url_core() -> str:
    """La URL de la base de LibraCore para los tests, derivada de la del dominio.

    Se deriva en vez de pedir otra variable para que corra igual en el CI y en
    cualquier máquina: es el mismo servidor, otra base.
    """
    url = os.environ["DATABASE_URL"]
    base, _, nombre = url.rpartition("/")
    return f"{base}/{nombre}_core".replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture
def base_de_libracore():
    """Crea la base de LibraCore y la deja vacía. La borra al terminar."""
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
        database_url=os.environ["DATABASE_URL"],
        entorno="test",
        debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos",
        libracore_database_url=url_core,
    )


@pytest.fixture
def api(engine, sesion, monkeypatch, base_de_libracore):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(
        crear_app(_config(base_de_libracore)), base_url="https://testserver"
    )
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200
    yield cliente
    AuthBase.metadata.drop_all(engine)


#: 🔴 Sin `certificado_path` ni `clave_path`: desde el 2026-08-30 el router es
#: `libracore.arca_router` y **el path lo pone el servidor** al recibir el
#: archivo, no el cliente en un JSON. Mientras fue un campo de texto, dar de
#: alta la facturacion exigia que alguien dejara el .crt y el .key dentro del
#: volumen del contenedor a mano.
ARCA = {
    "cuit": "30712345679", "punto_venta": 3,
    "ambiente": "homologacion",
}


def test_la_config_de_arca_se_guarda_y_se_relee(api):
    assert api.get("/config/arca").json() is None, "arranca sin configurar"

    guardado = api.put("/config/arca", json=ARCA)
    assert guardado.status_code == 200, guardado.text

    # Se relee del servidor y no se mira la respuesta del PUT: lo que se prueba
    # es que persistió, no que el endpoint devolvió lo que le mandaron.
    leido = api.get("/config/arca").json()
    assert leido["cuit"] == ARCA["cuit"]
    assert leido["punto_venta"] == ARCA["punto_venta"]
    assert leido["ambiente"] == "homologacion"


def test_la_fila_se_crea_con_el_slug_que_lee_la_facturacion(api):
    """🔴 `servicios/facturacion.py` lee la configuracion con
    `EMPRESA = "complejo"`. Con `default` --el valor al que caia el router del
    motor antes de que el producto pudiera declarar el suyo-- el PUT contesta
    200 y la pantalla dice "Guardado", pero la facturacion no lee esa fila
    NUNCA: se descubre al emitir el primer comprobante."""
    r = api.put("/config/arca", json=ARCA)
    assert r.status_code == 200, r.text
    assert r.json()["empresa"] == "complejo"


def test_el_certificado_se_sube_y_se_valida_antes_de_escribirlo(api):
    """Subir el `.csr` --el pedido-- en vez del `.crt` que ARCA devuelve es el
    error habitual, y antes se aceptaba: el router propio escribia el path que
    le mandaran sin mirar nada, y fallaba recien al emitir."""
    r = api.post(
        "/config/arca/certificado",
        files={"archivo": ("pedido.pem", b"-----BEGIN CERTIFICATE REQUEST-----", "text/plain")},
    )
    assert r.status_code == 422
    assert "certificado" in r.json()["detail"].lower()


def test_el_estado_dice_si_la_instancia_puede_facturar(api):
    """🔑 Trae el vencimiento del certificado, que es el dato que evita la falla
    silenciosa: duran dos anos y el dia que vencen la facturacion deja de andar
    sin que nadie haya tocado nada."""
    r = api.get("/config/arca/estado")
    assert r.status_code == 200
    assert r.json()["configurado"] is False


def test_el_ambiente_por_default_es_homologacion(api):
    """🔑 Una instancia recién configurada no puede emitir contra producción.

    Pasar a `produccion` tiene que ser un acto deliberado, no lo que ocurre si
    alguien deja el campo como vino.
    """
    sin_ambiente = {k: v for k, v in ARCA.items() if k != "ambiente"}
    api.put("/config/arca", json=sin_ambiente)
    assert api.get("/config/arca").json()["ambiente"] == "homologacion"


def test_las_tablas_de_libracore_NO_caen_en_la_base_del_dominio(api, engine):
    """El choque que motivó las dos bases.

    `arca_config` tiene que existir del lado de LibraCore y **no** del lado del
    dominio. El control positivo —que exista de un lado— es lo que hace que el
    negativo signifique algo: sin él, "no está en el dominio" se cumpliría
    también si el schema no se hubiera creado en ningún lado.
    """
    from sqlalchemy import text

    with engine.connect() as c:
        en_dominio = c.execute(
            text("SELECT count(*) FROM pg_tables WHERE tablename = 'arca_config'")
        ).scalar_one()
    assert en_dominio == 0, "arca_config no puede estar en la base del dominio"

    # Control positivo: del lado de LibraCore sí está, y responde.
    assert api.put("/config/arca", json=ARCA).status_code == 200


def test_una_instancia_sin_base_de_libracore_lo_DICE(engine, sesion, monkeypatch):
    """503 nombrando la variable que falta, no un 500 genérico.

    Sin esto el síntoma en la pantalla es idéntico al de cualquier otro error, y
    nadie sabría que lo que hay que hacer es agregar una variable de entorno.
    """
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(crear_app(_config(None)), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200

    r = cliente.get("/config/arca")
    assert r.status_code == 503, r.text
    assert "LIBRACLUB_LIBRACORE_DATABASE_URL" in r.text
    AuthBase.metadata.drop_all(engine)


def test_una_url_que_no_es_postgres_no_se_acepta(monkeypatch):
    """Misma regla que la base del dominio: PostgreSQL es el único motor."""
    monkeypatch.setenv("DATABASE_URL", os.environ["DATABASE_URL"])
    monkeypatch.setenv("LIBRACLUB_LIBRACORE_DATABASE_URL", "sqlite:///core.db")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Config.desde_entorno()


# ── Emisión ───────────────────────────────────────────────────────────────
#
# ⚠️ **Nada de esto llega a ARCA.** Sin certificado cargado, `libracore` numera
# localmente y la factura queda **sin CAE** — que es exactamente lo que va a
# pasar en una instancia recién configurada. Lo que se prueba acá es el circuito
# del producto: qué comprobante se elige, cómo se parten los importes, y que no
# se pueda facturar dos veces. **El CAE real queda sin verificar** hasta que haya
# un certificado de homologación.

from datetime import date  # noqa: E402
from decimal import Decimal  # noqa: E402

from app.servicios import facturacion as servicio  # noqa: E402


def test_un_monotributista_emite_C_y_no_B():
    """🔴 El caso que la lógica de la familia se equivoca.

    `_tipo_comprobante` de Gestiolibra devuelve **B** para todo lo que no sea
    Responsable Inscripto — o sea que un complejo monotributista, que es el
    default de la config y el caso más probable, emitiría el comprobante
    equivocado. No es un bug de pantalla: es fiscal.
    """
    assert servicio.tipo_de_comprobante("Monotributista") == servicio.FACTURA_C
    # Y sin condición cargada tampoco puede caer en B: el default de la config es
    # Monotributista, así que lo conservador es C.
    assert servicio.tipo_de_comprobante(None) == servicio.FACTURA_C
    assert servicio.tipo_de_comprobante("Responsable Inscripto") == servicio.FACTURA_B


def test_la_factura_C_NO_discrimina_iva():
    """🔑 El monotributista no cobra IVA: el neto ES el total.

    `_split_iva` de la familia parte siempre al 21%. Aplicado a una C,
    inventaría un IVA que nadie pagó y dejaría el neto 21% por debajo del total.
    """
    neto, iva = servicio.importes(Decimal("14000.00"), servicio.FACTURA_C)
    assert neto == Decimal("14000.00")
    assert iva == Decimal("0.00")


def test_la_factura_B_si_lo_separa():
    """Control de la de arriba: si B tampoco separara, el test anterior pasaría
    con la función devolviendo siempre `(total, 0)` y no probaría nada."""
    neto, iva = servicio.importes(Decimal("121.00"), servicio.FACTURA_B)
    assert neto == Decimal("100.00")
    assert iva == Decimal("21.00")
    assert neto + iva == Decimal("121.00"), "los importes tienen que cerrar contra el total"


def _reserva_facturable(api, cancha, cliente, tarifa_base):
    """Una reserva con precio, creada por la API."""
    r = api.post(
        "/api/reservas",
        json={"cancha_id": cancha.id, "cliente_id": cliente.id,
              "comienza_at": "2026-09-01T20:00:00-03:00", "duracion_min": 90},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_facturar_una_reserva_emite_y_la_deja_vinculada(api, cancha, cliente, tarifa_base):
    reserva = _reserva_facturable(api, cancha, cliente, tarifa_base)
    assert api.get(f"/api/reservas/{reserva['id']}/factura").json() is None

    emitida = api.post(f"/api/reservas/{reserva['id']}/facturar")
    assert emitida.status_code == 201, emitida.text
    factura = emitida.json()
    # Monotributista por default -> Factura C.
    assert factura["tipo"] == servicio.FACTURA_C
    assert factura["total"] > 0

    # Se relee por el otro endpoint: lo que se prueba es que quedó VINCULADA,
    # no que el POST devolvió algo.
    vista = api.get(f"/api/reservas/{reserva['id']}/factura").json()
    assert vista is not None
    assert vista["id"] == factura["id"]


def test_no_se_puede_facturar_dos_veces(api, cancha, cliente, tarifa_base):
    """🔑 Dos comprobantes por la misma reserva son dos veces el mismo ingreso
    ante ARCA, y no se arregla borrando: hace falta una nota de crédito."""
    reserva = _reserva_facturable(api, cancha, cliente, tarifa_base)
    assert api.post(f"/api/reservas/{reserva['id']}/facturar").status_code == 201
    segunda = api.post(f"/api/reservas/{reserva['id']}/facturar")
    assert segunda.status_code == 409, segunda.text


def test_algo_sin_precio_no_se_factura(api, cancha):
    """422 y no un total en cero: una factura de $0 con CAE es un comprobante
    fiscal que no debería existir.

    Se usa un **bloqueo**, que es el caso real sin precio: mantenimiento, lluvia
    o un torneo ocupan la cancha y no se le cobran a nadie. Una reserva común no
    sirve para este test — la API la rechaza antes, porque sin tarifa vigente no
    la deja crear.
    """
    b = api.post(
        "/api/reservas/bloqueos",
        json={"cancha_id": cancha.id,
              "comienza_at": "2026-09-02T20:00:00-03:00",
              "termina_at": "2026-09-02T21:30:00-03:00",
              "motivo": "Mantenimiento"},
    )
    assert b.status_code == 201, b.text
    assert api.post(f"/api/reservas/{b.json()['id']}/facturar").status_code == 422


def test_facturar_es_de_admin(api, cancha, cliente, tarifa_base, engine):
    """El mostrador toma reservas y cobra; qué se factura es del dueño."""
    reserva = _reserva_facturable(api, cancha, cliente, tarifa_base)
    api.post("/api/usuarios", json={
        "username": "mostrador", "name": "Mostrador", "password": "clave-mostrador",
        "role": "staff",
    })
    staff = TestClient(crear_app(_config(_url_core())), base_url="https://testserver")
    assert staff.post(
        "/auth/login", json={"username": "mostrador", "password": "clave-mostrador"}
    ).status_code == 200
    assert staff.post(f"/api/reservas/{reserva['id']}/facturar").status_code == 403
    # Control: ver la factura sí puede.
    assert staff.get(f"/api/reservas/{reserva['id']}/factura").status_code == 200


# ── El listado y el PDF ───────────────────────────────────────────────────
#
# Lo que se prueba acá es la vista de arriba: `GET /api/facturas` y el PDF. El
# detalle de un comprobante sigue siendo el diálogo de la reserva, que ya tiene
# sus tests más arriba.


def _facturar(api, cancha, cliente, comienza: str) -> dict:
    """Una reserva con precio, facturada. Devuelve el comprobante."""
    r = api.post(
        "/api/reservas",
        json={"cancha_id": cancha.id, "cliente_id": cliente.id,
              "comienza_at": comienza, "duracion_min": 90},
    )
    assert r.status_code == 201, r.text
    emitida = api.post(f"/api/reservas/{r.json()['id']}/facturar")
    assert emitida.status_code == 201, emitida.text
    return emitida.json()


def test_el_listado_trae_las_facturas_emitidas(api, cancha, cliente, tarifa_base):
    """🔑 **Dos, y no una.** Con una sola factura, un listado que devolviera
    siempre "la última" —o que ignorara la paginación— pasaría igual.

    Se emiten por la API de reservas, que es el único camino por el que nacen
    los comprobantes de este producto: sembrarlas escribiendo directo en
    `facturas` probaría el SELECT contra filas que la aplicación nunca escribió.
    """
    assert api.get("/api/facturas").json()["items"] == [], "arranca vacío"

    primera = _facturar(api, cancha, cliente, "2026-09-01T20:00:00-03:00")
    segunda = _facturar(api, cancha, cliente, "2026-09-02T20:00:00-03:00")

    pagina = api.get("/api/facturas").json()
    assert pagina["total"] == 2
    assert pagina["total_pages"] == 1
    assert pagina["page"] == 1

    numeros = {f["numero"] for f in pagina["items"]}
    assert numeros == {primera["numero"], segunda["numero"]}

    # El cliente y el importe salen del listado, no del POST: es lo que la
    # pantalla va a mostrar.
    fila = next(f for f in pagina["items"] if f["numero"] == primera["numero"])
    assert fila["cliente_razon"] == cliente.nombre
    assert fila["total"] == primera["total"]
    assert fila["tipo"] == servicio.FACTURA_C


def test_el_listado_filtra_por_fecha(api, cancha, cliente, tarifa_base):
    """El filtro corta de verdad.

    Las dos facturas llevan la fecha de HOY —`facturar_reserva` estampa
    `date.today()`, no la fecha del turno—, así que el corte se prueba contra
    mañana. El control es la consulta sin filtro: sin él, un `desde` que
    devuelve cero se cumpliría también si el listado estuviera roto.
    """
    from datetime import date, timedelta

    _facturar(api, cancha, cliente, "2026-09-01T20:00:00-03:00")
    _facturar(api, cancha, cliente, "2026-09-02T20:00:00-03:00")
    assert api.get("/api/facturas").json()["total"] == 2, "control: sin filtro están"

    hoy = date.today().isoformat()
    manana = (date.today() + timedelta(days=1)).isoformat()
    assert api.get(f"/api/facturas?desde={hoy}&hasta={hoy}").json()["total"] == 2
    assert api.get(f"/api/facturas?desde={manana}").json()["total"] == 0


def test_el_listado_busca_por_cliente(api, cancha, cliente, tarifa_base):
    """⚠️ Con el nombre **tal cual está escrito**.

    `get_facturas_filtradas` usa `LIKE`, y `libracore.db.core` no lo traduce a
    `ILIKE`: sobre PostgreSQL la búsqueda distingue mayúsculas. No se asierta lo
    contrario a propósito —un test que exigiera que `juan` no encuentre a `Juan`
    congelaría el defecto—; el arreglo es del motor y toca también a Contalibra
    y Restolibra.
    """
    _facturar(api, cancha, cliente, "2026-09-01T20:00:00-03:00")

    encontrado = api.get(f"/api/facturas?q={cliente.nombre}").json()
    assert encontrado["total"] == 1
    assert encontrado["items"][0]["cliente_razon"] == cliente.nombre

    assert api.get("/api/facturas?q=nadie-con-ese-nombre").json()["total"] == 0


def test_el_pdf_del_comprobante_se_genera(api, cancha, cliente, tarifa_base):
    """200, un PDF de verdad, y el número en el nombre del archivo."""
    factura = _facturar(api, cancha, cliente, "2026-09-01T20:00:00-03:00")

    r = api.get(f"/api/facturas/{factura['id']}/pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    # Los bytes, no el status: un 200 con un cuerpo vacío o con el `index.html`
    # de la SPA también daría 200.
    assert r.content.startswith(b"%PDF"), r.content[:40]
    assert len(r.content) > 1000, "un PDF con el comprobante adentro no pesa 200 bytes"
    assert str(factura["numero"]).zfill(8) in r.headers["content-disposition"]


def test_el_pdf_de_un_comprobante_que_no_existe_da_404(api):
    assert api.get("/api/facturas/99999/pdf").status_code == 404


def test_el_listado_es_de_admin(api, cancha, cliente, tarifa_base):
    """El mostrador ve la factura de SU turno; todo lo facturado es del dueño.

    El control es la misma consulta como admin: sin él, un 403 se cumpliría
    también si la ruta no existiera.
    """
    _facturar(api, cancha, cliente, "2026-09-01T20:00:00-03:00")
    api.post("/api/usuarios", json={
        "username": "mostrador", "name": "Mostrador", "password": "clave-mostrador",
        "role": "staff",
    })
    staff = TestClient(crear_app(_config(_url_core())), base_url="https://testserver")
    assert staff.post(
        "/auth/login", json={"username": "mostrador", "password": "clave-mostrador"}
    ).status_code == 200

    assert staff.get("/api/facturas").status_code == 403
    assert staff.get("/api/facturas/1/pdf").status_code == 403
    # Control: el admin sí, por la misma ruta.
    assert api.get("/api/facturas").status_code == 200


def test_sin_base_de_libracore_el_listado_lo_DICE(engine, sesion, monkeypatch):
    """503 nombrando la variable, igual que la config de ARCA. Un complejo que
    todavía no factura tiene que poder entrar a la pantalla y entender por qué
    está vacía."""
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cliente = TestClient(crear_app(_config(None)), base_url="https://testserver")
    assert cliente.post(
        "/auth/login", json={"username": USUARIO, "password": CLAVE}
    ).status_code == 200

    r = cliente.get("/api/facturas")
    assert r.status_code == 503, r.text
    assert "LIBRACLUB_LIBRACORE_DATABASE_URL" in r.text
    AuthBase.metadata.drop_all(engine)


def test_la_ruta_de_la_PANTALLA_no_la_intercepta_la_api(api):
    """🔴 El error que ya pasó con el log de actividad, en este mismo producto.

    El router del kit se montaba en `/logs` —que es la URL de la **pantalla**—,
    y FastAPI resuelve sus rutas antes que el catch-all de la SPA: entrar a
    `/logs` devolvía el JSON crudo del endpoint en vez del listado. Por eso este
    producto monta todo bajo `/api`.

    La pantalla de comprobantes vive en `/facturas` y la API en `/api/facturas`.
    El día que alguien mueva el prefijo "para que quede más corto", esto se pone
    en rojo antes de que la pantalla desaparezca.

    ⚠️ Se miran los caminos del **esquema OpenAPI** y no `app.routes`: en esta
    versión de FastAPI un router incluido no se aplana en la lista de rutas
    —queda como un `_IncludedRouter` sin `.path`—, así que recorrer `app.routes`
    da una lista corta de la que `/api/facturas` está ausente. Un test escrito
    así pasaría por el motivo equivocado: no porque la ruta esté bien montada,
    sino porque no encuentra ninguna.
    """
    caminos = set(api.app.openapi()["paths"])
    # Control positivo: sin él, "no hay ninguna ruta /facturas" se cumpliría
    # también si el router no estuviera montado en ningún lado.
    assert "/api/facturas" in caminos, "la API tiene que estar montada"
    assert not [
        c for c in caminos if c == "/facturas" or c.startswith("/facturas/")
    ], "la URL de la pantalla no puede ser también una ruta de la API"


# ── Los comprobantes del motor: alta manual, notas de crédito y de débito ──
#
# Los doce endpoints los arma `libracore.facturas_router`, el mismo módulo que
# consumen Contalibra y Restolibra. Lo que se prueba acá es **el cableado de
# este producto**, no el circuito fiscal —que tiene sus 38 tests en el motor—:
# que emitir a mano funcione con los usuarios en la otra base, que el PDF
# siga saliendo, y que todo quede detrás del rol de admin.

HOY = date.today().isoformat()


def _factura_manual(**extra) -> dict:
    cuerpo = {
        "tipo": 11, "punto_venta": 1, "fecha": HOY,
        "condicion_venta": "Contado", "client_name": "Marcela Gutierrez",
        "items": [{"description": "Clase particular", "qty": 1, "unit_price": 9000.0}],
    }
    cuerpo.update(extra)
    return cuerpo


def test_emitir_a_mano_funciona_con_los_usuarios_en_LA_OTRA_base(api):
    """🔴 El caso que casi rompe el cableado.

    `facturas.usuario_id` es una FK contra la tabla `usuarios` **de LibraCore**,
    y en este producto los usuarios viven en la base del dominio, con la forma de
    `libraauth`. Pasarle el id del usuario del dominio reventaría el INSERT con
    un `FOREIGN KEY constraint failed` — o, si esa tabla llegara a tener filas,
    le acreditaría la factura a otra persona, que es peor porque no falla.

    Por eso `_usuario_para_el_motor` lo manda en `None`. Este test es lo que lo
    sostiene: sin esa decisión, no emite.
    """
    r = api.post("/api/facturas", json=_factura_manual())
    assert r.status_code == 200, r.text

    factura = r.json()
    assert factura["id"], "la respuesta trae el comprobante pelado, con su id"
    assert factura["total"] == 9000.0
    assert factura["cliente_razon"] == "Marcela Gutierrez"

    # Se relee por el listado: lo que importa es que quedó guardada.
    listado = api.get("/api/facturas").json()
    assert listado["total"] == 1
    assert listado["items"][0]["id"] == factura["id"]


def test_la_nota_de_credito_anula_una_factura_del_complejo(api, cancha, cliente, tarifa_base):
    """Anular el comprobante de un turno, que es el caso real: se facturó una
    reserva y hubo que darla de baja."""
    reserva = _reserva_facturable(api, cancha, cliente, tarifa_base)
    emitida = api.post(f"/api/reservas/{reserva['id']}/facturar").json()

    r = api.post(f"/api/facturas/{emitida['id']}/nota-credito")
    assert r.status_code == 200, r.text
    nota = r.json()

    assert nota["tipo"] == 13, "una C da una Nota de Crédito C"
    assert nota["total"] == emitida["total"], "anula el importe exacto"
    assert nota["cbte_asoc_nro"] == emitida["numero"]

    # Y el detalle de la original la muestra colgando.
    detalle = api.get(f"/api/facturas/{emitida['id']}").json()
    assert len(detalle["notas_credito"]) == 1


def test_la_nota_de_debito_tambien_existe(api):
    factura = api.post("/api/facturas", json=_factura_manual()).json()
    nota = api.post(f"/api/facturas/{factura['id']}/nota-debito").json()
    assert nota["tipo"] == 12


def test_el_PDF_sigue_saliendo_por_el_endpoint_de_este_producto(api):
    """El factory no trae PDF: lo sirve este producto, y tiene que convivir con
    las rutas del motor sin pisarse."""
    factura = api.post("/api/facturas", json=_factura_manual()).json()

    r = api.get(f"/api/facturas/{factura['id']}/pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")

    # Control de que no se pisan: el detalle, que es `/{id}` a secas, sigue
    # devolviendo JSON.
    detalle = api.get(f"/api/facturas/{factura['id']}")
    assert detalle.headers["content-type"].startswith("application/json")


def test_todo_el_circuito_es_de_admin(api, engine):
    """El mostrador ve la factura de SU turno; emitir a mano y anular es del dueño."""
    api.post("/api/usuarios", json={
        "username": "mostrador2", "name": "Mostrador", "password": "clave-mostrador",
        "role": "staff",
    })
    staff = TestClient(crear_app(_config(_url_core())), base_url="https://testserver")
    assert staff.post(
        "/auth/login", json={"username": "mostrador2", "password": "clave-mostrador"}
    ).status_code == 200

    assert staff.post("/api/facturas", json=_factura_manual()).status_code == 403
    assert staff.get("/api/facturas").status_code == 403
    assert staff.post("/api/facturas/1/nota-credito").status_code == 403
    # Control: el admin sí, por las mismas rutas.
    assert api.get("/api/facturas").status_code == 200


#: Los campos que la pantalla `Facturas.tsx` lee de cada fila del listado.
#:
#: 🔑 Están escritos acá y no deducidos del código: hasta el 2026-08-27 este
#: listado lo armaba un `response_model` de este producto, y al pasarlo al motor
#: la respuesta cambió de forma —ahora son las filas crudas de `facturas`, con
#: más campos—. La pantalla siguió andando porque los que usa están todos, pero
#: eso hay que **verificarlo**, no suponerlo: el mismo cambio de forma en
#: `POST /api/facturas` rompió la navegación de Contalibra sin que ninguna de
#: sus 369 pruebas lo viera.
CAMPOS_QUE_USA_LA_PANTALLA = (
    "id", "tipo", "punto_venta", "numero", "fecha", "cliente_razon", "total", "cae",
)


def test_el_listado_trae_lo_que_la_PANTALLA_lee(api, cancha, cliente, tarifa_base):
    reserva = _reserva_facturable(api, cancha, cliente, tarifa_base)
    api.post(f"/api/reservas/{reserva['id']}/facturar")

    pagina = api.get("/api/facturas").json()
    assert set(pagina) >= {"items", "total", "total_pages", "page"}, sorted(pagina)

    fila = pagina["items"][0]
    faltan = [c for c in CAMPOS_QUE_USA_LA_PANTALLA if c not in fila]
    assert not faltan, f"la pantalla se rompe sin: {faltan}"

    # Y con los valores que la pantalla espera, no sólo las claves.
    assert fila["cliente_razon"] == cliente.nombre
    assert fila["punto_venta"] >= 1
    assert isinstance(fila["total"], (int, float))
    # `fecha` se dibuja con `fecha()` del frontend, que espera `aaaa-mm-dd`.
    assert len(str(fila["fecha"])) == 10, fila["fecha"]
