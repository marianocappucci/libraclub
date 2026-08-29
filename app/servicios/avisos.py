"""El motor de avisos: qué hay que avisarle al cliente, y mandarlo.

Tres avisos, y son los que manda todo el rubro: **confirmación** cuando el turno
queda tomado, **recordatorio** unas horas antes, y **cancelación** cuando se
cae. Es la brecha número uno contra los competidores argentinos —Turnito,
Canchero, ATC y EasyCancha lo tienen— y hasta hoy este producto no mandaba nada.

## Por qué no hay una cola

La forma obvia es una tabla de pendientes que se llena cuando pasa algo: se
confirma un turno, se encolan sus tres avisos. **No se hizo así**, y el motivo
es medible: hoy hay **tres** caminos distintos que dejan una reserva confirmada
y ninguno pasa por los otros dos —

1. `servicios/reservas.crear()`, que es el mostrador y nace `CONFIRMADA`;
2. `servicios/reservas.cambiar_estado()`, que es el botón de la agenda;
3. `servicios/pagos.aplicar_pago_aprobado()`, el webhook de MercadoPago, que
   escribe `reserva.estado = EstadoReserva.CONFIRMADA` **a mano**.

Con una cola hay que acordarse de encolar en los tres, y el día que aparezca un
cuarto —la reserva desde el panel, la importación de una planilla— el síntoma no
es un error: es que **no le llega el mail y nadie se entera**. Un aviso que no
sale no rompe nada, que es exactamente lo que lo hace difícil de encontrar.

Acá el barrido **le pregunta a las reservas** qué corresponde mandar y usa la
tabla `avisos` sólo como registro de lo ya intentado. Un camino nuevo que
confirme un turno queda cubierto sin tocar este archivo. El precio es una
consulta por regla en cada corrida del cron, con índice y acotada por fecha.

## Qué garantiza que no salga dos veces

`uq_avisos_reserva_tipo_canal` —única sobre `(reserva_id, tipo, canal,
horas_antes)` con `NULLS NOT DISTINCT`—. No el `if` de Python: dos corridas del
cron superpuestas pasan las dos por el `if` antes de que cualquiera escriba.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import and_, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.avisos import Aviso
from app.models.enums import CanalAviso, EstadoAviso, EstadoReserva, TipoAviso
from app.models.maestros import Cliente
from app.models.reservas import Reserva
from app.tiempo import ahora, formatear_fecha_hora

#: Con cuánta anticipación se recuerda un turno, en horas. Dos avisos: uno el
#: día antes —a tiempo para cancelar y que el turno se revenda— y otro dos horas
#: antes, que es el que evita el no-show.
#:
#: Es una constante y no una config porque todavía no hay pantalla que la edite;
#: cuando la haya, sale de ahí y esto queda como default. Lo que **no** puede
#: pasar es que se vuelva parte del nombre del tipo de aviso: por eso la
#: anticipación es una columna (ver `models/enums.TipoAviso`).
ANTICIPACIONES: tuple[int, ...] = (24, 2)

#: Cuánto después de creada una reserva todavía tiene sentido confirmarla por
#: mail.
#:
#: 🔴 **Es lo que impide el mailing masivo del día que esto se enciende.** Sin
#: la ventana, la primera corrida del cron encuentra *todas* las reservas
#: futuras ya confirmadas —las que se cargaron durante meses, sin que nadie
#: prometiera un mail— y le escribe a cada cliente por cada turno. El costo de
#: tenerla es que si el cron estuvo caído tres horas, esas confirmaciones no
#: salen; y es el lado correcto para equivocarse.
VENTANA_DE_CONFIRMACION = timedelta(hours=2)

#: Hasta cuándo se avisa una cancelación. Un turno de la semana pasada que
#: alguien pasa a `cancelada` para ordenar la agenda no es noticia para nadie.
VENTANA_DE_CANCELACION = timedelta(hours=24)

#: Cuántas veces se reintenta un envío fallido antes de dejarlo. El reintento lo
#: hace la corrida siguiente del cron: no hay backoff propio porque el cron ya
#: es el intervalo.
MAX_INTENTOS = 3


class Transporte(Protocol):
    """Cómo sale un aviso. Un objeto por canal."""

    canal: CanalAviso

    def disponible(self) -> bool:
        """Si hay con qué mandar. Un SMTP sin configurar devuelve `False`.

        Se pregunta **antes** de barrer: sin esto, una instancia sin SMTP
        acumula un `FALLIDO` por reserva por corrida y a los tres intentos deja
        de mandarle a ese cliente para siempre — por una config que a lo mejor
        se completa mañana.
        """

    def enviar(self, *, destino: str, asunto: str, cuerpo: str) -> None:
        """Manda, o levanta una excepción con el motivo."""


@dataclass(frozen=True, slots=True)
class Candidato:
    """Un aviso que corresponde mandar ahora, y el intento anterior si lo hubo."""

    reserva: Reserva
    tipo: TipoAviso
    horas_antes: int | None
    previo: Aviso | None


@dataclass(frozen=True, slots=True)
class Resumen:
    """Lo que hizo una corrida. Es lo que el cron imprime al log."""

    enviados: int = 0
    fallidos: int = 0
    omitidos: int = 0

    def __str__(self) -> str:
        return (
            f"enviados: {self.enviados} · fallidos: {self.fallidos} · "
            f"omitidos: {self.omitidos}"
        )


def _sin_aviso_terminal(tipo: TipoAviso, canal: CanalAviso, horas: int | None):
    """`NOT EXISTS` de un aviso que ya cerró el tema.

    Un `FALLIDO` con intentos de sobra **no** cierra nada: es justamente el que
    hay que reintentar, así que no entra en el `EXISTS` y la reserva vuelve a
    salir como candidata.
    """
    condiciones = [
        Aviso.reserva_id == Reserva.id,
        Aviso.tipo == tipo,
        Aviso.canal == canal,
        (Aviso.estado != EstadoAviso.FALLIDO) | (Aviso.intentos >= MAX_INTENTOS),
    ]
    if horas is None:
        condiciones.append(Aviso.horas_antes.is_(None))
    else:
        condiciones.append(Aviso.horas_antes == horas)
    return ~exists().where(and_(*condiciones))


def _previo(sesion: Session, reserva_id: int, tipo: TipoAviso, canal: CanalAviso,
            horas: int | None) -> Aviso | None:
    """El intento anterior para esta combinación, si existe (siempre `FALLIDO`).

    Se busca de a uno y no con un `JOIN` en la consulta grande porque son pocos:
    un envío falla cuando el SMTP se cayó, y eso es raro. La consulta simple se
    lee mejor y el costo aparece sólo cuando hubo fallas.
    """
    condicion = (
        Aviso.horas_antes.is_(None) if horas is None else Aviso.horas_antes == horas
    )
    return sesion.scalars(
        select(Aviso).where(
            Aviso.reserva_id == reserva_id,
            Aviso.tipo == tipo,
            Aviso.canal == canal,
            condicion,
        )
    ).first()


def pendientes(
    sesion: Session, canal: CanalAviso, momento: datetime | None = None
) -> list[Candidato]:
    """Qué corresponde avisar por este canal en este instante.

    No toca la base más que para leer. Separada del envío a propósito: es la
    parte que tiene las reglas, y así se puede probar sin transporte y mirar sin
    mandar nada.
    """
    momento = momento or ahora()
    candidatos: list[Candidato] = []

    # 1. Confirmación: el turno quedó tomado recién.
    #
    # 🔑 **No hace falta filtrar `cliente_id IS NOT NULL`**, y no es un olvido:
    # `ck_reservas_cliente_segun_estado` ya garantiza que una reserva viva que no
    # es un bloqueo tiene cliente. Un filtro que la base hace imposible de violar
    # no protege de nada y esconde cuál es la regla que sí protege — acá, el
    # estado. Los bloqueos quedan afuera por `estado == CONFIRMADA`.
    confirmaciones = sesion.scalars(
        select(Reserva).where(
            Reserva.estado == EstadoReserva.CONFIRMADA,
            Reserva.comienza_at > momento,
            Reserva.created_at >= momento - VENTANA_DE_CONFIRMACION,
            _sin_aviso_terminal(TipoAviso.CONFIRMACION, canal, None),
        )
    ).all()
    candidatos += [
        Candidato(
            r,
            TipoAviso.CONFIRMACION,
            None,
            _previo(sesion, r.id, TipoAviso.CONFIRMACION, canal, None),
        )
        for r in confirmaciones
    ]

    # 2. Recordatorios: falta poco para jugar.
    for horas in ANTICIPACIONES:
        ventana = timedelta(hours=horas)
        recordatorios = sesion.scalars(
            select(Reserva).where(
                Reserva.estado == EstadoReserva.CONFIRMADA,
                Reserva.comienza_at > momento,
                Reserva.comienza_at <= momento + ventana,
                # 🔑 El turno tiene que haberse tomado **antes** de que se
                # abriera la ventana. Sin esto, el que reserva a las 19:00 para
                # las 20:00 recibe el «recordatorio de 24 h» tres minutos
                # después de la confirmación, que es ruido y se lee como un
                # error del sistema.
                Reserva.created_at < Reserva.comienza_at - ventana,
                _sin_aviso_terminal(TipoAviso.RECORDATORIO, canal, horas),
            )
        ).all()
        candidatos += [
            Candidato(
                r,
                TipoAviso.RECORDATORIO,
                horas,
                _previo(sesion, r.id, TipoAviso.RECORDATORIO, canal, horas),
            )
            for r in recordatorios
        ]

    # 3. Cancelación: se cayó un turno que el cliente creía tomado.
    cancelaciones = sesion.scalars(
        select(Reserva).where(
            Reserva.estado == EstadoReserva.CANCELADA,
            Reserva.comienza_at > momento - VENTANA_DE_CANCELACION,
            # 🔴 **Sólo se avisa la cancelación de algo que se confirmó y se
            # avisó**, y este `EXISTS` es la única puerta que lo sostiene.
            #
            # Cubre los dos casos que llegan acá y que no son una cancelación de
            # verdad: la provisoria que venció sin pagarse —mandarle «se canceló
            # tu reserva» a quien nunca tuvo una es peor que no mandar nada: cree
            # que perdió un turno— y el **bloqueo que se quita**, que pasa a
            # `cancelada` sin cliente (`ck_reservas_cliente_segun_estado` exime a
            # las canceladas justamente por eso).
            exists().where(
                and_(
                    Aviso.reserva_id == Reserva.id,
                    Aviso.tipo == TipoAviso.CONFIRMACION,
                    Aviso.canal == canal,
                    Aviso.estado == EstadoAviso.ENVIADO,
                )
            ),
            _sin_aviso_terminal(TipoAviso.CANCELACION, canal, None),
        )
    ).all()
    candidatos += [
        Candidato(
            r,
            TipoAviso.CANCELACION,
            None,
            _previo(sesion, r.id, TipoAviso.CANCELACION, canal, None),
        )
        for r in cancelaciones
    ]

    return candidatos


def _complejo() -> str:
    """Cómo se llama el complejo. De la config de LibraCore, como la factura."""
    from libracore import config_manager

    return (config_manager.load().get("empresa_nombre") or "").strip()


def redactar(candidato: Candidato) -> tuple[str, str]:
    """Asunto y cuerpo del aviso. Texto plano, en castellano y con vos.

    Sin HTML a propósito: el mail de un complejo de barrio se lee en el celular,
    y un texto corto entra entero en la notificación. Un HTML con logo agrega
    peso, se rompe en la mitad de los clientes de mail y no dice nada más.
    """
    reserva = candidato.reserva
    cancha = reserva.cancha
    cuando = formatear_fecha_hora(reserva.comienza_at)
    complejo = _complejo()
    firma = f"\n\n{complejo}" if complejo else ""
    donde = f"{cancha.nombre}" if cancha is not None else "tu cancha"
    nombre = reserva.cliente.nombre if reserva.cliente is not None else ""
    hola = f"Hola {nombre}," if nombre else "Hola,"

    if candidato.tipo is TipoAviso.CONFIRMACION:
        asunto = f"Turno confirmado: {donde}, {cuando}"
        cuerpo = (
            f"{hola}\n\n"
            f"Tu turno quedó confirmado.\n\n"
            f"Cancha: {donde}\n"
            f"Cuándo: {cuando}\n"
            f"{_linea_de_precio(reserva)}"
            f"\nSi no vas a poder venir, avisanos así lo liberamos."
            f"{firma}"
        )
        return asunto, cuerpo

    if candidato.tipo is TipoAviso.RECORDATORIO:
        horas = candidato.horas_antes
        cuanto = "mañana" if horas and horas >= 24 else f"en {horas} horas"
        asunto = f"Te esperamos {cuanto}: {donde}, {cuando}"
        cuerpo = (
            f"{hola}\n\n"
            f"Te recordamos tu turno.\n\n"
            f"Cancha: {donde}\n"
            f"Cuándo: {cuando}\n"
            f"{_linea_de_precio(reserva)}"
            f"\nSi no vas a poder venir, avisanos así lo liberamos."
            f"{firma}"
        )
        return asunto, cuerpo

    asunto = f"Turno cancelado: {donde}, {cuando}"
    motivo = f"\nMotivo: {reserva.motivo}\n" if reserva.motivo else ""
    cuerpo = (
        f"{hola}\n\n"
        f"Tu turno del {cuando} en {donde} quedó cancelado.\n"
        f"{motivo}"
        f"\nCualquier duda, respondé este mail."
        f"{firma}"
    )
    return asunto, cuerpo


def pesos(valor: Decimal) -> str:
    """`$10.000,00`: miles con punto y decimales con coma, como en Argentina.

    ⚠️ El `.replace(",", ".")` directo sobre el formato de Python **no alcanza**
    y es el error fácil: `f"{10000:,.2f}"` da `10,000.00`, y cambiar sólo la coma
    deja `10.000.00`, que no es un número en ningún lado. Hay que rotar los dos
    separadores, y por eso pasa por el guión bajo.

    Vive acá y no en `tiempo.py` —que es de fechas— ni en un módulo nuevo: hoy el
    único que formatea plata en el backend es este texto. El día que haya un
    segundo consumidor, sube; inventarle un módulo ahora sería un archivo con una
    función y ningún llamador de fondo.
    """
    return "$" + f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _linea_de_precio(reserva: Reserva) -> str:
    """El precio, y la seña si hay. Vacío en los bloqueos, que no tienen."""
    if reserva.precio is None:
        return ""
    linea = f"Precio: {pesos(reserva.precio)}\n"
    if reserva.sena is not None and reserva.sena > 0:
        linea += f"Seña: {pesos(reserva.sena)}\n"
    return linea


def _destino(reserva: Reserva, canal: CanalAviso) -> str:
    """A dónde va, según el canal. Vacío si el cliente no dejó ese dato."""
    cliente: Cliente | None = reserva.cliente
    if cliente is None:
        return ""
    if canal is CanalAviso.EMAIL:
        return (cliente.email or "").strip()
    return (cliente.telefono or "").strip()


def _anotar(
    sesion: Session,
    candidato: Candidato,
    canal: CanalAviso,
    *,
    estado: EstadoAviso,
    destino: str,
    asunto: str | None = None,
    cuerpo: str | None = None,
    detalle: str | None = None,
) -> None:
    """Deja la fila del intento: una nueva, o el reintento sobre la que había.

    ⚠️ El `IntegrityError` se atrapa **acá y no se ignora en el llamador**: si
    dos corridas del cron se superponen, la segunda choca contra
    `uq_avisos_reserva_tipo_canal` y eso significa que el aviso ya salió por la
    otra. Es el resultado correcto, no un error — pero hay que hacer `rollback`
    del `SAVEPOINT`, si no la transacción queda abortada y la corrida entera se
    cae con «current transaction is aborted».
    """
    previo = candidato.previo
    if previo is not None:
        previo.estado = estado
        previo.destino = destino
        previo.asunto = asunto
        previo.cuerpo = cuerpo
        previo.detalle = detalle
        previo.intentos = (previo.intentos or 0) + 1
        previo.enviado_at = ahora() if estado is EstadoAviso.ENVIADO else None
        sesion.flush()
        return

    aviso = Aviso(
        reserva_id=candidato.reserva.id,
        tipo=candidato.tipo,
        canal=canal,
        horas_antes=candidato.horas_antes,
        estado=estado,
        destino=destino,
        asunto=asunto,
        cuerpo=cuerpo,
        detalle=detalle,
        intentos=1,
        enviado_at=ahora() if estado is EstadoAviso.ENVIADO else None,
    )
    sesion.add(aviso)
    try:
        with sesion.begin_nested():
            sesion.flush()
    except IntegrityError:
        sesion.expunge(aviso)


def despachar(
    sesion: Session, transporte: Transporte, momento: datetime | None = None
) -> Resumen:
    """Manda todo lo que corresponde por este transporte. Devuelve el resumen.

    No hace `commit`: lo hace el llamador, como todos los servicios de este
    repo. El script del cron commitea una vez al final; los tests miran la
    sesión.

    ⚠️ **Eso deja una ventana conocida**: mandar un mail es un efecto que no
    entra en la transacción, así que si el proceso muere entre el envío y el
    `commit`, esos avisos no quedaron registrados y la corrida siguiente los
    manda **de nuevo**. El techo del daño es una corrida —un cliente recibe dos
    veces el mismo mail— y el otro lado del canje sería anotar antes de mandar,
    que convierte la misma caída en un aviso que **no llega nunca**. Para un
    recordatorio de turno, duplicado es mejor que faltante.
    """
    if not transporte.disponible():
        return Resumen()

    enviados = fallidos = omitidos = 0
    for candidato in pendientes(sesion, transporte.canal, momento):
        destino = _destino(candidato.reserva, transporte.canal)
        cliente = candidato.reserva.cliente
        if not destino:
            _anotar(
                sesion, candidato, transporte.canal,
                estado=EstadoAviso.OMITIDO, destino="",
                detalle=f"El cliente no tiene {transporte.canal.value}.",
            )
            omitidos += 1
            continue
        if cliente is not None and not cliente.acepta_avisos:
            _anotar(
                sesion, candidato, transporte.canal,
                estado=EstadoAviso.OMITIDO, destino=destino,
                detalle="El cliente pidió no recibir avisos.",
            )
            omitidos += 1
            continue

        asunto, cuerpo = redactar(candidato)
        try:
            transporte.enviar(destino=destino, asunto=asunto, cuerpo=cuerpo)
        except Exception as exc:  # noqa: BLE001 — cualquier falla de red o SMTP
            _anotar(
                sesion, candidato, transporte.canal,
                estado=EstadoAviso.FALLIDO, destino=destino,
                asunto=asunto, cuerpo=cuerpo, detalle=str(exc)[:500],
            )
            fallidos += 1
            continue

        _anotar(
            sesion, candidato, transporte.canal,
            estado=EstadoAviso.ENVIADO, destino=destino,
            asunto=asunto, cuerpo=cuerpo,
        )
        enviados += 1

    return Resumen(enviados=enviados, fallidos=fallidos, omitidos=omitidos)


class TransporteEmail:
    """El canal de mail, sobre el SMTP que ya tiene configurado la instancia.

    🔑 **No trae SMTP propio.** Usa `libraauth.email_sender`, que es el mismo que
    manda el mail de recuperación de contraseña, y la config sale de
    `resolver_smtp_config` — o sea de la pantalla «Configuración → Email» que ya
    existe. Un segundo lugar donde cargar un servidor de correo sería un lugar
    más donde el dueño puede cargarlo mal.
    """

    canal = CanalAviso.EMAIL

    def __init__(self, config_smtp) -> None:
        #: Un callable y no el valor: la config vive en la base y la pantalla la
        #: edita mientras el proceso corre. Resolverla una vez al construir haría
        #: que el cron use la de cuando arrancó.
        self._config = config_smtp

    def disponible(self) -> bool:
        return bool(self._config().configurado)

    def enviar(self, *, destino: str, asunto: str, cuerpo: str) -> None:
        from libraauth.email_sender import enviar_email

        enviar_email(self._config(), to_email=destino, asunto=asunto, cuerpo=cuerpo)
