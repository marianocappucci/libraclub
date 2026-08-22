"""El portal público: quién entra desde internet y qué se lleva.

🔴 **Es el único router del producto sin sesión de staff detrás**, así que la
mitad de estos tests son de lo que NO tiene que pasar: que un jugador vea las
reservas de otro, que el login diga quién tiene cuenta, que una reserva se
confirme sin pago, que el simulador exista en producción.

La regla del producto es **sin pago no hay reserva**, y de ahí sale todo:
el turno se retiene provisorio, y sólo el pago aprobado lo confirma.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app
from app.models.enums import AlcanceDia, EstadoReserva
from app.models.maestros import FranjaDeAtencion
from app.models.reservas import EstadoPago, PagoDeReserva, Reserva
from app.tiempo import TZ, ahora

USUARIO, CLAVE = "admin", "clave-de-prueba"
MAIL, PASS = "jugador@ejemplo.com", "una-clave-larga"


def _config(entorno: str = "test") -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"], entorno=entorno, debug=False,
        directorio_de_datos="/tmp/libraclub-test-datos", libracore_database_url=None,
    )


@pytest.fixture(autouse=True)
def _secreto(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 40)


@pytest.fixture
def api(engine, sesion, monkeypatch):
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    yield TestClient(crear_app(_config()), base_url="https://testserver")
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def abierto(sesion, sucursal):
    """El complejo abre todo el día: acá no se prueba el horario."""
    sesion.add(FranjaDeAtencion(
        sucursal_id=sucursal.id, alcance_dia=AlcanceDia.TODOS,
        abre=time(0, 0), cierra=time(0, 0)))
    sesion.commit()


def _registrar(api, mail=MAIL, nombre="Juan Jugador"):
    return api.post("/api/portal/registro", json={
        "email": mail, "password": PASS, "nombre": nombre, "telefono": "111"})


def _turno(dias=3, hora_=20):
    """Un turno futuro, en hora local del complejo."""
    d = date.today() + timedelta(days=dias)
    return datetime.combine(d, time(hora_, 0), tzinfo=TZ)


def _reservar(api, cancha, cuando=None):
    return api.post("/api/portal/reservas", json={
        "cancha_id": cancha.id,
        "comienza_at": (cuando or _turno()).isoformat()})


# ── La cuenta ────────────────────────────────────────────────────────────


def test_registrarse_crea_la_cuenta_y_el_cliente(api, sesion):
    r = _registrar(api)
    assert r.status_code == 201, r.text
    assert r.json()["email"] == MAIL
    assert r.json()["nombre"] == "Juan Jugador"
    # Y queda logueado: el registro deja la cookie puesta.
    assert api.get("/api/portal/yo").json()["email"] == MAIL


def test_el_registro_NO_dice_si_el_mail_ya_existe(api, sesion):
    """🔴 Contestar «ese mail ya está registrado» convierte el formulario en un
    verificador de quién es cliente del complejo.

    El mensaje tiene que ser el mismo que el de cualquier otro rechazo.
    """
    _registrar(api)
    otro = TestClient(crear_app(_config()), base_url="https://testserver")
    repetido = _registrar(otro)
    corto = otro.post("/api/portal/registro", json={
        "email": "nuevo@ejemplo.com", "password": "corta", "nombre": "X"})

    assert repetido.status_code == 422, repetido.text
    detalle = repetido.json()["detail"]
    assert "existe" not in str(detalle).lower()
    assert "registrad" not in str(detalle).lower()
    # Y el de contraseña corta es 422 también: los dos se ven igual desde afuera.
    assert corto.status_code == 422


def test_el_login_no_distingue_mail_inexistente_de_clave_mala(api, sesion):
    _registrar(api)
    sin_sesion = TestClient(crear_app(_config()), base_url="https://testserver")

    mala = sin_sesion.post("/api/portal/login", json={"email": MAIL, "password": "otra"})
    inexistente = sin_sesion.post(
        "/api/portal/login", json={"email": "nadie@ejemplo.com", "password": PASS})

    assert mala.status_code == inexistente.status_code == 401
    assert mala.json()["detail"] == inexistente.json()["detail"]


def test_entrar_y_salir(api, sesion):
    _registrar(api)
    assert api.post("/api/portal/logout").status_code == 204
    assert api.get("/api/portal/yo").json() is None
    assert api.post(
        "/api/portal/login", json={"email": MAIL, "password": PASS}
    ).status_code == 200
    assert api.get("/api/portal/yo").json()["email"] == MAIL


def test_el_mail_no_distingue_mayusculas(api, sesion):
    """Nadie recuerda si se registró con mayúscula.

    🔑 **Se prueba entrando CON mayúsculas**, no registrándose con ellas: el
    schema del registro ya normaliza, así que registrarse con `Juan@X.COM` y
    entrar con `juan@x.com` pasaría igual con la normalización del servicio
    sacada. El login no tiene ese validador — es el único camino que ejercita
    `_normalizar`. Verificado mutándolo.
    """
    _registrar(api, mail="juan@ejemplo.com")
    otro = TestClient(crear_app(_config()), base_url="https://testserver")
    assert otro.post(
        "/api/portal/login", json={"email": "  JUAN@Ejemplo.COM  ", "password": PASS}
    ).status_code == 200


# ── Lo que se ve sin sesión ──────────────────────────────────────────────


def test_las_canchas_se_ven_sin_registrarse(api, sucursal, cancha):
    """Hay que poder mirar antes de registrarse: si no, nadie se registra."""
    r = api.get(f"/api/portal/canchas?sucursal_id={sucursal.id}")
    assert r.status_code == 200, r.text
    assert r.json()[0]["nombre"] == cancha.nombre


def test_las_canchas_publicas_NO_traen_datos_internos(api, sucursal, cancha):
    """🔴 El modelo entero incluye `punto_venta_arca` y las notas internas."""
    fila = api.get(f"/api/portal/canchas?sucursal_id={sucursal.id}").json()[0]
    assert set(fila) == {
        "id", "nombre", "deporte", "techada", "iluminacion", "duracion_turno_min"
    }, fila


def test_la_disponibilidad_NO_dice_quien_ocupa(
    api, sesion, sucursal, cancha, cliente, tarifa_base, abierto
):
    """🔴 La grilla del mostrador trae `cliente`, `motivo` y `reserva_id`.

    Publicarla diría en internet quién juega, a qué hora y con qué frecuencia.
    """
    from app.servicios import reservas as servicio

    cuando = _turno()
    servicio.crear(sesion, cancha_id=cancha.id, cliente_id=cliente.id,
                   comienza_at=cuando, duracion_min=90)
    sesion.commit()

    libres = api.get(
        f"/api/portal/disponibilidad?cancha_id={cancha.id}&dia={cuando.date().isoformat()}"
    ).json()
    assert libres, "tiene que haber otros turnos libres"
    for t in libres:
        assert set(t) == {"comienza_at", "termina_at", "precio"}, t
    # 🔴 Y ningún turno libre se **solapa** con la reserva.
    #
    # Comparar el instante exacto no servía y el assert pasaba con los ocupados
    # publicados: la reserva de las 20:00 dura 90 minutos y la grilla arranca a
    # las 00:00, así que se dibuja sobre el casillero de las **19:30** — el
    # `comienza_at` del turno nunca es 20:00. Lo que hay que verificar es el
    # solapamiento, que es lo que significa "ocupado". Verificado mutándolo.
    termina = cuando + timedelta(minutes=90)
    for t in libres:
        inicio = datetime.fromisoformat(t["comienza_at"])
        fin = datetime.fromisoformat(t["termina_at"])
        assert not (inicio < termina and fin > cuando), (
            f"el turno {inicio:%H:%M}-{fin:%H:%M} pisa la reserva y se publicó como libre"
        )


def test_un_turno_sin_tarifa_no_se_ofrece(api, sesion, sucursal, cancha, abierto):
    """Sin precio no hay nada que cobrar, y regalarlo en cero es peor."""
    libres = api.get(f"/api/portal/disponibilidad?cancha_id={cancha.id}").json()
    assert libres == []


# ── Reservar: sin pago no hay reserva ────────────────────────────────────


def test_reservar_deja_el_turno_PROVISORIO_y_no_confirmado(
    api, sesion, cancha, tarifa_base, abierto
):
    """🔴 **La regla del producto.** Confirmar acá dejaría al complejo con
    turnos tomados por gente que nunca pagó."""
    _registrar(api)
    r = _reservar(api, cancha)
    assert r.status_code == 201, r.text

    reserva = sesion.get(Reserva, r.json()["reserva_id"])
    sesion.refresh(reserva)
    assert reserva.estado is EstadoReserva.PROVISORIA
    assert reserva.vence_at is not None, "sin vencimiento el turno queda muerto"
    # Y la respuesta se lo dice al jugador: un turno que desaparece sin aviso
    # mientras completa la tarjeta es la peor versión de esto.
    assert r.json()["vence_at"] is not None
    assert r.json()["monto"] > 0


def test_el_precio_lo_pone_el_SERVIDOR(api, sesion, cancha, tarifa_base, abierto):
    """Mandar `precio` en el cuerpo no cambia nada: si lo tomara del cliente,
    cualquiera reservaría por un peso."""
    _registrar(api)
    r = api.post("/api/portal/reservas", json={
        "cancha_id": cancha.id, "comienza_at": _turno().isoformat(), "precio": "1"})
    assert r.status_code == 201, r.text
    assert r.json()["monto"] == float(tarifa_base.precio)


def test_sin_sesion_no_se_reserva(api, cancha, tarifa_base, abierto):
    r = _reservar(api, cancha)
    assert r.status_code == 401, r.text


def test_no_se_pueden_abrir_mas_de_tres_sin_pagar(
    api, sesion, cancha, tarifa_base, abierto
):
    """🔴 Sin tope, una sola cuenta bloquea la agenda entera.

    Cada provisoria saca un turno de circulación durante la ventana de pago; en
    bucle, deja el viernes a la noche sin nada que vender sin pagar un peso.
    """
    _registrar(api)
    from app.servicios.portal import MAXIMO_SIN_PAGAR

    for i in range(MAXIMO_SIN_PAGAR):
        assert _reservar(api, cancha, _turno(dias=3 + i)).status_code == 201

    extra = _reservar(api, cancha, _turno(dias=20))
    assert extra.status_code == 429, extra.text


def test_un_turno_ya_tomado_da_409(api, sesion, cancha, tarifa_base, abierto):
    _registrar(api)
    cuando = _turno()
    assert _reservar(api, cancha, cuando).status_code == 201

    otro = TestClient(crear_app(_config()), base_url="https://testserver")
    _registrar(otro, mail="otro@ejemplo.com", nombre="Otro")
    r = _reservar(otro, cancha, cuando)
    assert r.status_code == 409, r.text
    # Y el mensaje NO repite el del backoffice, que nombra la cancha y el
    # horario del complejo.
    assert "disponible" in r.json()["detail"].lower()


# ── El pago, que es lo que confirma ──────────────────────────────────────


def test_el_pago_aprobado_CONFIRMA_la_reserva(api, sesion, cancha, tarifa_base, abierto):
    _registrar(api)
    creada = _reservar(api, cancha).json()

    r = api.post(f"/api/portal/pagos/{creada['pago_id']}/simular")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "pago": "aprobado", "reserva": "confirmada", "cambio": True, "simulado": True}

    reserva = sesion.get(Reserva, creada["reserva_id"])
    sesion.refresh(reserva)
    assert reserva.estado is EstadoReserva.CONFIRMADA
    # 🔑 Y sin vencimiento: con `vence_at` puesto, `vencer_provisorias` se la
    # llevaría en la próxima corrida y el jugador perdería el turno que pagó.
    assert reserva.vence_at is None


def test_aplicar_el_pago_dos_veces_no_cambia_nada(
    api, sesion, cancha, tarifa_base, abierto
):
    """🔑 MercadoPago reintenta las notificaciones y manda varias por el mismo
    pago. Sin el corte, el ingreso entraría dos veces a la caja."""
    _registrar(api)
    creada = _reservar(api, cancha).json()
    primera = api.post(f"/api/portal/pagos/{creada['pago_id']}/simular").json()
    segunda = api.post(f"/api/portal/pagos/{creada['pago_id']}/simular").json()

    assert primera["cambio"] is True
    assert segunda["cambio"] is False, "la segunda no tiene que hacer nada"
    assert segunda["reserva"] == "confirmada"


def test_un_pago_rechazado_NO_cancela_la_reserva(
    api, sesion, cancha, tarifa_base, abierto
):
    """Sigue provisoria con su vencimiento corriendo: el jugador puede
    reintentar con otra tarjeta dentro de la ventana."""
    _registrar(api)
    creada = _reservar(api, cancha).json()
    r = api.post(f"/api/portal/pagos/{creada['pago_id']}/simular?aprobado=false")
    assert r.json()["pago"] == "rechazado"
    assert r.json()["reserva"] == "provisoria"


def test_una_reserva_VENCIDA_no_se_confirma_aunque_llegue_el_pago(
    api, sesion, cancha, tarifa_base, abierto
):
    """🔴 Si el jugador pagó después de que la provisoria venciera, el turno
    pudo haberse vendido a otro: confirmarla pondría dos reservas encima.

    El pago queda aprobado —la plata entró y hay que devolverla— y el turno no.
    """
    from app.servicios import reservas as servicio

    _registrar(api)
    creada = _reservar(api, cancha).json()
    reserva = sesion.get(Reserva, creada["reserva_id"])
    reserva.vence_at = ahora() - timedelta(minutes=1)
    sesion.commit()
    assert servicio.vencer_provisorias(sesion) == 1
    sesion.commit()

    r = api.post(f"/api/portal/pagos/{creada['pago_id']}/simular")
    assert r.json()["pago"] == "aprobado", "el pago se registra: la plata entró"
    assert r.json()["reserva"] != "confirmada", "pero el turno NO se confirma"


# ── El simulador no existe en producción ─────────────────────────────────


def test_el_simulador_NO_se_monta_en_produccion(engine, sesion, monkeypatch, cancha):
    """🔴 Es lo único que separa dev de regalar turnos.

    Montado en la instancia de un complejo, cualquiera con la URL confirma
    reservas sin pagar. Se verifica con **control positivo**: en dev el mismo
    endpoint contesta, así que el 404 de producción no es de cualquier ruta.
    """
    monkeypatch.setenv("LIBRACLUB_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACLUB_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    try:
        for entorno, monta in (("dev", True), ("demo", True), ("prod", False)):
            cliente = TestClient(crear_app(_config(entorno)), base_url="https://testserver")
            r = cliente.post("/api/portal/pagos/999999/simular")
            # Se mide por lo que CONTESTA y no listando `app.routes`: las rutas
            # de un router incluido no aparecen ahí con `path`, y ese chequeo
            # daba "no existe" hasta en dev — un falso verde que habría dado el
            # simulador por apagado estándolo montado.
            #
            # Los dos son 404, así que lo que distingue es el mensaje: montado,
            # el handler corre y dice que ese PAGO no existe; sin montar, es la
            # RUTA la que no existe.
            detalle = str(r.json().get("detail", "")).lower()
            monta_de_verdad = "pago" in detalle
            assert monta_de_verdad is monta, f"entorno={entorno}: {r.status_code} {detalle}"
    finally:
        AuthBase.metadata.drop_all(engine)


# ── Mis reservas: sólo las mías ──────────────────────────────────────────


def test_un_jugador_NO_ve_las_reservas_de_otro(
    api, sesion, cancha, tarifa_base, abierto
):
    """🔴 La única barrera es el filtro por `cliente_id` de su cuenta."""
    _registrar(api)
    mia = _reservar(api, cancha, _turno(dias=3)).json()

    otro = TestClient(crear_app(_config()), base_url="https://testserver")
    _registrar(otro, mail="otro@ejemplo.com", nombre="Otro")
    suya = _reservar(otro, cancha, _turno(dias=4)).json()

    mias = api.get("/api/portal/reservas").json()
    ids = {r["id"] for r in mias}
    assert mia["reserva_id"] in ids
    assert suya["reserva_id"] not in ids, "está viendo la reserva de otro"


def test_un_jugador_NO_puede_cancelar_la_de_otro(
    api, sesion, cancha, tarifa_base, abierto
):
    """🔴 `POST /reservas/<id>/cancelar` con el id de otro es el agujero que un
    portal público tiene por defecto si uno se olvida del dueño."""
    _registrar(api)
    otro = TestClient(crear_app(_config()), base_url="https://testserver")
    _registrar(otro, mail="otro@ejemplo.com", nombre="Otro")
    suya = _reservar(otro, cancha, _turno(dias=4)).json()

    r = api.post(f"/api/portal/reservas/{suya['reserva_id']}/cancelar")
    assert r.status_code == 404, r.text

    sesion.expire_all()
    reserva = sesion.get(Reserva, suya["reserva_id"])
    assert reserva.estado is not EstadoReserva.CANCELADA, "se la cancelaron"


def test_cancelar_la_propia_si_se_puede(api, sesion, cancha, tarifa_base, abierto):
    """Control del test de arriba: si cancelar no funcionara nunca, aquél
    pasaría igual sin probar la comprobación de dueño."""
    _registrar(api)
    mia = _reservar(api, cancha).json()
    r = api.post(f"/api/portal/reservas/{mia['reserva_id']}/cancelar")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "cancelada"


def test_mis_reservas_trae_el_estado_del_pago(api, sesion, cancha, tarifa_base, abierto):
    _registrar(api)
    creada = _reservar(api, cancha).json()
    fila = api.get("/api/portal/reservas").json()[0]
    assert fila["pago"] == "pendiente"
    assert fila["estado"] == "provisoria"

    api.post(f"/api/portal/pagos/{creada['pago_id']}/simular")
    fila = api.get("/api/portal/reservas").json()[0]
    assert fila["pago"] == "aprobado"
    assert fila["estado"] == "confirmada"


# ── La firma del webhook ─────────────────────────────────────────────────


def test_la_firma_invalida_se_rechaza():
    """🔴 El webhook es público —lo llama MercadoPago— así que la firma es lo
    único que separa una notificación real de una inventada."""
    from app.servicios.pagos import firma_valida

    assert not firma_valida(
        cuerpo=b"{}", x_signature="ts=1,v1=deadbeef", x_request_id="r1",
        payment_id="123", secreto="el-secreto")


def test_la_firma_valida_se_acepta():
    """Control positivo: sin él, una implementación que rechace SIEMPRE pasaría
    el test de arriba y dejaría el webhook inservible."""
    import hashlib
    import hmac

    from app.servicios.pagos import firma_valida

    secreto, ts, pid, rid = "el-secreto", "1700000000", "123", "r1"
    esperado = hmac.new(
        secreto.encode(), f"id:{pid};request-id:{rid};ts:{ts}".encode(), hashlib.sha256
    ).hexdigest()

    assert firma_valida(
        cuerpo=b"{}", x_signature=f"ts={ts},v1={esperado}", x_request_id=rid,
        payment_id=pid, secreto=secreto)


def test_sin_secreto_configurado_ninguna_firma_es_valida():
    """🔴 Una instancia a medio configurar no puede aceptar cualquier cosa.

    Se firma **con la clave vacía**, que es lo que haría el HMAC si el guard no
    estuviera: con un `v1` inventado el test pasa igual sin el guard, porque el
    hash tampoco coincide. Verificado mutándolo.
    """
    import hashlib
    import hmac

    from app.servicios.pagos import firma_valida

    ts, pid, rid = "1700000000", "1", "r"
    con_clave_vacia = hmac.new(
        b"", f"id:{pid};request-id:{rid};ts:{ts}".encode(), hashlib.sha256
    ).hexdigest()

    assert not firma_valida(
        cuerpo=b"{}", x_signature=f"ts={ts},v1={con_clave_vacia}",
        x_request_id=rid, payment_id=pid, secreto="")


def test_el_webhook_sin_secreto_no_confirma_nada(api, sesion, cancha, tarifa_base, abierto):
    """Con la instancia sin configurar, una notificación no puede confirmar."""
    _registrar(api)
    creada = _reservar(api, cancha).json()

    r = api.post("/api/portal/webhook", json={"type": "payment", "data": {"id": "1"}})
    assert r.status_code == 200, "no se le devuelve error a MercadoPago"
    assert r.json()["ok"] is False

    reserva = sesion.get(Reserva, creada["reserva_id"])
    sesion.refresh(reserva)
    assert reserva.estado is EstadoReserva.PROVISORIA, "se confirmó sin pago"


def test_el_webhook_ignora_lo_que_no_es_un_pago(api):
    r = api.post("/api/portal/webhook", json={"type": "merchant_order", "data": {"id": "1"}})
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── Los pagos de reservas vencidas se marcan ─────────────────────────────


def test_los_pagos_de_reservas_vencidas_quedan_vencidos(
    api, sesion, cancha, tarifa_base, abierto
):
    """Sin esto, un pago pendiente de una reserva liberada hace un mes sigue
    figurando como «esperando pago»."""
    from app.servicios import pagos as servicio_pagos
    from app.servicios import reservas as servicio

    _registrar(api)
    creada = _reservar(api, cancha).json()
    reserva = sesion.get(Reserva, creada["reserva_id"])
    reserva.vence_at = ahora() - timedelta(minutes=1)
    sesion.commit()
    servicio.vencer_provisorias(sesion)
    sesion.commit()

    assert servicio_pagos.marcar_vencidos(sesion) == 1
    sesion.commit()
    pago = sesion.get(PagoDeReserva, creada["pago_id"])
    sesion.refresh(pago)
    assert pago.estado is EstadoPago.VENCIDO


def test_el_webhook_CONSULTA_el_pago_y_no_le_cree_al_payload(
    api, sesion, cancha, tarifa_base, abierto, monkeypatch
):
    """🔴 El webhook avisa *"pasó algo con el pago 123"*; qué pasó se consulta.

    Confiar en el cuerpo de la notificación haría que, si alguna vez se filtrara
    el secreto, un POST forjado pudiera decir «aprobado» solo. Acá el payload
    dice `approved` **y una referencia que no es la nuestra**; lo que confirma
    es lo que devuelve MercadoPago.

    Es la única forma de cubrirlo sin credenciales: se reemplaza `obtener_pago`
    por un doble. El doble **no encoda la respuesta esperada** —devuelve lo que
    devolvería MercadoPago— y el test verifica que el resultado salga de ahí y
    no del payload.
    """
    import hashlib
    import hmac

    from libracore import config_manager

    from app.routers import portal as router_portal

    _registrar(api)
    creada = _reservar(api, cancha).json()

    secreto = "secreto-de-prueba"
    config_manager.save({"mp_webhook_secret": secreto, "mp_access_token": "token"})

    consultado = {}

    async def falso_obtener_pago(payment_id, token):
        consultado["payment_id"] = payment_id
        # La referencia REAL sale de acá, no del payload.
        return {"status": "approved", "external_reference": creada["referencia"]}

    monkeypatch.setattr(router_portal.mp_api, "obtener_pago", falso_obtener_pago)

    cuerpo = json.dumps({
        "type": "payment",
        "data": {"id": "9999"},
        # 🔑 Mentiras en el payload: si el código las mirara, confirmaría una
        # reserva que no es. La referencia acá es de otra instancia.
        "status": "approved",
        "external_reference": "lc-99999-otra",
    }).encode()

    ts, rid, pid = "1700000000", "req-1", "9999"
    v1 = hmac.new(
        secreto.encode(), f"id:{pid};request-id:{rid};ts:{ts}".encode(), hashlib.sha256
    ).hexdigest()

    r = api.post(
        "/api/portal/webhook",
        content=cuerpo,
        headers={
            "content-type": "application/json",
            "x-signature": f"ts={ts},v1={v1}",
            "x-request-id": rid,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "confirmada": True}
    assert consultado["payment_id"] == "9999", "no se consultó el pago a MercadoPago"

    reserva = sesion.get(Reserva, creada["reserva_id"])
    sesion.refresh(reserva)
    assert reserva.estado is EstadoReserva.CONFIRMADA


def test_el_webhook_con_firma_INVALIDA_no_confirma(
    api, sesion, cancha, tarifa_base, abierto
):
    """Control del test de arriba: con el secreto configurado, una firma que no
    cierra tiene que rebotar antes de tocar nada."""
    from libracore import config_manager

    _registrar(api)
    creada = _reservar(api, cancha).json()
    config_manager.save({"mp_webhook_secret": "secreto", "mp_access_token": "token"})

    r = api.post(
        "/api/portal/webhook",
        content=json.dumps({"type": "payment", "data": {"id": "1"}}).encode(),
        headers={
            "content-type": "application/json",
            "x-signature": "ts=1,v1=deadbeef",
            "x-request-id": "r",
        },
    )
    assert r.status_code == 401, r.text

    reserva = sesion.get(Reserva, creada["reserva_id"])
    sesion.refresh(reserva)
    assert reserva.estado is EstadoReserva.PROVISORIA


# ── El barrido que libera los turnos ─────────────────────────────────────


def test_el_script_del_cron_vence_reservas_Y_marca_pagos(
    api, sesion, cancha, tarifa_base, abierto
):
    """🔴 Sin este barrido el portal no funciona: el turno que alguien empezó a
    reservar y abandonó queda retenido para siempre.

    Y hace **las dos** cosas. Vencer la reserva libera el turno; marcar el pago
    deja de mostrarle al jugador «esperando pago» sobre algo que ya no existe.
    Son dos tablas, y la segunda es la que se olvida.
    """
    from scripts.vencer_provisorias import main

    _registrar(api)
    creada = _reservar(api, cancha).json()
    reserva = sesion.get(Reserva, creada["reserva_id"])
    reserva.vence_at = ahora() - timedelta(minutes=1)
    sesion.commit()

    assert main() == 0

    sesion.expire_all()
    reserva = sesion.get(Reserva, creada["reserva_id"])
    pago = sesion.get(PagoDeReserva, creada["pago_id"])
    assert reserva.estado is not EstadoReserva.PROVISORIA, "el turno sigue retenido"
    assert pago.estado is EstadoPago.VENCIDO, "el pago quedó diciendo «esperando»"


def test_el_barrido_NO_toca_las_que_todavia_no_vencieron(
    api, sesion, cancha, tarifa_base, abierto
):
    """Control del test de arriba: si venciera todo, aquél pasaría igual con el
    barrido llevándose reservas vivas — que es peor que no correr."""
    from scripts.vencer_provisorias import main

    _registrar(api)
    creada = _reservar(api, cancha).json()

    assert main() == 0

    sesion.expire_all()
    reserva = sesion.get(Reserva, creada["reserva_id"])
    pago = sesion.get(PagoDeReserva, creada["pago_id"])
    assert reserva.estado is EstadoReserva.PROVISORIA
    assert pago.estado is EstadoPago.PENDIENTE


def test_el_barrido_no_toca_una_reserva_YA_PAGADA(
    api, sesion, cancha, tarifa_base, abierto
):
    """🔴 El caso que rompería lo que el jugador pagó.

    Una confirmada no tiene `vence_at` —se limpia al aprobar el pago— así que el
    barrido no la ve. Este test es lo que sostiene esa limpieza: si algún día se
    dejara de limpiar, acá se vería.
    """
    from scripts.vencer_provisorias import main

    _registrar(api)
    creada = _reservar(api, cancha).json()
    api.post(f"/api/portal/pagos/{creada['pago_id']}/simular")

    assert main() == 0

    sesion.expire_all()
    reserva = sesion.get(Reserva, creada["reserva_id"])
    assert reserva.estado is EstadoReserva.CONFIRMADA, "se llevó un turno pagado"
