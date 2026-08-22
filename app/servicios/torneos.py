"""Torneos: inscripción, sorteo, programación y resultados.

El armado del cuadro en sí —quién juega contra quién, quién descansa, quién
avanza a dónde— vive en `servicios/fixture.py`, que no toca la base. Acá está lo
que sí la toca: sortear, ocupar canchas y cargar resultados.

La regla que ordena el módulo: **un torneo sorteado no se re-sortea**. Todo lo
que cambia después —el horario de un partido, un resultado, una corrección— es
una operación sobre el fixture existente, nunca una regeneración. Regenerar
borraría partidos ya jugados y no habría forma de darse cuenta.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import EstadoReserva, EstadoTorneo, EtapaTorneo, FormatoTorneo
from app.models.maestros import Cancha
from app.models.torneos import (
    Competidor,
    IntegranteDeCompetidor,
    ParcialDePartido,
    PartidoDeTorneo,
    Torneo,
    Zona,
)
from app.servicios import fixture
from app.servicios import reservas as servicio_reservas

#: Puntos de la tabla. 3/1/0, que es lo que usa cualquier torneo de fútbol de
#: barrio. En pádel no hay empates, así que la columna de empatados queda en cero
#: y ordenar por puntos es lo mismo que ordenar por partidos ganados.
PUNTOS_POR_GANAR = 3
PUNTOS_POR_EMPATAR = 1

#: Los nombres de las zonas, en orden. Con más de 26 zonas —que no va a pasar—
#: se sigue con AA, AB…
_LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class TorneoInvalido(ValueError):
    """El pedido está mal formado: sin competidores, un resultado imposible."""


class EstadoDelTorneo(Exception):
    """La operación no corresponde en el punto en que está el torneo.

    Se separa de `TorneoInvalido` porque el router las traduce distinto: esto es
    un 409 —el pedido está bien, el recurso no lo admite ahora— y aquello un 422.
    """


# ── Competidores ────────────────────────────────────────────────────────────


def inscribir(
    sesion: Session,
    torneo: Torneo,
    *,
    nombre: str,
    siembra: int | None = None,
    integrantes: list[tuple[str, str | None]] | None = None,
) -> Competidor:
    """Anota un competidor. Sólo antes del sorteo.

    🔴 **Después del sorteo no se inscribe.** El cuadro ya está armado y el
    inscripto nuevo no tendría dónde entrar; peor, en una liga habría que
    generarle los partidos contra todos los que ya jugaron. Que falle acá es
    mejor que un competidor con cero partidos arriba de la tabla.
    """
    if torneo.estado is not EstadoTorneo.ARMADO:
        raise EstadoDelTorneo(
            "El torneo ya está sorteado: no se pueden agregar competidores."
        )
    if not nombre.strip():
        raise TorneoInvalido("El competidor necesita un nombre.")

    competidor = Competidor(
        torneo_id=torneo.id, nombre=nombre.strip(), siembra=siembra
    )
    competidor.integrantes = [
        IntegranteDeCompetidor(nombre=n.strip(), telefono=(t or None))
        for n, t in (integrantes or [])
        if n.strip()
    ]
    sesion.add(competidor)
    sesion.flush()
    return competidor


def bajar_competidor(sesion: Session, competidor: Competidor) -> None:
    """Borra un inscripto. Sólo antes del sorteo, por el mismo motivo."""
    torneo = sesion.get(Torneo, competidor.torneo_id)
    if torneo is not None and torneo.estado is not EstadoTorneo.ARMADO:
        raise EstadoDelTorneo(
            "El torneo ya está sorteado: dar de baja a un competidor dejaría "
            "partidos sin jugador. Cancelá el torneo o cargá el partido como "
            "ganado por el rival."
        )
    sesion.delete(competidor)
    sesion.flush()


# ── Sorteo ──────────────────────────────────────────────────────────────────


def sortear(sesion: Session, torneo: Torneo, semilla: int | None = None) -> None:
    """Reparte el bombo y arma el fixture. **Una sola vez por torneo.**

    🔑 **La semilla se guarda.** Con ese número y la lista de inscriptos el
    sorteo se reproduce entero: es lo único que convierte "salió así" en algo
    verificable cuando alguien pregunta por qué le tocó el primero en la primera
    ronda. Se puede pasar a mano —para repetir un sorteo hecho frente a la
    gente— y si no viene se elige una.
    """
    if torneo.estado is not EstadoTorneo.ARMADO:
        raise EstadoDelTorneo("Este torneo ya fue sorteado.")

    competidores = list(
        sesion.scalars(
            select(Competidor)
            .where(Competidor.torneo_id == torneo.id)
            .order_by(Competidor.id)
        ).all()
    )
    if len(competidores) < 2:
        raise TorneoInvalido("Un torneo necesita al menos dos competidores.")

    torneo.semilla = semilla if semilla is not None else random.randrange(1, 2**31)
    orden = _orden_del_bombo(competidores, random.Random(torneo.semilla))

    if torneo.formato is FormatoTorneo.ELIMINACION:
        _crear_llaves(sesion, torneo, orden)
    elif torneo.formato is FormatoTorneo.LIGA:
        # Una liga es grupos sin zonas: sus partidos van con `zona_id` en NULL.
        _crear_grupo(sesion, torneo, None, orden)
    else:
        _sortear_zonas(sesion, torneo, orden)

    torneo.estado = EstadoTorneo.SORTEADO
    sesion.flush()


def _orden_del_bombo(
    competidores: list[Competidor], azar: random.Random
) -> list[Competidor]:
    """Las cabezas de serie por su número, y el resto mezclado detrás.

    🔴 **Las sembradas no entran al bombo.** Sortearlas junto al resto haría que
    la siembra no signifique nada: el sentido de ser cabeza de serie es caer en
    una posición del cuadro que no te cruce con la otra cabeza hasta el final.
    """
    sembrados = sorted(
        (c for c in competidores if c.siembra is not None), key=lambda c: c.siembra or 0
    )
    resto = [c for c in competidores if c.siembra is None]
    azar.shuffle(resto)
    return [*sembrados, *resto]


def _sortear_zonas(sesion: Session, torneo: Torneo, orden: list[Competidor]) -> None:
    cantidad = torneo.cantidad_zonas or 0
    if len(orden) < cantidad * 2:
        raise TorneoInvalido(
            f"Con {len(orden)} competidores no alcanza para {cantidad} zonas: "
            "cada zona necesita al menos dos."
        )

    zonas = []
    for numero in range(cantidad):
        zona = Zona(torneo_id=torneo.id, nombre=f"Zona {_letra(numero)}")
        sesion.add(zona)
        zonas.append(zona)
    sesion.flush()

    for zona, integrantes in zip(zonas, _repartir(orden, cantidad), strict=True):
        for competidor in integrantes:
            competidor.zona_id = zona.id
        _crear_grupo(sesion, torneo, zona, integrantes)


def _letra(numero: int) -> str:
    if numero < len(_LETRAS):
        return _LETRAS[numero]
    alto, bajo = divmod(numero, len(_LETRAS))
    return f"{_LETRAS[alto - 1]}{_LETRAS[bajo]}"


def _repartir(orden: list[Competidor], zonas: int) -> list[list[Competidor]]:
    """Reparte en serpentina: 1→A, 2→B, 3→C, 4→C, 5→B, 6→A, 7→A…

    🔑 **Serpentina y no módulo.** Repartiendo con `i % zonas`, las cuatro
    primeras siembras caen una en cada zona pero la 5ª vuelve a la A, la 6ª a la
    B… y la zona A termina con la 1ª y la 5ª mientras la D tiene la 4ª y la 8ª.
    La serpentina compensa: la zona que recibe la mejor recibe también la peor de
    la vuelta siguiente.
    """
    grupos: list[list[Competidor]] = [[] for _ in range(zonas)]
    for indice, competidor in enumerate(orden):
        vuelta, posicion = divmod(indice, zonas)
        grupos[posicion if vuelta % 2 == 0 else zonas - 1 - posicion].append(competidor)
    return grupos


def _crear_grupo(
    sesion: Session, torneo: Torneo, zona: Zona | None, integrantes: list[Competidor]
) -> None:
    """Todos contra todos dentro de un grupo, por fecha."""
    if len(integrantes) < 2:
        raise TorneoInvalido("Una zona necesita al menos dos competidores.")
    for numero, cruces in enumerate(fixture.ronda_robin(len(integrantes)), start=1):
        for orden, (a, b) in enumerate(cruces):
            sesion.add(
                PartidoDeTorneo(
                    torneo_id=torneo.id,
                    etapa=EtapaTorneo.GRUPOS,
                    zona_id=zona.id if zona is not None else None,
                    ronda=numero,
                    orden=orden,
                    competidor_a_id=integrantes[a].id,
                    competidor_b_id=integrantes[b].id,
                )
            )
    sesion.flush()


def _crear_llaves(sesion: Session, torneo: Torneo, orden: list[Competidor]) -> None:
    """Materializa el cuadro de eliminación y enlaza los avances."""
    cruces = fixture.llaves(len(orden))
    creados: dict[tuple[int, int], PartidoDeTorneo] = {}
    for cruce in cruces:
        partido = PartidoDeTorneo(
            torneo_id=torneo.id,
            etapa=EtapaTorneo.LLAVES,
            ronda=cruce.ronda,
            orden=cruce.orden,
            competidor_a_id=orden[cruce.a].id if cruce.a is not None else None,
            competidor_b_id=orden[cruce.b].id if cruce.b is not None else None,
        )
        sesion.add(partido)
        creados[(cruce.ronda, cruce.orden)] = partido
    # 🔴 El `flush` va acá y no al final: `avanza_a_id` es una FK contra esta
    # misma tabla, así que los ids tienen que existir antes de escribirlos.
    sesion.flush()

    for cruce in cruces:
        if cruce.avanza_a is None:
            continue
        partido = creados[(cruce.ronda, cruce.orden)]
        partido.avanza_a_id = creados[cruce.avanza_a].id
        partido.avanza_a_slot = cruce.avanza_a_slot
    sesion.flush()


def generar_playoff(sesion: Session, torneo: Torneo) -> None:
    """Arma las llaves con los que clasificaron de cada zona.

    Se hace en un paso aparte y no al sortear porque **hasta que no termina la
    fase de grupos no se sabe quién juega**. Es también el momento en que el
    encargado puede mirar las tablas antes de largar el playoff.
    """
    if torneo.formato is not FormatoTorneo.ZONAS:
        raise EstadoDelTorneo("Sólo un torneo por zonas tiene playoff.")
    if torneo.estado is not EstadoTorneo.SORTEADO:
        raise EstadoDelTorneo("El torneo no está en condiciones de largar el playoff.")

    partidos = partidos_de(sesion, torneo)
    if any(p.etapa is EtapaTorneo.LLAVES for p in partidos):
        raise EstadoDelTorneo("El playoff de este torneo ya está armado.")
    faltan = [p for p in partidos if not p.finalizado]
    if faltan:
        raise EstadoDelTorneo(
            f"Faltan {len(faltan)} partidos de la fase de grupos por jugar."
        )

    clasifican = torneo.clasifican_por_zona or 1
    tablas = tabla_de_posiciones(sesion, torneo)
    por_zona = [
        [fila.competidor_id for fila in tabla.filas[:clasifican]] for tabla in tablas
    ]
    if any(len(z) < clasifican for z in por_zona):
        raise TorneoInvalido(
            "Alguna zona tiene menos competidores que los que clasifican."
        )

    ids = fixture.orden_de_clasificados(por_zona)
    por_id = {c.id: c for c in competidores_de(sesion, torneo)}
    _crear_llaves(sesion, torneo, [por_id[i] for i in ids])


# ── Programación: cancha y horario ──────────────────────────────────────────


def programar(
    sesion: Session,
    partido: PartidoDeTorneo,
    *,
    cancha_id: int,
    comienza_at: datetime,
    duracion_min: int | None = None,
) -> PartidoDeTorneo:
    """Le da cancha y horario a un partido, ocupando la cancha de verdad.

    🔑 **Lo que ocupa la cancha es un bloqueo en `reservas`, no este partido.**
    Es la misma decisión que toma una cancha fija con sus ocurrencias: el
    constraint de exclusión sólo mira su propia tabla, así que un partido de
    torneo guardado sólo acá no impediría que el mostrador alquile esa cancha a
    esa hora — y el día del torneo habría dos grupos en la puerta.

    Reprogramar libera el bloqueo anterior y toma el nuevo. 🔴 Las dos cosas van
    adentro del **mismo SAVEPOINT**: si el horario nuevo está ocupado, se
    deshace también la liberación del viejo. Sin eso, un intento fallido de mover
    un partido lo dejaría sin cancha —había una y ahora no hay ninguna— que es
    el peor resultado posible de una operación que falló.
    """
    torneo = sesion.get(Torneo, partido.torneo_id)
    if torneo is None:
        raise TorneoInvalido("No existe el torneo de ese partido.")
    if torneo.estado is EstadoTorneo.CANCELADO:
        raise EstadoDelTorneo("El torneo está cancelado.")
    if partido.finalizado:
        raise EstadoDelTorneo("Ese partido ya se jugó.")

    cancha = sesion.get(Cancha, cancha_id)
    if cancha is None:
        raise TorneoInvalido("No existe esa cancha.")
    minutos = duracion_min or cancha.duracion_turno_min

    punto = sesion.begin_nested()
    try:
        anterior = partido.reserva_id
        if anterior is not None:
            # 🔴 Se suelta la referencia ANTES de cancelar: `uq_partidos_reserva`
            # es único, y crear el bloqueo nuevo antes de soltar el viejo dejaría
            # al partido apuntando a dos.
            partido.reserva_id = None
            sesion.flush()
            servicio_reservas.cambiar_estado(
                sesion, anterior, EstadoReserva.CANCELADA,
                motivo=f"Reprogramado — {torneo.nombre}",
            )
        bloqueo = servicio_reservas.crear_bloqueo(
            sesion,
            cancha_id=cancha_id,
            comienza_at=comienza_at,
            termina_at=comienza_at + timedelta(minutes=minutos),
            motivo=_motivo(sesion, torneo, partido),
        )
        partido.reserva_id = bloqueo.id
        sesion.flush()
    except Exception:
        punto.rollback()
        # Tras deshacer el savepoint, lo que tiene el objeto en memoria puede no
        # ser lo que quedó en la base. Se lo obliga a releer.
        sesion.expire(partido)
        raise
    punto.commit()
    return partido


def desprogramar(sesion: Session, partido: PartidoDeTorneo) -> PartidoDeTorneo:
    """Le saca la cancha a un partido y libera el horario."""
    if partido.reserva_id is None:
        return partido
    reserva_id = partido.reserva_id
    partido.reserva_id = None
    sesion.flush()
    servicio_reservas.cambiar_estado(
        sesion, reserva_id, EstadoReserva.CANCELADA, motivo="Partido sin programar"
    )
    return partido


def _motivo(sesion: Session, torneo: Torneo, partido: PartidoDeTorneo) -> str:
    """El texto que ve el mostrador en la grilla, sobre el casillero ocupado.

    Nombra el torneo, la instancia y los dos competidores: quien mira la agenda
    tiene que poder decir qué es ese bloque sin abrir la pantalla de torneos.
    """
    nombres = {c.id: c.nombre for c in competidores_de(sesion, torneo)}
    a = nombres.get(partido.competidor_a_id or 0, "a definir")
    b = nombres.get(partido.competidor_b_id or 0, "a definir")
    return f"{torneo.nombre} — {instancia(sesion, torneo, partido)}: {a} vs {b}"[:200]


def rondas_de_llaves(partidos: list[PartidoDeTorneo]) -> int:
    """Cuántas rondas tiene el cuadro. Es la ronda de la final.

    Se calcula sobre la lista ya cargada y no con una consulta propia: quien
    dibuja el fixture ya tiene todos los partidos en la mano, y nombrar 63
    instancias no puede costar 63 consultas.
    """
    return max((p.ronda for p in partidos if p.etapa is EtapaTorneo.LLAVES), default=0)


def instancia(
    sesion: Session,
    torneo: Torneo,
    partido: PartidoDeTorneo,
    rondas: int | None = None,
) -> str:
    """«Fecha 3», «Zona A · Fecha 2», «Semifinal»."""
    if partido.etapa is EtapaTorneo.LLAVES:
        total = rondas or rondas_de_llaves(partidos_de(sesion, torneo)) or partido.ronda
        return fixture.nombre_de_ronda(partido.ronda, total)
    if partido.zona_id is None:
        return f"Fecha {partido.ronda}"
    zona = sesion.get(Zona, partido.zona_id)
    return f"{zona.nombre if zona else 'Zona'} · Fecha {partido.ronda}"


# ── Resultados ──────────────────────────────────────────────────────────────


def cargar_resultado(
    sesion: Session, partido: PartidoDeTorneo, parciales: list[tuple[int, int]]
) -> PartidoDeTorneo:
    """Carga el resultado, define el ganador y lo pasa a la ronda siguiente.

    Vuelve a cargarse encima para corregir: los parciales se reemplazan enteros.
    """
    torneo = sesion.get(Torneo, partido.torneo_id)
    if torneo is None:
        raise TorneoInvalido("No existe el torneo de ese partido.")
    if torneo.estado is EstadoTorneo.CANCELADO:
        raise EstadoDelTorneo("El torneo está cancelado.")
    if partido.competidor_a_id is None or partido.competidor_b_id is None:
        raise EstadoDelTorneo(
            "Todavía no se sabe quiénes juegan este partido: falta que se "
            "definan los de la ronda anterior."
        )

    ganador_id = _resolver_ganador(torneo, partido, parciales)
    _propagar(sesion, partido, ganador_id)

    # 🔴 **Vaciar y flushear ANTES de cargar los nuevos.** Reemplazar la lista
    # de una sola vez parece equivalente y no lo es: SQLAlchemy emite todos los
    # INSERT de una tabla antes que sus DELETE, así que al **corregir** un
    # resultado el parcial nuevo número 1 choca con el viejo número 1 y sale un
    # `uq_parciales_partido_numero` violado. Se ve sólo al corregir —cargar por
    # primera vez anda perfecto—, que es la mitad de los casos que no se prueban.
    partido.parciales = []
    sesion.flush()
    partido.parciales = [
        ParcialDePartido(numero=numero, puntos_a=a, puntos_b=b)
        for numero, (a, b) in enumerate(parciales, start=1)
    ]
    partido.ganador_id = ganador_id
    partido.finalizado = True
    sesion.flush()

    _cerrar_si_termino(sesion, torneo)
    return partido


def _resolver_ganador(
    torneo: Torneo, partido: PartidoDeTorneo, parciales: list[tuple[int, int]]
) -> int | None:
    """Valida el resultado y devuelve el ganador. `None` = empate.

    🔑 **Un solo camino para los tres deportes.** `sets_para_ganar` vale 1 en
    fútbol —un partido es un parcial, el resultado— y 2 en un pádel al mejor de
    tres. Todo lo demás sale de ahí sin ninguna rama por deporte.
    """
    para_ganar = torneo.sets_para_ganar
    if not parciales:
        raise TorneoInvalido("Falta el resultado.")
    if para_ganar == 1 and len(parciales) != 1:
        # Fútbol: un partido es UN resultado. El tope genérico de abajo también
        # lo atajaría, pero con un mensaje que habla de parciales — una palabra
        # que en fútbol no significa nada para el que la lee.
        raise TorneoInvalido("Este torneo se juega a un solo resultado.")
    if len(parciales) > para_ganar * 2 - 1:
        raise TorneoInvalido(
            f"Un partido al mejor de {para_ganar * 2 - 1} no puede tener "
            f"{len(parciales)} parciales."
        )

    gana_a = sum(1 for a, b in parciales if a > b)
    gana_b = sum(1 for a, b in parciales if b > a)
    empatados = len(parciales) - gana_a - gana_b

    if para_ganar > 1 and empatados:
        # Un set de pádel o de tenis no termina empatado. Aceptarlo dejaría un
        # partido sin forma de definir el ganador.
        raise TorneoInvalido("Un set no puede terminar empatado.")

    if gana_a == gana_b:
        if partido.etapa is EtapaTorneo.LLAVES:
            raise TorneoInvalido(
                "Una llave no puede terminar empatada: alguien tiene que pasar."
            )
        return None

    ganador_es_a = gana_a > gana_b
    if max(gana_a, gana_b) != para_ganar:
        raise TorneoInvalido(
            f"El ganador tiene que llevarse {para_ganar} parciales, y este "
            f"resultado da {max(gana_a, gana_b)}."
        )
    # 🔑 El último parcial lo gana el que gana el partido: nadie sigue jugando
    # después de definirlo. Sin este chequeo entra un 6-4 / 4-6 / 4-6 cargado
    # como victoria de A, que es un error de tipeo de lo más común.
    ultimo_a, ultimo_b = parciales[-1]
    if (ultimo_a > ultimo_b) is not ganador_es_a:
        raise TorneoInvalido(
            "El último parcial lo tiene que ganar el que gana el partido: "
            "revisá el orden."
        )
    return partido.competidor_a_id if ganador_es_a else partido.competidor_b_id


def _propagar(
    sesion: Session, partido: PartidoDeTorneo, ganador_id: int | None
) -> None:
    """Escribe al ganador en el slot que este partido alimenta.

    🔴 **Si el que pasa cambia y el partido siguiente ya se jugó, no se toca.**
    Corregir el resultado de unos cuartos cuando la semifinal ya está cargada
    dejaría a un competidor jugando un partido al que nunca clasificó, y el
    cuadro quedaría contando una historia que no pasó. Se rechaza y se le pide a
    quien corrige que borre el resultado de abajo primero — que es una decisión
    con consecuencias y tiene que ser deliberada.

    Corregir el **marcador** sin cambiar quién ganó sí se permite, que es el caso
    frecuente: alguien cargó 6-3 donde iba 6-2.
    """
    if partido.avanza_a_id is None:
        return
    siguiente = sesion.get(PartidoDeTorneo, partido.avanza_a_id)
    if siguiente is None:
        return
    campo = f"competidor_{partido.avanza_a_slot}_id"
    if getattr(siguiente, campo) == ganador_id:
        return
    if siguiente.finalizado:
        raise EstadoDelTorneo(
            "Cambiar el ganador de este partido obligaría a rehacer el "
            "siguiente, que ya tiene resultado. Borrá ese resultado primero."
        )
    setattr(siguiente, campo, ganador_id)


def borrar_resultado(
    sesion: Session, partido: PartidoDeTorneo
) -> PartidoDeTorneo:
    """Deja el partido como no jugado, y saca al ganador de la ronda siguiente."""
    if not partido.finalizado:
        return partido
    _propagar(sesion, partido, None)
    partido.parciales = []
    partido.ganador_id = None
    partido.finalizado = False
    torneo = sesion.get(Torneo, partido.torneo_id)
    if torneo is not None and torneo.estado is EstadoTorneo.FINALIZADO:
        # Vuelve a estar en juego: el campeón deja de estar definido.
        torneo.estado = EstadoTorneo.SORTEADO
    sesion.flush()
    return partido


def _cerrar_si_termino(sesion: Session, torneo: Torneo) -> None:
    partidos = partidos_de(sesion, torneo)
    if not partidos or any(not p.finalizado for p in partidos):
        return
    if torneo.formato is FormatoTorneo.ZONAS and not any(
        p.etapa is EtapaTorneo.LLAVES for p in partidos
    ):
        # Terminaron los grupos pero falta el playoff: el torneo no terminó.
        return
    torneo.estado = EstadoTorneo.FINALIZADO
    sesion.flush()


def campeon(sesion: Session, torneo: Torneo) -> Competidor | None:
    """Quién ganó, o `None` si todavía no se sabe.

    En un torneo con llaves es el ganador de la final —el único partido sin
    `avanza_a`—. En una liga es el primero de la tabla, y sólo cuando ya se
    jugó todo: el primero de una tabla a mitad de campeonato no es campeón.
    """
    if torneo.estado is not EstadoTorneo.FINALIZADO:
        return None
    llaves = [p for p in partidos_de(sesion, torneo) if p.etapa is EtapaTorneo.LLAVES]
    if llaves:
        final = max(llaves, key=lambda p: p.ronda)
        return sesion.get(Competidor, final.ganador_id) if final.ganador_id else None
    tablas = tabla_de_posiciones(sesion, torneo)
    if not tablas or not tablas[0].filas:
        return None
    return sesion.get(Competidor, tablas[0].filas[0].competidor_id)


# ── Tabla de posiciones ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FilaDePosiciones:
    competidor_id: int
    nombre: str
    jugados: int
    ganados: int
    empatados: int
    perdidos: int
    #: La suma de los parciales. En fútbol son goles; en pádel y tenis, games.
    #: Es el desempate estándar en los dos casos.
    a_favor: int
    en_contra: int
    diferencia: int
    puntos: int


@dataclass(frozen=True, slots=True)
class TablaDeZona:
    zona_id: int | None
    #: `None` en una liga, que no tiene zonas.
    nombre: str | None
    filas: list[FilaDePosiciones]


def tabla_de_posiciones(sesion: Session, torneo: Torneo) -> list[TablaDeZona]:
    """Las posiciones, una tabla por zona. Una liga devuelve una sola.

    Incluye a los que todavía no jugaron: una tabla que esconde al que no debutó
    hace que el encargado crea que se olvidó de inscribirlo.
    """
    competidores = competidores_de(sesion, torneo)
    partidos = [
        p
        for p in partidos_de(sesion, torneo)
        if p.etapa is EtapaTorneo.GRUPOS and p.finalizado
    ]

    acumulado: dict[int, dict[str, int]] = {
        c.id: dict(jugados=0, ganados=0, empatados=0, perdidos=0, a_favor=0, en_contra=0)
        for c in competidores
    }
    for partido in partidos:
        a, b = partido.competidor_a_id, partido.competidor_b_id
        if a is None or b is None or a not in acumulado or b not in acumulado:
            continue
        favor_a = sum(p.puntos_a for p in partido.parciales)
        favor_b = sum(p.puntos_b for p in partido.parciales)
        lados = ((a, favor_a, favor_b), (b, favor_b, favor_a))
        for propio, favor, contra in lados:
            fila = acumulado[propio]
            fila["jugados"] += 1
            fila["a_favor"] += favor
            fila["en_contra"] += contra
            if partido.ganador_id is None:
                fila["empatados"] += 1
            elif partido.ganador_id == propio:
                fila["ganados"] += 1
            else:
                fila["perdidos"] += 1

    por_zona: dict[int | None, list[Competidor]] = {}
    for competidor in competidores:
        por_zona.setdefault(competidor.zona_id, []).append(competidor)

    nombres = {z.id: z.nombre for z in sesion.scalars(
        select(Zona).where(Zona.torneo_id == torneo.id)
    ).all()}

    tablas = []
    for zona_id in sorted(por_zona, key=lambda z: (z is not None, z or 0)):
        filas = []
        for competidor in por_zona[zona_id]:
            datos = acumulado[competidor.id]
            filas.append(
                FilaDePosiciones(
                    competidor_id=competidor.id,
                    nombre=competidor.nombre,
                    **datos,
                    diferencia=datos["a_favor"] - datos["en_contra"],
                    puntos=(
                        datos["ganados"] * PUNTOS_POR_GANAR
                        + datos["empatados"] * PUNTOS_POR_EMPATAR
                    ),
                )
            )
        # Puntos, después diferencia, después lo hecho a favor, y por último el
        # nombre para que el orden sea estable: sin ese último criterio, dos
        # competidores con todo igual se intercambian entre consultas y la
        # pantalla parece cambiar sola.
        filas.sort(key=lambda f: (-f.puntos, -f.diferencia, -f.a_favor, f.nombre))
        tablas.append(
            TablaDeZona(zona_id=zona_id, nombre=nombres.get(zona_id), filas=filas)
        )
    return tablas


# ── Cancelación ─────────────────────────────────────────────────────────────


def cancelar(sesion: Session, torneo: Torneo) -> int:
    """Cancela el torneo y **libera todas las canchas que tenía tomadas**.

    🔴 Sin esto, cancelar un torneo dejaría los bloqueos puestos: las canchas del
    fin de semana seguirían ocupadas por un torneo que no se juega, y nadie
    tendría cómo saber por qué. Devuelve cuántos bloqueos se liberaron.
    """
    if torneo.estado is EstadoTorneo.CANCELADO:
        return 0
    liberados = 0
    for partido in partidos_de(sesion, torneo):
        if partido.reserva_id is not None:
            desprogramar(sesion, partido)
            liberados += 1
    torneo.estado = EstadoTorneo.CANCELADO
    sesion.flush()
    return liberados


# ── Consultas compartidas con el router ─────────────────────────────────────


def competidores_de(sesion: Session, torneo: Torneo) -> list[Competidor]:
    """Los inscriptos, por nombre."""
    return list(
        sesion.scalars(
            select(Competidor)
            .where(Competidor.torneo_id == torneo.id)
            .order_by(Competidor.nombre)
        ).all()
    )


def partidos_de(sesion: Session, torneo: Torneo) -> list[PartidoDeTorneo]:
    """El fixture entero, agrupado por etapa y zona.

    La zona entra en el orden para que las fechas de la Zona A salgan juntas: sin
    ella se intercalan con las de la B y la pantalla tiene que reordenar.
    """
    return list(
        sesion.scalars(
            select(PartidoDeTorneo)
            .where(PartidoDeTorneo.torneo_id == torneo.id)
            .order_by(
                PartidoDeTorneo.etapa,
                PartidoDeTorneo.zona_id,
                PartidoDeTorneo.ronda,
                PartidoDeTorneo.orden,
            )
        ).all()
    )
