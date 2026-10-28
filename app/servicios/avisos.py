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

## Qué se suma en ADR-029

- **El aviso de seña por vencer** (`TipoAviso.SENA_POR_VENCER`): el turno que el portal retiene
  `VENCIMIENTO_PROVISORIA` mientras se paga se está por liberar. Como los otros, **se deduce**: la
  barrida le pregunta a `reservas` por las provisorias con pago pendiente que vencen en
  `VENTANA_DE_SENA`, sin cola.
- **WhatsApp en modo registro** (`TransporteWhatsAppRegistro`): arma el mensaje y lo anota como
  `registrado`, sin mandar nada. Es la costura para el proveedor real, que va en el motor.
- **La configuración** (`ConfiguracionDeAvisos`): qué tipos salen y si WhatsApp está prendido. No es
  el interruptor general —ése sigue siendo el cron—.

## Qué garantiza que no salga dos veces

`uq_avisos_reserva_tipo_canal` —única sobre `(reserva_id, tipo, canal,
horas_antes)` con `NULLS NOT DISTINCT`—. No el `if` de Python: dos corridas del
cron superpuestas pasan las dos por el `if` antes de que cualquiera escriba.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import and_, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.avisos import Aviso, ConfigAvisos
from app.models.enums import CanalAviso, EstadoAviso, EstadoReserva, ModoWhatsapp, TipoAviso
from app.models.maestros import Cliente
from app.models.reservas import EstadoPago, PagoDeReserva, Reserva
from app.servicios import cancelacion as servicio_cancelacion
from app.tiempo import a_local, ahora, formatear_fecha_hora

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

#: Cuánto antes de que venza la retención se avisa que el turno se libera (ADR-029).
#:
#: 🔑 **Son 8 minutos y no 5 por el cron.** El cron corre cada 5 minutos, así que un aviso que
#: "corresponde" a los 5 minutos puede salir hasta 5 minutos tarde: es decir, **justo cuando el
#: turno ya se liberó**. Con 8 sale entre 3 y 8 minutos antes del vencimiento, que sobre los 15
#: de `VENCIMIENTO_PROVISORIA` deja al jugador tiempo de volver a pagar. Si cambia el período del
#: cron o el de la retención, esta constante se revisa con ellos.
VENTANA_DE_SENA = timedelta(minutes=8)

#: Cuántas veces se reintenta un envío fallido antes de dejarlo. El reintento lo
#: hace la corrida siguiente del cron: no hay backoff propio porque el cron ya
#: es el intervalo.
MAX_INTENTOS = 3


class Transporte(Protocol):
    """Cómo sale un aviso. Un objeto por canal."""

    canal: CanalAviso
    #: `True` si el transporte **no manda nada de verdad** y sólo deja el mensaje anotado
    #: (`EstadoAviso.REGISTRADO`). Un transporte que no lo declara es real. Importa porque lo
    #: registrado por uno simulado **no cierra el tema** para uno real: ver `_sin_aviso_terminal`.
    simulado: bool

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
    #: Qué pasó con la seña, contado para el cliente. Sólo en las cancelaciones,
    #: y `None` si no hubo seña.
    #:
    #: 🔑 Se resuelve al armar el candidato —que ya tiene la sesión— y no en
    #: `redactar`, para que `redactar` siga siendo una función pura que no toca
    #: la base. El texto sale de `servicios/cancelacion.py`: es el mismo que el
    #: portal le muestra al jugador al cancelar, no una segunda redacción.
    sena: str | None = None
    #: Lo que falta pagar. Sólo en `SENA_POR_VENCER`: sale del pago pendiente, que es lo que el
    #: jugador va a ver en MercadoPago, y no de la reserva.
    a_pagar: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ConfiguracionDeAvisos:
    """Qué avisos salen y por dónde, ya leída. Sin fila en la base son los defaults."""

    whatsapp: ModoWhatsapp = ModoWhatsapp.APAGADO
    confirmacion: bool = True
    recordatorio: bool = True
    cancelacion: bool = True
    sena_por_vencer: bool = True


def configuracion(sesion: Session) -> ConfiguracionDeAvisos:
    """La configuración de la instancia. **Sin fila, los defaults** (todo prendido, WhatsApp apagado)."""
    fila = sesion.get(ConfigAvisos, 1)
    if fila is None:
        return ConfiguracionDeAvisos()
    return ConfiguracionDeAvisos(
        whatsapp=fila.whatsapp,
        confirmacion=fila.avisar_confirmacion,
        recordatorio=fila.avisar_recordatorio,
        cancelacion=fila.avisar_cancelacion,
        sena_por_vencer=fila.avisar_sena_por_vencer,
    )


def guardar_configuracion(sesion: Session, nueva: ConfiguracionDeAvisos) -> ConfiguracionDeAvisos:
    """Crea o actualiza la fila única. No hace `commit`: lo hace el llamador.

    Quién la tocó lo anota `app/auditoria.py` solo (`created_by` / `updated_by`).
    """
    fila = sesion.get(ConfigAvisos, 1)
    if fila is None:
        fila = ConfigAvisos(id=1)
        sesion.add(fila)
    fila.whatsapp = nueva.whatsapp
    fila.avisar_confirmacion = nueva.confirmacion
    fila.avisar_recordatorio = nueva.recordatorio
    fila.avisar_cancelacion = nueva.cancelacion
    fila.avisar_sena_por_vencer = nueva.sena_por_vencer
    sesion.flush()
    return nueva


@dataclass(frozen=True, slots=True)
class Resumen:
    """Lo que hizo una corrida. Es lo que el cron imprime al log."""

    enviados: int = 0
    fallidos: int = 0
    omitidos: int = 0
    #: Los que un transporte simulado dejó anotados sin mandar (ADR-029).
    registrados: int = 0

    def __str__(self) -> str:
        texto = (
            f"enviados: {self.enviados} · fallidos: {self.fallidos} · "
            f"omitidos: {self.omitidos}"
        )
        # Sólo cuando hay: la línea del cron de una instancia sin WhatsApp queda como siempre.
        return f"{texto} · registrados: {self.registrados}" if self.registrados else texto


def _sin_aviso_terminal(
    tipo: TipoAviso, canal: CanalAviso, horas: int | None, *, simulado: bool = False
):
    """`NOT EXISTS` de un aviso que ya cerró el tema.

    Un `FALLIDO` con intentos de sobra **no** cierra nada: es justamente el que
    hay que reintentar, así que no entra en el `EXISTS` y la reserva vuelve a
    salir como candidata.

    🔑 **Un `REGISTRADO` cierra el tema sólo para un transporte simulado.** Lo que quedó anotado
    sin salir (WhatsApp en modo registro) es un mensaje que nadie recibió: cuando se conecte un
    proveedor real tiene que mandarse, no darse por hecho. Con `simulado=True` la barrida no lo
    vuelve a evaluar —si no, anotaría el mismo mensaje en cada corrida—; con uno real, sí.
    """
    reintentable = (Aviso.estado == EstadoAviso.FALLIDO) & (Aviso.intentos < MAX_INTENTOS)
    if not simulado:
        reintentable = reintentable | (Aviso.estado == EstadoAviso.REGISTRADO)
    condiciones = [
        Aviso.reserva_id == Reserva.id,
        Aviso.tipo == tipo,
        Aviso.canal == canal,
        ~reintentable,
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


def _monto_pendiente(sesion: Session, reserva_id: int) -> Decimal | None:
    """Lo que falta pagar de una reserva: el monto de su pago pendiente (el más nuevo)."""
    return sesion.scalar(
        select(PagoDeReserva.monto)
        .where(
            PagoDeReserva.reserva_id == reserva_id,
            PagoDeReserva.estado == EstadoPago.PENDIENTE,
        )
        .order_by(PagoDeReserva.id.desc())
        .limit(1)
    )


def pendientes(
    sesion: Session,
    canal: CanalAviso,
    momento: datetime | None = None,
    *,
    simulado: bool = False,
    config: ConfiguracionDeAvisos | None = None,
) -> list[Candidato]:
    """Qué corresponde avisar por este canal en este instante.

    No toca la base más que para leer. Separada del envío a propósito: es la
    parte que tiene las reglas, y así se puede probar sin transporte y mirar sin
    mandar nada.

    `config` decide qué **tipos** se evalúan (sin ella, los de la instancia); `simulado` es lo que
    declara el transporte y cambia qué cuenta como «ya avisado» (ver `_sin_aviso_terminal`).
    """
    momento = momento or ahora()
    config = config or configuracion(sesion)
    candidatos: list[Candidato] = []
    # Para no repetir `simulado=` en cada regla.
    def sin_aviso(tipo, horas):
        return _sin_aviso_terminal(tipo, canal, horas, simulado=simulado)

    # Qué cuenta como «la confirmación salió» para poder avisar la cancelación: lo enviado, y lo
    # registrado sólo si el transporte también es simulado (si no, nunca llegó a nadie).
    salieron = (
        (EstadoAviso.ENVIADO, EstadoAviso.REGISTRADO) if simulado else (EstadoAviso.ENVIADO,)
    )

    # 1. Confirmación: el turno quedó tomado recién.
    #
    # 🔑 **No hace falta filtrar `cliente_id IS NOT NULL`**, y no es un olvido:
    # `ck_reservas_cliente_segun_estado` ya garantiza que una reserva viva que no
    # es un bloqueo tiene cliente. Un filtro que la base hace imposible de violar
    # no protege de nada y esconde cuál es la regla que sí protege — acá, el
    # estado. Los bloqueos quedan afuera por `estado == CONFIRMADA`.
    if config.confirmacion:
        confirmaciones = sesion.scalars(
            select(Reserva).where(
                Reserva.estado == EstadoReserva.CONFIRMADA,
                Reserva.comienza_at > momento,
                Reserva.created_at >= momento - VENTANA_DE_CONFIRMACION,
                sin_aviso(TipoAviso.CONFIRMACION, None),
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
    if config.recordatorio:
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
                    sin_aviso(TipoAviso.RECORDATORIO, horas),
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
    if config.cancelacion:
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
                        Aviso.estado.in_(salieron),
                    )
                ),
                sin_aviso(TipoAviso.CANCELACION, None),
            )
        ).all()
        candidatos += [
            Candidato(
                r,
                TipoAviso.CANCELACION,
                None,
                _previo(sesion, r.id, TipoAviso.CANCELACION, canal, None),
                sena=servicio_cancelacion.sena_para_el_aviso(sesion, r),
            )
            for r in cancelaciones
        ]

    # 4. Seña por vencer: el turno retenido mientras se paga se libera en unos minutos.
    #
    # 🔑 **Las dos condiciones sobre el pago son la regla.** Una provisoria sin pago pendiente
    # no es una seña que se esté pagando (la del mostrador, por ejemplo, no pasa por MercadoPago)
    # y una con el pago aprobado ya no es provisoria. `vence_at > momento` evita avisar de un
    # turno que ya se perdió: esa reserva la cancela `vencer_provisorias`, y mandarle «se libera
    # en unos minutos» cuando ya se liberó es peor que no mandar nada.
    if config.sena_por_vencer:
        por_vencer = sesion.scalars(
            select(Reserva).where(
                Reserva.estado == EstadoReserva.PROVISORIA,
                Reserva.vence_at.is_not(None),
                Reserva.vence_at > momento,
                Reserva.vence_at <= momento + VENTANA_DE_SENA,
                exists().where(
                    PagoDeReserva.reserva_id == Reserva.id,
                    PagoDeReserva.estado == EstadoPago.PENDIENTE,
                ),
                sin_aviso(TipoAviso.SENA_POR_VENCER, None),
            )
        ).all()
        candidatos += [
            Candidato(
                r,
                TipoAviso.SENA_POR_VENCER,
                None,
                _previo(sesion, r.id, TipoAviso.SENA_POR_VENCER, canal, None),
                a_pagar=_monto_pendiente(sesion, r.id),
            )
            for r in por_vencer
        ]

    return candidatos


def _complejo() -> str:
    """Cómo se llama el complejo. De la config de LibraCore, como la factura."""
    from libracore import config_manager

    return (config_manager.load().get("empresa_nombre") or "").strip()


def redactar(
    candidato: Candidato, canal: CanalAviso = CanalAviso.EMAIL
) -> tuple[str, str]:
    """Asunto y cuerpo del aviso. Texto plano, en castellano y con vos.

    Sin HTML a propósito: el mail de un complejo de barrio se lee en el celular,
    y un texto corto entra entero en la notificación. Un HTML con logo agrega
    peso, se rompe en la mitad de los clientes de mail y no dice nada más.

    Por WhatsApp no hay asunto: viene vacío y el título va en negrita (`*así*`) como primera
    línea del cuerpo, y donde el mail dice «respondé este mail» el mensaje dice «respondé este
    mensaje». El texto de fondo es el mismo —una sola redacción por aviso—, sólo cambia el envoltorio.
    """
    asunto, cuerpo = _redactar(candidato, "mail" if canal is CanalAviso.EMAIL else "mensaje")
    if canal is CanalAviso.WHATSAPP:
        return "", f"*{asunto}*\n\n{cuerpo}"
    return asunto, cuerpo


def _redactar(candidato: Candidato, medio: str) -> tuple[str, str]:
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

    if candidato.tipo is TipoAviso.SENA_POR_VENCER:
        hasta = a_local(reserva.vence_at).strftime("%H:%M") if reserva.vence_at else ""
        asunto = f"Tu turno se libera a las {hasta}: {donde}, {cuando}"
        monto = f"A pagar: {pesos(candidato.a_pagar)}\n" if candidato.a_pagar else ""
        cuerpo = (
            f"{hola}\n\n"
            f"Tu turno está retenido hasta las {hasta} esperando el pago.\n\n"
            f"Cancha: {donde}\n"
            f"Cuándo: {cuando}\n"
            f"{monto}"
            f"\nSi el pago no se acredita a tiempo, el turno se libera y lo puede tomar otra "
            f"persona. Podés completarlo desde «Mis reservas» en la página del complejo."
            f"{firma}"
        )
        return asunto, cuerpo

    asunto = f"Turno cancelado: {donde}, {cuando}"
    motivo = f"\nMotivo: {reserva.motivo}\n" if reserva.motivo else ""
    # 🔑 Qué pasó con la plata, si hubo. Es lo primero que pregunta el que
    # recibe este mail —«¿y mi seña?»—, y hasta el 2026-09-11 sólo el portal lo
    # contestaba: el que canceló por teléfono tenía que volver a llamar. Sin
    # seña no se dice nada: hablar de una plata que nunca entró confunde más
    # de lo que explica.
    sena = f"\n{candidato.sena}\n" if candidato.sena else ""
    cuerpo = (
        f"{hola}\n\n"
        f"Tu turno del {cuando} en {donde} quedó cancelado.\n"
        f"{motivo}"
        f"{sena}"
        f"\nCualquier duda, respondé este {medio}."
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


def telefono_para_whatsapp(texto: str | None) -> str:
    """El teléfono como lo piden los proveedores de WhatsApp: sólo dígitos, con país. Vacío si no se sabe.

    `11 5555-1234`, `(011) 5555-1234` y `+54 9 11 5555 1234` son el mismo celular y salen como
    `5491155551234`. **Ante la duda devuelve vacío** y el aviso queda `omitido` con su motivo: un
    número mal armado es un mensaje a un desconocido, que es peor que un mensaje que no sale. Por
    eso sólo se reconocen formas sin ambigüedad:

    - con el 54 de Argentina (con o sin el 9 del celular);
    - 10 dígitos nacionales (característica + número), con o sin el 0 de adelante. La característica
      empieza con 11, 2 o 3: un «15 5555-1234» —el 15 sin característica— no es un número completo;
    - el «15» que se marca entre la característica y el número, **sólo con la característica 11**:
      en el interior la característica tiene 2, 3 o 4 dígitos y el «15» no se puede ubicar solo;
    - otro país, **sólo si se escribió con `+` o `00`**: sin ese prefijo un número largo puede ser
      un argentino con el 15 puesto, y mandárselo a un desconocido es lo que se quiere evitar.
    """
    crudo = (texto or "").strip()
    digitos = re.sub(r"\D", "", crudo)
    internacional = crudo.startswith("+") or crudo.startswith("00")
    if crudo.startswith("00"):
        digitos = digitos[2:]

    if internacional:
        if digitos.startswith("54"):
            resto = digitos[2:]
            if resto.startswith("9"):
                return digitos if len(resto) == 11 else ""
            return f"549{resto}" if len(resto) == 10 else ""
        return digitos if 8 <= len(digitos) <= 15 and not digitos.startswith("0") else ""

    if digitos.startswith("0"):
        digitos = digitos[1:]
    if len(digitos) == 12 and digitos.startswith("1115"):
        digitos = "11" + digitos[4:]
    if len(digitos) == 10 and (digitos.startswith("11") or digitos[0] in "23"):
        return f"549{digitos}"
    return ""


#: Cómo se dice, en el motivo de un aviso omitido, qué dato le falta al cliente para ese canal.
_DATO_DEL_CANAL = {
    CanalAviso.EMAIL: "email",
    CanalAviso.WHATSAPP: "un teléfono que WhatsApp reconozca",
}

#: El `detalle` de lo que un transporte simulado dejó anotado.
DETALLE_REGISTRADO = "Registrado en modo prueba: no se mandó nada."


def _destino(reserva: Reserva, canal: CanalAviso) -> str:
    """A dónde va, según el canal. Vacío si el cliente no dejó ese dato."""
    cliente: Cliente | None = reserva.cliente
    if cliente is None:
        return ""
    if canal is CanalAviso.EMAIL:
        return (cliente.email or "").strip()
    return telefono_para_whatsapp(cliente.telefono)


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

    # Los que no declaran `simulado` (el de mail, los dobles de los tests) son reales.
    simulado = bool(getattr(transporte, "simulado", False))
    enviados = fallidos = omitidos = registrados = 0
    for candidato in pendientes(sesion, transporte.canal, momento, simulado=simulado):
        destino = _destino(candidato.reserva, transporte.canal)
        cliente = candidato.reserva.cliente
        if not destino:
            _anotar(
                sesion, candidato, transporte.canal,
                estado=EstadoAviso.OMITIDO, destino="",
                detalle=f"El cliente no tiene {_DATO_DEL_CANAL[transporte.canal]}.",
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

        asunto, cuerpo = redactar(candidato, transporte.canal)
        try:
            transporte.enviar(destino=destino, asunto=asunto, cuerpo=cuerpo)
        except Exception as exc:  # noqa: BLE001 — cualquier falla de red o SMTP
            _anotar(
                sesion, candidato, transporte.canal,
                estado=EstadoAviso.FALLIDO, destino=destino,
                asunto=asunto or None, cuerpo=cuerpo, detalle=str(exc)[:500],
            )
            fallidos += 1
            continue

        # 🔴 Un transporte simulado deja el aviso `registrado`, nunca `enviado`: ese estado dice
        # que alguien lo recibió, y acá no lo recibió nadie.
        _anotar(
            sesion, candidato, transporte.canal,
            estado=EstadoAviso.REGISTRADO if simulado else EstadoAviso.ENVIADO,
            destino=destino, asunto=asunto or None, cuerpo=cuerpo,
            detalle=DETALLE_REGISTRADO if simulado else None,
        )
        if simulado:
            registrados += 1
        else:
            enviados += 1

    return Resumen(
        enviados=enviados, fallidos=fallidos, omitidos=omitidos, registrados=registrados
    )


class TransporteEmail:
    """El canal de mail, sobre el SMTP que ya tiene configurado la instancia.

    🔑 **No trae SMTP propio.** Usa `libraauth.email_sender`, que es el mismo que
    manda el mail de recuperación de contraseña, y la config sale de
    `resolver_smtp_config` — o sea de la pantalla «Configuración → Email» que ya
    existe. Un segundo lugar donde cargar un servidor de correo sería un lugar
    más donde el dueño puede cargarlo mal.
    """

    canal = CanalAviso.EMAIL
    simulado = False

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


class TransporteWhatsAppRegistro:
    """El canal de WhatsApp en modo registro: arma el mensaje y **no manda nada**.

    No hay proveedor de WhatsApp conectado a la familia (ADR-029): ni la API de Meta ni
    Evolution tienen cliente en el motor, y esta instancia no tiene credenciales para ninguno.
    Esto es la **costura**: cumple el mismo `Transporte` que el de mail, así que el día que
    exista el proveedor se cambia esta clase por la real en `construir_transportes` y nada más
    se toca —ni las reglas, ni los textos, ni el registro—.

    Lo que hace hoy es lo que sirve para dejarlo andando sin riesgo: el aviso queda en `avisos`
    con su destino, su texto y el estado `registrado`, que es lo que la pantalla muestra para
    revisar cómo quedarían los mensajes antes de prender el canal de verdad.
    """

    canal = CanalAviso.WHATSAPP
    simulado = True

    def __init__(self, modo: ModoWhatsapp) -> None:
        self._modo = modo

    def disponible(self) -> bool:
        return self._modo is ModoWhatsapp.REGISTRO

    def enviar(self, *, destino: str, asunto: str, cuerpo: str) -> None:
        # Nada que mandar. El registro lo escribe `despachar`, que es el mismo para todos.
        return None


def construir_transportes(sesion: Session, config_smtp) -> list[Transporte]:
    """Los transportes de esta corrida, según la configuración de la instancia.

    `config_smtp` es el callable que resuelve la config de correo (ver `TransporteEmail`). El
    de WhatsApp se arma siempre y decide por sí mismo si está disponible: así el cron no sabe
    qué canales existen y sumar uno es sumar una línea acá.
    """
    config = configuracion(sesion)
    return [TransporteEmail(config_smtp), TransporteWhatsAppRegistro(config.whatsapp)]
