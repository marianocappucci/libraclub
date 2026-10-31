"""Qué hay que avisarle al cliente, y cuándo. Cómo sale (y que no salga dos veces) es del motor.

Tres avisos, y son los que manda todo el rubro: **confirmación** cuando el turno
queda tomado, **recordatorio** unas horas antes, y **cancelación** cuando se
cae. Es la brecha número uno contra los competidores argentinos —Turnito,
Canchero, ATC y EasyCancha lo tienen— y hasta hoy este producto no mandaba nada.

## Qué es de quién (ADR-030)

Desde el 2026-10-28 **el envío no es de este módulo**: es de `libracore.avisos` (ADR-090 del motor). Lo que sigue
siendo de LibraClub, y por eso vive acá:

- **Qué corresponde avisar** (`pendientes`): las reglas, deducidas de las reservas en cada barrida.
- **Los textos** (`redactar`) y la plata (`pesos`).
- **Qué tipos salen** (`ConfiguracionDeAvisos`, la tabla `config_avisos`).

Y lo que pasó al motor: los proveedores (SMTP, Evolution, Registro, Apagado), `despachar` —que manda **una sola vez**
por `(canal, clave)` y reserva el aviso *antes* de salir a la red—, los reintentos con tope, el registro
(`avisos_envios`), el modo de WhatsApp y su configuración, `telefono_para_whatsapp`. `barrer` es el pegamento: le
pregunta a `pendientes` qué hay, y por cada candidato llama a `avisar` del motor con la `clave` del hecho (`clave_de`) y
un `redactar` por canal.

## Un aviso, un canal (addendum de ADR-030, 2026-10-28)

Un aviso sale por **un solo canal**: WhatsApp si el cliente tiene un teléfono válido y WhatsApp está disponible (modo
registro o Evolution); si no, mail. Si WhatsApp lo da por perdido (`rechazado`, `omitido` o agotó los intentos) cae a
mail **con la misma clave**, y lo que ya salió por un canal no sale por el otro aunque la configuración haya cambiado
entre dos corridas. La decisión y la comprobación entre canales son del motor (`libracore.avisos.avisar`, v1.204.0); acá
quedan los dos lugares donde LibraClub tiene que mirar **todos los canales a la vez**:

- `_sin_cerrar`: un aviso está resuelto si salió por cualquiera, o si el canal que le toca ya lo cerró (mismo recorrido
  que hace `avisar`, para no armar el texto de lo que ya salió ni contarlo como «repetido» en cada barrida).
- `_salio_la_confirmacion`: la regla «la cancelación exige que la confirmación haya salido» cuenta la confirmación que
  salió por **cualquiera** de los dos.

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

Acá el barrido **le pregunta a las reservas** qué corresponde mandar y usa `avisos_envios` sólo como registro de lo ya
intentado (`cerradas`). Un camino nuevo que confirme un turno queda cubierto sin tocar este archivo. El precio es una
consulta por regla en cada corrida del cron, con índice y acotada por fecha.

## Qué se suma en ADR-029

- **El aviso de seña por vencer** (`TipoAviso.SENA_POR_VENCER`): el turno que el portal retiene
  `VENCIMIENTO_PROVISORIA` mientras se paga se está por liberar. Como los otros, **se deduce**: la
  barrida le pregunta a `reservas` por las provisorias con pago pendiente que vencen en
  `VENTANA_DE_SENA`, sin cola.
- **La seña del mostrador** (addendum del 2026-10-28): la reserva `pendiente_pago` tomada por teléfono
  o en el local vence a las 24 h (`reservas.vencimiento_de_sena`) y el mismo `SENA_POR_VENCER` avisa
  `VENTANA_DE_SENA_DEL_MOSTRADOR` antes, con otro texto y sin pasar por MercadoPago.
- **WhatsApp**: el mismo texto de cada aviso, sin asunto y con el título en negrita. Lo manda el proveedor que
  diga la configuración del motor (apagado, registro o Evolution).

## Qué garantiza que no salga dos veces

`UNIQUE (canal, clave)` de `avisos_envios` —la clave es `reserva:{id}:{tipo}:{horas_antes|-}`— y que el motor
**reserva** la fila antes de mandar. No el `if` de Python: dos corridas del cron superpuestas pasan las dos por el
`if` antes de que cualquiera escriba.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from libracore.avisos import (
    CANALES_POR_DEFECTO,
    MAX_INTENTOS,
    Mensaje,
    Proveedor,
    Resumen,
    avisar,
    omitir,
)
from libracore.avisos import proveedores as proveedores_del_motor
from libracore.avisos.canales import destino_de
from libracore.db import avisos_envios as registro_del_motor
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models.avisos import ConfigAvisos
from app.models.enums import CanalAviso, EstadoReserva, TipoAviso
from app.models.reservas import EstadoPago, PagoDeReserva, Reserva
from app.servicios import cancelacion as servicio_cancelacion
from app.servicios import reservas as servicio_reservas
from app.tiempo import a_local, ahora, formatear_fecha_hora

logger = logging.getLogger(__name__)


#: Con cuánta anticipación se recuerda un turno, en horas. Dos avisos: uno el
#: día antes —a tiempo para cancelar y que el turno se revenda— y otro dos horas
#: antes, que es el que evita el no-show.
#:
#: Es una constante y no una config porque todavía no hay pantalla que la edite;
#: cuando la haya, sale de ahí y esto queda como default. Lo que **no** puede
#: pasar es que se vuelva parte del nombre del tipo de aviso: por eso la
#: anticipación es un campo aparte de la clave del aviso (ver `clave_de`).
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

#: Cuánto antes de que venza el plazo de la seña **del mostrador** (24 h, `reservas.PLAZO_DE_SENA`) se avisa.
#:
#: 🔑 **Tres horas**, no minutos como la del portal, y por qué no las mismas: el jugador de la
#: provisoria está con la tarjeta en la mano y le alcanzan 8 minutos; el que reservó por teléfono
#: tiene que ver el mensaje, buscar el alias y hacer la transferencia (o pasar por el local), y eso
#: no se hace en 8 minutos ni se hace si el mensaje llega con la cancha ya perdida.
#: - **Menos de 2 horas** deja sin margen a quien lee el aviso tarde (el mail se mira de a ratos);
#: - **más de 3** lo manda tan lejos del vencimiento que se lee como «ya veré» y se olvida: de las 24
#:   horas del plazo, el aviso sale a las ~21;
#: - el cron de 5 minutos agrega a lo sumo 5 más, y 3 horas lo absorbe sobradamente.
#: Sale una vez (`uq_avisos_reserva_tipo_canal`) y **sólo si el plazo era más largo que la ventana**:
#: a quien se le dio media hora porque el turno era sobre la hora no se le avisa a los dos minutos
#: de haber cortado el teléfono que «se libera en media hora».
VENTANA_DE_SENA_DEL_MOSTRADOR = timedelta(hours=3)


def clave_de(reserva_id: int, tipo: TipoAviso, horas_antes: int | None = None) -> str:
    """De qué hecho es un aviso: `reserva:41:recordatorio:24`, `reserva:41:confirmacion:-`.

    🔴 **Es lo que impide que un aviso salga dos veces** (`UNIQUE (canal, clave)` del motor), así que tiene que ser la
    misma cada vez que el barrido vuelve sobre el mismo hecho y distinta entre hechos: por eso la anticipación entra
    (el recordatorio de 24 h y el de 2 h son avisos distintos). **Sólo ids**: la clave aparece en los logs del motor,
    y el teléfono o el mail del cliente no pueden estar ahí.
    """
    return f"reserva:{reserva_id}:{tipo.value}:{'-' if horas_antes is None else horas_antes}"


@dataclass(frozen=True, slots=True)
class Candidato:
    """Un aviso que corresponde mandar ahora."""

    reserva: Reserva
    tipo: TipoAviso
    horas_antes: int | None
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

    @property
    def clave(self) -> str:
        return clave_de(self.reserva.id, self.tipo, self.horas_antes)


@dataclass(frozen=True, slots=True)
class ConfiguracionDeAvisos:
    """Qué tipos de aviso salen, ya leída. Sin fila en la base son los defaults (todos).

    🔴 **No dice por dónde salen**: el modo de WhatsApp (apagado, registro o Evolution) es del motor
    (`libracore.avisos.configuracion`, ADR-030). Tener acá un segundo `whatsapp` era tener dos fuentes de verdad.
    """

    confirmacion: bool = True
    recordatorio: bool = True
    cancelacion: bool = True
    sena_por_vencer: bool = True


def configuracion(sesion: Session) -> ConfiguracionDeAvisos:
    """La configuración de la instancia. **Sin fila, los defaults** (todos los tipos prendidos)."""
    fila = sesion.get(ConfigAvisos, 1)
    if fila is None:
        return ConfiguracionDeAvisos()
    return ConfiguracionDeAvisos(
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
    fila.avisar_confirmacion = nueva.confirmacion
    fila.avisar_recordatorio = nueva.recordatorio
    fila.avisar_cancelacion = nueva.cancelacion
    fila.avisar_sena_por_vencer = nueva.sena_por_vencer
    sesion.flush()
    return nueva


#: Los proveedores de una corrida: `{canal: Proveedor}` (lo que arma `construir_proveedores`), o uno solo, que es
#: «sólo ese canal» (un barrido de un canal, y los tests).
Proveedores = Proveedor | Mapping[str, Proveedor]


def _por_canal(proveedores: Proveedores) -> dict[str, Proveedor]:
    """Los proveedores como `{canal: Proveedor}`. Uno suelto vale por su canal."""
    if isinstance(proveedores, Mapping):
        return dict(proveedores)
    return {proveedores.canal: proveedores}


def _filas_por_canal(claves: list[str]) -> dict[str, dict[str, dict]]:
    """`{canal: {clave: fila de avisos_envios}}` de esas claves en **todos** los canales, estén disponibles o no.

    Lo que ya salió por un canal cuenta aunque hoy esté apagado."""
    return {canal: registro_del_motor.obtener_varios(canal, claves) for canal in CANALES_POR_DEFECTO}


def _perdido(fila: dict) -> bool:
    """Si por ese canal ese aviso **no va a salir nunca** y toca probar el otro (el mismo criterio que `avisar`)."""
    estado = fila["estado"]
    if estado in (registro_del_motor.ESTADO_RECHAZADO, registro_del_motor.ESTADO_OMITIDO):
        return True
    return estado == registro_del_motor.ESTADO_FALLIDO and fila["intentos"] >= MAX_INTENTOS


def _resuelto(por_canal: dict[str, dict[str, dict]], disponibles: dict[str, Proveedor], clave: str) -> bool:
    """Si ese aviso no tiene nada más que hacer: salió por algún canal, o el canal que le toca ya lo cerró.

    Recorre los canales como `avisar`: el primero **disponible** donde el aviso no está perdido decide. Sin fila ahí,
    falta mandarlo. Con fila, lo cierra todo menos lo que sigue vivo: un `fallido` con intentos, un `enviando`, y un
    `registrado` ante un proveedor real (lo anotado en modo prueba no llegó a nadie: regla del ADR-029, hoy en el
    motor). Si todos los canales disponibles lo dieron por perdido, no hay otro lado por donde salir y también está
    resuelto.
    """
    for filas in por_canal.values():
        fila = filas.get(clave)
        if fila is not None and fila["estado"] == registro_del_motor.ESTADO_ENVIADO:
            return True
    for canal in CANALES_POR_DEFECTO:
        proveedor = disponibles.get(canal)
        if proveedor is None:
            continue
        fila = por_canal[canal].get(clave)
        if fila is None:
            return False
        if _perdido(fila):
            continue
        return fila["estado"] == registro_del_motor.ESTADO_REGISTRADO and bool(proveedor.simulado)
    return True


def _disponibles(proveedores: dict[str, Proveedor]) -> dict[str, Proveedor]:
    return {canal: p for canal, p in proveedores.items() if p.disponible()}


def _sin_cerrar(
    proveedores: dict[str, Proveedor], reservas: list[Reserva], tipo: TipoAviso, horas: int | None
) -> list[Reserva]:
    """Las reservas cuyo aviso `tipo` todavía no está resuelto (ver `_resuelto`).

    Una consulta al motor por canal y por tanda de 500. Un `fallido` con intentos de sobra **no** lo cierra: es
    justamente el que hay que reintentar, y la reserva vuelve a salir como candidata. Lo mismo un `registrado` ante un
    proveedor real: lo que quedó anotado sin salir (WhatsApp en modo registro) es un mensaje que nadie recibió, y
    cuando se conecta Evolution tiene que mandarse, no darse por hecho.
    """
    if not reservas:
        return []
    claves = {r.id: clave_de(r.id, tipo, horas) for r in reservas}
    por_canal = _filas_por_canal(list(claves.values()))
    disponibles = _disponibles(proveedores)
    return [r for r in reservas if not _resuelto(por_canal, disponibles, claves[r.id])]


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


def _salio_la_confirmacion(proveedores: dict[str, Proveedor], reservas: list[Reserva]) -> list[Reserva]:
    """De estas reservas, las que tuvieron una confirmación que **salió** por alguno de los canales.

    Lo `enviado` por cualquiera —no importa si hoy ese canal está apagado—, y lo `registrado` sólo si el proveedor de
    ese canal es hoy uno simulado y disponible (si no, nunca llegó a nadie). Mira el estado y no si «está cerrado»: un
    `omitido` (sin mail) o un `rechazado` también cierran el tema, pero ahí al cliente **no** se le dijo nada.
    """
    if not reservas:
        return []
    claves = {r.id: clave_de(r.id, TipoAviso.CONFIRMACION) for r in reservas}
    por_canal = _filas_por_canal(list(claves.values()))

    def salio(clave: str) -> bool:
        for canal, filas in por_canal.items():
            estado = (filas.get(clave) or {}).get("estado")
            if estado == registro_del_motor.ESTADO_ENVIADO:
                return True
            proveedor = proveedores.get(canal)
            if (estado == registro_del_motor.ESTADO_REGISTRADO and proveedor is not None
                    and proveedor.simulado and proveedor.disponible()):
                return True
        return False

    return [r for r in reservas if salio(claves[r.id])]


def pendientes(
    sesion: Session,
    proveedores: Proveedores,
    momento: datetime | None = None,
    *,
    config: ConfiguracionDeAvisos | None = None,
) -> list[Candidato]:
    """Qué corresponde avisar en este instante, por el canal que le toque a cada uno (un aviso, un canal).

    No toca la base más que para leer. Separada del envío a propósito: es la
    parte que tiene las reglas, y así se puede probar sin mandar nada.

    `config` decide qué **tipos** se evalúan (sin ella, los de la instancia); `proveedores` dice qué canales hay y si
    son simulados, que cambia qué cuenta como «ya avisado» (ver `_sin_cerrar`). Un candidato lo es una sola vez por
    hecho, no una por canal.
    """
    proveedores = _por_canal(proveedores)
    momento = momento or ahora()
    config = config or configuracion(sesion)
    candidatos: list[Candidato] = []

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
            )
        ).all()
        candidatos += [
            Candidato(r, TipoAviso.CONFIRMACION, None)
            for r in _sin_cerrar(proveedores, list(confirmaciones), TipoAviso.CONFIRMACION, None)
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
                )
            ).all()
            candidatos += [
                Candidato(r, TipoAviso.RECORDATORIO, horas)
                for r in _sin_cerrar(proveedores, list(recordatorios), TipoAviso.RECORDATORIO, horas)
            ]

    # 3. Cancelación: se cayó un turno que el cliente creía tomado.
    if config.cancelacion:
        canceladas = sesion.scalars(
            select(Reserva).where(
                Reserva.estado == EstadoReserva.CANCELADA,
                Reserva.comienza_at > momento - VENTANA_DE_CANCELACION,
            )
        ).all()
        # 🔴 **Sólo se avisa la cancelación de algo que se confirmó y se avisó**: esta es la única puerta.
        #
        # Cubre los dos casos que llegan acá y que no son una cancelación de
        # verdad: la provisoria que venció sin pagarse —mandarle «se canceló
        # tu reserva» a quien nunca tuvo una es peor que no mandar nada: cree
        # que perdió un turno— y el **bloqueo que se quita**, que pasa a
        # `cancelada` sin cliente (`ck_reservas_cliente_segun_estado` exime a
        # las canceladas justamente por eso).
        avisadas = _salio_la_confirmacion(proveedores, list(canceladas))
        candidatos += [
            Candidato(r, TipoAviso.CANCELACION, None, sena=servicio_cancelacion.sena_para_el_aviso(sesion, r))
            for r in _sin_cerrar(proveedores, avisadas, TipoAviso.CANCELACION, None)
        ]

    # 4. Seña por vencer: el turno retenido mientras se paga se libera pronto. Son dos casos con el
    # mismo tipo de aviso y la misma configuración, y distinta ventana.
    if config.sena_por_vencer:
        candidatos += _senas_por_vencer(sesion, proveedores, momento)

    return candidatos


def _senas_por_vencer(sesion: Session, proveedores: dict[str, Proveedor], momento: datetime) -> list[Candidato]:
    """Las señas a punto de vencer: la provisoria del portal y la `pendiente_pago` del mostrador.

    1. **Portal** (`VENTANA_DE_SENA`, minutos).
    2. **Mostrador** (`VENTANA_DE_SENA_DEL_MOSTRADOR`, horas).

    🔑 **Las condiciones sobre el pago son la regla.** Una provisoria sin pago pendiente no es una seña
    que se esté pagando (la del mostrador, por ejemplo, no pasa por MercadoPago) y una con el pago
    aprobado ya no es provisoria. `vence_at > momento` evita avisar de un turno que ya se perdió: esa
    reserva la cancela `vencer_provisorias`, y mandarle «se libera en unos minutos» cuando ya se liberó
    es peor que no mandar nada.
    """
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
        )
    ).all()
    candidatos = [
        Candidato(r, TipoAviso.SENA_POR_VENCER, None, a_pagar=_monto_pendiente(sesion, r.id))
        for r in _sin_cerrar(proveedores, list(por_vencer), TipoAviso.SENA_POR_VENCER, None)
    ]

    del_mostrador = sesion.scalars(
        select(Reserva).where(
            Reserva.estado == EstadoReserva.PENDIENTE_PAGO,
            Reserva.vence_at.is_not(None),
            Reserva.vence_at > momento,
            Reserva.vence_at <= momento + VENTANA_DE_SENA_DEL_MOSTRADOR,
            # Se tomó **antes** de que se abriera la ventana: el mismo criterio que el recordatorio
            # (`created_at < comienza_at - ventana`). Sin esto, una seña con plazo corto (el turno
            # era sobre la hora) avisaría «se libera» a los segundos de haberla tomado.
            Reserva.created_at < Reserva.vence_at - VENTANA_DE_SENA_DEL_MOSTRADOR,
        )
    ).all()
    del_mostrador = _sin_cerrar(proveedores, list(del_mostrador), TipoAviso.SENA_POR_VENCER, None)
    if not del_mostrador:
        return candidatos

    # 🔴 Quien ya pagó no recibe «se libera tu turno». Lo cobrado en caja es la única señal: el
    # mostrador no pasa por MercadoPago. Si la caja no responde no se sabe quién pagó y no se avisa a
    # nadie en esta corrida (el aviso sale en la próxima, con tiempo de sobra: son 3 horas).
    ids = [r.id for r in del_mostrador]
    try:
        con_plata = servicio_reservas.con_plata_adentro(sesion, ids)
        cobrado = servicio_reservas.cobrado_en_caja(ids)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo consultar la caja: no se avisan las señas del mostrador")
        return candidatos
    for r in del_mostrador:
        if r.id in con_plata:
            continue
        falta = (
            max(Decimal(r.sena) - cobrado.get(r.id, Decimal("0")), Decimal("0")) if r.sena else None
        )
        candidatos.append(Candidato(r, TipoAviso.SENA_POR_VENCER, None, a_pagar=falta or None))
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

    if candidato.tipo is TipoAviso.SENA_POR_VENCER and reserva.estado is EstadoReserva.PENDIENTE_PAGO:
        # La seña de una reserva tomada por teléfono o en el local: el plazo es de un día, así que
        # lleva fecha, y no hay «Mis reservas» donde completarla: se paga y se avisa al complejo.
        hasta = formatear_fecha_hora(reserva.vence_at)
        asunto = f"Tu turno se libera el {hasta}: {donde}, {cuando}"
        monto = f"Seña a pagar: {pesos(candidato.a_pagar)}\n" if candidato.a_pagar else ""
        cuerpo = (
            f"{hola}\n\n"
            f"Tu turno está reservado hasta el {hasta} esperando la seña.\n\n"
            f"Cancha: {donde}\n"
            f"Cuándo: {cuando}\n"
            f"{monto}"
            f"\nSi la seña no llega a tiempo, el turno se libera y lo puede tomar otra persona. "
            f"Para conservarlo, pagala antes de esa hora y avisanos: respondé este {medio}."
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


def barrer(
    sesion: Session,
    proveedores: Proveedores,
    momento: datetime | None = None,
    *,
    config: ConfiguracionDeAvisos | None = None,
) -> Resumen:
    """Manda todo lo que corresponde, **un aviso por un solo canal**. Devuelve el `Resumen` del motor.

    `proveedores` es `{canal: Proveedor}` (`construir_proveedores`); uno suelto vale «sólo por ese canal». Por cada
    candidato (`pendientes`) llama a `avisar` del motor: WhatsApp si el cliente tiene un teléfono válido y WhatsApp está
    disponible, si no mail, y mail también si WhatsApp lo da por perdido. La clave es la misma para los dos canales
    (`clave_de`). El `Resumen` cuenta lo que pasó en cada canal tocado: un WhatsApp `rechazado` que cae a mail suma un
    rechazado y un enviado.

    **No escribe en `sesion`**: sólo lee las reservas. Lo que se anota (el aviso reservado, enviado, fallido u
    omitido) lo escribe el motor en `avisos_envios`, y cada paso se confirma solo, **antes** de salir a la red: es lo
    que cierra la ventana que tenía el barrido anterior (ADR-015), que anotaba *después* de mandar y, con dos corridas
    del cron superpuestas, mandaba las dos.

    ⚠️ Queda una sola ventana, la que documenta el motor (ADR-090): si el proceso muere *después* de que el proveedor
    aceptó el aviso y *antes* de anotarlo, a los 10 minutos se lo da por abandonado y se reintenta, y el cliente lo
    recibe dos veces. Para un recordatorio de turno, duplicado es mejor que faltante.

    Un canal no disponible (SMTP sin cargar, WhatsApp apagado) no hace nada: ni arma textos ni anota omitidos por una
    configuración que a lo mejor se completa mañana. Sin ningún canal disponible, no hace nada.
    """
    proveedores = _por_canal(proveedores)
    disponibles = _disponibles(proveedores)
    if not disponibles:
        return Resumen()

    resumen = Resumen()
    for candidato in pendientes(sesion, proveedores, momento, config=config):
        cliente = candidato.reserva.cliente
        contacto = {
            "email": (cliente.email if cliente else "") or "",
            "telefono": (cliente.telefono if cliente else "") or "",
        }
        tipo = candidato.tipo.value

        if cliente is not None and not cliente.acepta_avisos:
            # Se anota en cada canal disponible: con uno solo, el otro lo volvería a plantear en cada barrida.
            for canal in disponibles:
                resumen = resumen.sumar(omitir(
                    canal, candidato.clave, tipo=tipo, destino=destino_de(canal, contacto),
                    motivo="El cliente pidió no recibir avisos.",
                ))
            continue

        def redactar_por(canal: str, candidato: Candidato = candidato) -> Mensaje:
            asunto, cuerpo = redactar(candidato, CanalAviso(canal))
            return Mensaje(destino="", asunto=asunto, cuerpo=cuerpo)  # el destino lo pone `avisar`

        for envio in avisar(proveedores, contacto, redactar_por, clave=candidato.clave, tipo=tipo):
            resumen = resumen.sumar(envio)
    return resumen


def construir_proveedores(config_smtp, *, transporte=None) -> dict[str, Proveedor]:
    """Los proveedores de esta corrida, `{canal: Proveedor}` con uno por canal, según la configuración del motor.

    `config_smtp` es el callable que resuelve la config de correo (`app.smtp.smtp_config`): un callable y no el valor,
    porque la config vive en la base y la pantalla la edita mientras el proceso corre. El de WhatsApp lo elige el motor
    (apagado, registro o Evolution) y decide por sí mismo si está disponible: así el cron no sabe qué canales existen y
    sumar uno es sumar una línea acá.

    `transporte` es para los tests: un `httpx.MockTransport` por el que sale Evolution, para que nada real salga.
    """
    return dict(proveedores_del_motor(config_smtp, transporte=transporte))
