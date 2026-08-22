"""El portal público: quién entra desde internet y qué puede hacer.

🔴 **Todo lo de acá está expuesto a internet sin sesión de staff.** Esa es la
diferencia con el resto del producto y la que ordena las decisiones: un endpoint
que devuelve de más acá es una filtración, no un detalle de diseño.

Reglas que valen para todo el módulo:

- El jugador ve **su** información y la disponibilidad. Nunca el nombre de quien
  ocupa otro turno, ni el teléfono de nadie, ni precios de otras sucursales.
- El registro **no dice si un email ya existe**: contestar "ese mail ya está
  registrado" convierte al formulario en un verificador de quién es cliente del
  complejo.
- El login **no distingue** usuario inexistente de contraseña equivocada, por lo
  mismo.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from libraauth.hashing import hash_password, verify_password
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import EstadoReserva, OrigenReserva
from app.models.maestros import Cancha, Cliente, CuentaDeJugador
from app.models.reservas import EstadoPago, PagoDeReserva, Reserva
from app.servicios import reservas as servicio_reservas
from app.servicios import tarifario
from app.tiempo import ahora

#: Cuánto se le retiene el turno al jugador para que complete el pago.
#:
#: 🔑 Es el `VENCIMIENTO_PROVISORIA` del servicio de reservas y no un valor
#: propio: si fueran dos, la reserva podría vencer antes o después de lo que el
#: portal le prometió al jugador.
VENTANA_DE_PAGO = servicio_reservas.VENCIMIENTO_PROVISORIA


class CredencialesInvalidas(ValueError):
    """Usuario o contraseña. **Sin distinguir cuál**, a propósito."""


class RegistroInvalido(ValueError):
    pass


class TurnoNoDisponible(RuntimeError):
    pass


def _normalizar(email: str) -> str:
    return email.strip().lower()


def registrar(
    sesion: Session, *, email: str, password: str, nombre: str, telefono: str = ""
) -> CuentaDeJugador:
    """Crea la cuenta del jugador y su `Cliente`.

    El `Cliente` se crea siempre: es el dato con el que después se factura y se
    lleva la cuenta corriente, y sin él la reserva no tendría a quién colgarse.

    🔴 **Si el email ya existe, esto NO lo dice.** Levanta `RegistroInvalido` con
    un mensaje genérico, igual que si la contraseña fuera corta. Contestar "ese
    mail ya está registrado" convertiría el formulario en un verificador de
    quién es cliente del complejo, que es información de sus clientes y no de
    quien pregunta.
    """
    email = _normalizar(email)
    if len(password) < 8:
        raise RegistroInvalido("La contraseña tiene que tener al menos 8 caracteres.")
    if not nombre.strip():
        raise RegistroInvalido("Falta el nombre.")

    cliente = Cliente(nombre=nombre.strip(), email=email, telefono=telefono or None)
    sesion.add(cliente)
    sesion.flush()

    cuenta = CuentaDeJugador(
        cliente_id=cliente.id,
        email=email,
        password_hash=hash_password(password),
        telefono=telefono or None,
    )
    sesion.add(cuenta)
    try:
        sesion.flush()
    except IntegrityError as exc:
        sesion.rollback()
        raise RegistroInvalido(
            "No se pudo crear la cuenta. Revisá los datos o probá entrar."
        ) from exc
    return cuenta


def autenticar(sesion: Session, *, email: str, password: str) -> CuentaDeJugador:
    """La cuenta, o `CredencialesInvalidas`.

    🔑 **Se hashea igual aunque la cuenta no exista.** Sin eso, un email
    inexistente contesta mucho más rápido que uno con contraseña equivocada, y
    ese tiempo dice quién tiene cuenta. Son 260.000 iteraciones de PBKDF2: la
    diferencia es medible desde afuera.
    """
    cuenta = sesion.scalars(
        select(CuentaDeJugador).where(CuentaDeJugador.email == _normalizar(email))
    ).first()
    hash_a_comparar = cuenta.password_hash if cuenta else _HASH_FALSO
    valida = verify_password(hash_a_comparar, password)
    if cuenta is None or not valida or not cuenta.activa:
        raise CredencialesInvalidas("El correo o la contraseña no son correctos.")
    return cuenta


#: Un hash real contra el que comparar cuando la cuenta no existe, para que el
#: camino de "no existe" cueste lo mismo que el de "contraseña mala".
_HASH_FALSO = hash_password("una-contraseña-que-nadie-usa")


# ── Lo que el portal muestra ─────────────────────────────────────────────


def canchas_publicas(sesion: Session, sucursal_id: int) -> list[Cancha]:
    return list(
        sesion.scalars(
            select(Cancha)
            .where(Cancha.sucursal_id == sucursal_id, Cancha.activa.is_(True))
            .order_by(Cancha.orden, Cancha.id)
        )
    )


def turnos_libres(sesion: Session, cancha: Cancha, dia) -> list[dict]:
    """Los turnos que el jugador puede reservar, **y sólo eso**.

    🔴 Se arma desde `disponibilidad.grilla_del_dia` pero se devuelve otra cosa:
    la grilla del mostrador trae `cliente`, `motivo` y `reserva_id` de los turnos
    ocupados. Devolverla tal cual publicaría en internet quién juega a qué hora
    y con qué frecuencia.
    """
    from app.servicios import disponibilidad

    # ⚠️ **`t.libre` y `t.precio is not None` se cubren mutuamente hoy**, y las
    # dos quedan igual. Mutar `t.libre` sola no rompe ningún test: la grilla no
    # le resuelve precio a los turnos ocupados, así que el segundo filtro los
    # saca lo mismo. Verificado — sacando **las dos** el test cae.
    #
    # No se simplifica a una: son dos afirmaciones distintas —"no está vendido"
    # y "tiene precio"— y el día que la grilla informe el precio de un turno
    # ocupado, la que quedara sola dejaría de proteger. Es el caso de una
    # guarda rescatada por otra rama: el test no puede distinguirlas, y por eso
    # queda escrito acá.
    return [
        {
            "comienza_at": t.comienza_at,
            "termina_at": t.termina_at,
            "precio": t.precio,
        }
        for t in disponibilidad.grilla_del_dia(sesion, cancha, dia)
        if t.libre and t.precio is not None and t.comienza_at > ahora()
    ]


def reservar(
    sesion: Session, *, cuenta: CuentaDeJugador, cancha_id: int, comienza_at: datetime
) -> tuple[Reserva, Decimal]:
    """Retiene el turno **provisorio** y devuelve la reserva y lo que hay que pagar.

    🔑 **No confirma nada.** El turno queda tomado durante `VENTANA_DE_PAGO` y se
    libera solo si el pago no llega — es la regla del portal: sin pago no hay
    reserva. Confirmar acá dejaría al complejo con turnos tomados por gente que
    nunca pagó.

    El precio **lo resuelve el servidor**, no viene del cliente: es lo que
    impide que alguien mande `precio: 1` en el cuerpo del pedido.
    """
    cancha = sesion.get(Cancha, cancha_id)
    if cancha is None or not cancha.activa:
        raise TurnoNoDisponible("Esa cancha no está disponible.")

    try:
        precio, _ = tarifario.precio_y_sena(sesion, cancha, comienza_at)
    except tarifario.SinTarifa as exc:
        # Un turno sin tarifa no se vende por internet: no hay precio que
        # cobrar, y regalarlo en cero es peor que no ofrecerlo.
        raise TurnoNoDisponible("Ese horario no está disponible.") from exc

    try:
        reserva = servicio_reservas.crear(
            sesion,
            cancha_id=cancha_id,
            cliente_id=cuenta.cliente_id,
            comienza_at=comienza_at,
            estado=EstadoReserva.PROVISORIA,
            origen=OrigenReserva.PORTAL,
        )
    except (servicio_reservas.Superpuesta, servicio_reservas.FueraDelHorario) as exc:
        # 🔑 El mensaje del portal **no repite el del backoffice**: aquél nombra
        # la cancha y el horario del complejo, que acá es información de más.
        # Y "ya está ocupado" es lo único accionable para el jugador.
        raise TurnoNoDisponible("Ese turno ya no está disponible.") from exc
    return reserva, precio


def mis_reservas(sesion: Session, cuenta: CuentaDeJugador, *, limite: int = 50) -> list[dict]:
    """Las reservas del jugador, con el estado de su pago.

    Filtra por `cliente_id` de **su** cuenta: es la única barrera entre un
    jugador y las reservas de otro.
    """
    filas = sesion.execute(
        select(Reserva, PagoDeReserva, Cancha.nombre)
        .join(Cancha, Cancha.id == Reserva.cancha_id)
        .join(PagoDeReserva, PagoDeReserva.reserva_id == Reserva.id, isouter=True)
        .where(Reserva.cliente_id == cuenta.cliente_id)
        .order_by(Reserva.comienza_at.desc())
        .limit(limite)
    ).all()
    return [
        {
            "id": r.id,
            "cancha": nombre,
            "comienza_at": r.comienza_at,
            "termina_at": r.termina_at,
            "estado": r.estado.value,
            "precio": float(r.precio) if r.precio is not None else None,
            "pago": p.estado.value if p else None,
            "vence_at": r.vence_at,
        }
        for r, p, nombre in filas
    ]


def cancelar(sesion: Session, cuenta: CuentaDeJugador, reserva_id: int) -> Reserva:
    """El jugador cancela **su** reserva.

    🔴 La comprobación de dueño va primero y por `cliente_id`: sin ella,
    `POST /portal/reservas/<cualquier id>/cancelar` cancelaría la de otro. Es la
    clase de agujero que un portal público tiene por defecto si uno se olvida.
    """
    reserva = sesion.get(Reserva, reserva_id)
    if reserva is None or reserva.cliente_id != cuenta.cliente_id:
        # Mismo error para "no existe" y "no es tuya": distinguirlos diría
        # cuáles ids existen.
        raise TurnoNoDisponible("No encontramos esa reserva.")
    return servicio_reservas.cambiar_estado(
        sesion, reserva.id, EstadoReserva.CANCELADA, motivo="Cancelada por el jugador"
    )


def con_pago_pendiente(sesion: Session, cuenta: CuentaDeJugador) -> int:
    """Cuántas reservas tiene esperando pago. Para no dejarlo abrir diez a la vez."""
    return sesion.scalar(
        select(func.count(Reserva.id))
        .join(PagoDeReserva, PagoDeReserva.reserva_id == Reserva.id)
        .where(
            Reserva.cliente_id == cuenta.cliente_id,
            Reserva.estado == EstadoReserva.PROVISORIA,
            PagoDeReserva.estado == EstadoPago.PENDIENTE,
        )
    ) or 0


#: Cuántas reservas sin pagar puede tener abiertas un jugador a la vez.
#:
#: 🔴 **Sin este tope, una sola cuenta bloquea la agenda entera.** Cada reserva
#: provisoria saca un turno de circulación durante la ventana de pago; en bucle,
#: eso deja el viernes a la noche sin nada que vender sin haber pagado un peso.
#: Con tres, el que quiere hacer daño tiene que esperar el vencimiento.
MAXIMO_SIN_PAGAR = 3
