"""Torneos: alta, inscripción, sorteo, programación y resultados.

El router valida, delega y traduce errores a códigos. Las reglas están en
`app/servicios/torneos.py` y el armado del cuadro en `app/servicios/fixture.py`.

**Quién puede qué**: definir el torneo, sortearlo, largar el playoff y
cancelarlo son de **admin** —cambian lo que el complejo se comprometió a jugar—;
inscribir, programar y cargar resultados son de **staff**, porque eso pasa
durante el torneo y lo hace el que está en el mostrador. Es la misma línea que
separa facturar de cobrar en el resto del producto.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin, require_staff
from app.db import obtener_sesion
from app.models.enums import EtapaTorneo
from app.models.maestros import Cancha
from app.models.reservas import Reserva
from app.models.torneos import Competidor, PartidoDeTorneo, Torneo, Zona
from app.schemas.torneos import (
    CompetidorEntrada,
    CompetidorSalida,
    FixtureSalida,
    IntegranteSalida,
    PartidoSalida,
    ProgramacionEntrada,
    ResultadoEntrada,
    TablaSalida,
    TorneoEdicion,
    TorneoEnLista,
    TorneoEntrada,
    TorneoSalida,
)
from app.servicios import reservas as servicio_reservas
from app.servicios import torneos as servicio
from app.tiempo import TZ

router = APIRouter(prefix="/api/torneos", tags=["torneos"])


def _traducir(fn):
    """Las excepciones del servicio, a códigos HTTP. En un solo lugar."""

    def envuelto(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except servicio.EstadoDelTorneo as exc:
            # 409: el pedido está bien formado, el torneo no lo admite ahora.
            raise HTTPException(409, str(exc)) from exc
        except servicio.TorneoInvalido as exc:
            raise HTTPException(422, str(exc)) from exc
        except servicio_reservas.Superpuesta as exc:
            # La cancha del partido choca con otra cosa. Llega hasta acá porque
            # programar un partido crea un bloqueo de verdad.
            raise HTTPException(409, str(exc)) from exc
        except servicio_reservas.ReservaInvalida as exc:
            raise HTTPException(400, str(exc)) from exc

    return envuelto


def _torneo(sesion: Session, torneo_id: int) -> Torneo:
    torneo = sesion.get(Torneo, torneo_id)
    if torneo is None:
        raise HTTPException(404, "No existe ese torneo.")
    return torneo


def _partido(sesion: Session, partido_id: int) -> PartidoDeTorneo:
    partido = sesion.get(PartidoDeTorneo, partido_id)
    if partido is None:
        raise HTTPException(404, "No existe ese partido.")
    return partido


# ── El torneo ───────────────────────────────────────────────────────────────


@router.get("", response_model=list[TorneoEnLista])
def listar(
    sucursal_id: int | None = Query(default=None),
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    consulta = select(Torneo).order_by(Torneo.desde.desc(), Torneo.id.desc())
    if sucursal_id is not None:
        consulta = consulta.where(Torneo.sucursal_id == sucursal_id)
    torneos = list(sesion.scalars(consulta).all())
    if not torneos:
        return []

    # Los contadores de TODOS los torneos en dos consultas y no dos por torneo:
    # una lista de veinte torneos serían cuarenta viajes a la base.
    ids = [t.id for t in torneos]
    partidos: dict[int, list[PartidoDeTorneo]] = {i: [] for i in ids}
    for partido in sesion.scalars(
        select(PartidoDeTorneo).where(PartidoDeTorneo.torneo_id.in_(ids))
    ):
        partidos[partido.torneo_id].append(partido)
    inscriptos: dict[int, int] = {i: 0 for i in ids}
    for competidor in sesion.scalars(
        select(Competidor).where(Competidor.torneo_id.in_(ids))
    ):
        inscriptos[competidor.torneo_id] += 1

    salida = []
    for torneo in torneos:
        propios = partidos[torneo.id]
        ganador = servicio.campeon(sesion, torneo)
        salida.append(
            TorneoEnLista(
                **TorneoSalida.model_validate(torneo).model_dump(),
                competidores=inscriptos[torneo.id],
                partidos=len(propios),
                jugados=sum(1 for p in propios if p.finalizado),
                sin_programar=sum(
                    1 for p in propios if p.reserva_id is None and not p.finalizado
                ),
                campeon=ganador.nombre if ganador else None,
            )
        )
    return salida


@router.post("", response_model=TorneoSalida, status_code=201)
def crear(
    datos: TorneoEntrada,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
):
    torneo = Torneo(**datos.model_dump())
    sesion.add(torneo)
    sesion.commit()
    sesion.refresh(torneo)
    return torneo


@router.get("/{torneo_id}", response_model=TorneoSalida)
def obtener(
    torneo_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    return _torneo(sesion, torneo_id)


@router.put("/{torneo_id}", response_model=TorneoSalida)
def editar(
    torneo_id: int,
    datos: TorneoEdicion,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
):
    """Corrige lo que no toca el cuadro. El formato no está acá a propósito."""
    torneo = _torneo(sesion, torneo_id)
    for campo, valor in datos.model_dump().items():
        setattr(torneo, campo, valor)
    sesion.commit()
    sesion.refresh(torneo)
    return torneo


@router.post("/{torneo_id}/cancelar", response_model=dict)
def cancelar(
    torneo_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
):
    """Cancela el torneo y libera todas las canchas que tenía tomadas."""
    torneo = _torneo(sesion, torneo_id)
    liberadas = _traducir(servicio.cancelar)(sesion, torneo)
    sesion.commit()
    return {"torneo_id": torneo_id, "canchas_liberadas": liberadas}


# ── Competidores ────────────────────────────────────────────────────────────


@router.get("/{torneo_id}/competidores", response_model=list[CompetidorSalida])
def listarcompetidores_de(
    torneo_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    torneo = _torneo(sesion, torneo_id)
    zonas = {z.id: z.nombre for z in sesion.scalars(
        select(Zona).where(Zona.torneo_id == torneo.id)
    )}
    return [
        CompetidorSalida(
            id=c.id,
            nombre=c.nombre,
            siembra=c.siembra,
            zona_id=c.zona_id,
            zona=zonas.get(c.zona_id) if c.zona_id else None,
            integrantes=[
                IntegranteSalida.model_validate(i) for i in c.integrantes
            ],
        )
        # Sembrados primero y por su número, después alfabético: es el orden en
        # que el encargado revisa la lista antes de sortear.
        for c in sorted(
            servicio.competidores_de(sesion, torneo),
            key=lambda c: (c.siembra is None, c.siembra or 0, c.nombre),
        )
    ]


@router.post("/{torneo_id}/competidores", response_model=CompetidorSalida, status_code=201)
def inscribir(
    torneo_id: int,
    datos: CompetidorEntrada,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    torneo = _torneo(sesion, torneo_id)
    competidor = _traducir(servicio.inscribir)(
        sesion,
        torneo,
        nombre=datos.nombre,
        siembra=datos.siembra,
        integrantes=[(i.nombre, i.telefono) for i in datos.integrantes],
    )
    sesion.commit()
    sesion.refresh(competidor)
    return CompetidorSalida(
        id=competidor.id, nombre=competidor.nombre, siembra=competidor.siembra,
        zona_id=None, zona=None,
        integrantes=[IntegranteSalida.model_validate(i) for i in competidor.integrantes],
    )


@router.delete("/competidores/{competidor_id}", status_code=204)
def bajar_competidor(
    competidor_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    # 🔴 Dos segmentos y no `/{torneo_id}/competidores/{id}` por comodidad: el
    # competidor ya sabe de qué torneo es. Y `competidores` no colisiona con el
    # `GET /{torneo_id}` de arriba justamente porque son dos segmentos — ver la
    # misma trampa documentada en `routers/reservas.py`.
    competidor = sesion.get(Competidor, competidor_id)
    if competidor is None:
        raise HTTPException(404, "No existe ese competidor.")
    _traducir(servicio.bajar_competidor)(sesion, competidor)
    sesion.commit()


# ── Sorteo y fixture ────────────────────────────────────────────────────────


@router.post("/{torneo_id}/sortear", response_model=TorneoSalida)
def sortear(
    torneo_id: int,
    semilla: int | None = Query(default=None, ge=1),
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
):
    """Sortea y arma el fixture. Una sola vez por torneo.

    `semilla` se puede pasar para reproducir un sorteo hecho frente a la gente.
    Si no viene, se elige una y se guarda: el sorteo queda auditable igual.
    """
    torneo = _torneo(sesion, torneo_id)
    _traducir(servicio.sortear)(sesion, torneo, semilla)
    sesion.commit()
    sesion.refresh(torneo)
    return torneo


@router.post("/{torneo_id}/playoff", response_model=TorneoSalida)
def playoff(
    torneo_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_admin),
):
    """Arma las llaves con los que clasificaron. Sólo en torneos por zonas."""
    torneo = _torneo(sesion, torneo_id)
    _traducir(servicio.generar_playoff)(sesion, torneo)
    sesion.commit()
    sesion.refresh(torneo)
    return torneo


@router.get("/{torneo_id}/fixture", response_model=FixtureSalida)
def fixture(
    torneo_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Todo el fixture con nombres, canchas y horarios resueltos.

    Un solo endpoint para el cuadro y las fechas de grupos: la pantalla los
    dibuja distinto pero los necesita juntos, y partirlo en dos obligaría a
    pedir los dos y unirlos del lado del cliente.
    """
    torneo = _torneo(sesion, torneo_id)
    partidos = servicio.partidos_de(sesion, torneo)
    return FixtureSalida(
        rondas=servicio.rondas_de_llaves(partidos),
        partidos=_pintar(sesion, torneo, partidos),
    )


def _pintar(
    sesion: Session, torneo: Torneo, partidos: list[PartidoDeTorneo]
) -> list[PartidoSalida]:
    """Resuelve nombres, canchas y horarios **en tres consultas, no en 3N**.

    Un torneo de 32 llega a 63 partidos: pidiendo el competidor y la reserva de
    cada uno serían casi doscientos viajes a la base para dibujar una pantalla.
    """
    nombres = {c.id: c.nombre for c in servicio.competidores_de(sesion, torneo)}
    zonas = {z.id: z.nombre for z in sesion.scalars(
        select(Zona).where(Zona.torneo_id == torneo.id)
    )}
    ids = [p.reserva_id for p in partidos if p.reserva_id is not None]
    reservas = {
        r.id: r
        for r in (
            sesion.scalars(select(Reserva).where(Reserva.id.in_(ids))) if ids else []
        )
    }
    canchas = {c.id: c.nombre for c in sesion.scalars(select(Cancha))}
    rondas = servicio.rondas_de_llaves(partidos)

    salida = []
    for partido in partidos:
        reserva = reservas.get(partido.reserva_id or 0)
        salida.append(
            PartidoSalida(
                id=partido.id,
                etapa=partido.etapa,
                zona_id=partido.zona_id,
                zona=zonas.get(partido.zona_id) if partido.zona_id else None,
                ronda=partido.ronda,
                orden=partido.orden,
                instancia=servicio.instancia(sesion, torneo, partido, rondas),
                competidor_a_id=partido.competidor_a_id,
                competidor_a=nombres.get(partido.competidor_a_id or 0),
                competidor_b_id=partido.competidor_b_id,
                competidor_b=nombres.get(partido.competidor_b_id or 0),
                avanza_a_id=partido.avanza_a_id,
                avanza_a_slot=partido.avanza_a_slot,
                reserva_id=partido.reserva_id,
                cancha=canchas.get(reserva.cancha_id) if reserva else None,
                comienza_at=reserva.comienza_at if reserva else None,
                termina_at=reserva.termina_at if reserva else None,
                ganador_id=partido.ganador_id,
                finalizado=partido.finalizado,
                parciales=partido.parciales,
            )
        )
    return salida


@router.get("/{torneo_id}/posiciones", response_model=list[TablaSalida])
def posiciones(
    torneo_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Las tablas de la fase de grupos. Vacío en un torneo de eliminación."""
    torneo = _torneo(sesion, torneo_id)
    partidos = servicio.partidos_de(sesion, torneo)
    if not any(p.etapa is EtapaTorneo.GRUPOS for p in partidos):
        # Un cuadro de eliminación no tiene tabla. Devolver una vacía con todos
        # en cero haría creer que hay algo que mirar.
        return []
    return servicio.tabla_de_posiciones(sesion, torneo)


# ── Partidos: cancha, horario y resultado ───────────────────────────────────


@router.post("/partidos/{partido_id}/programar", response_model=PartidoSalida)
def programar(
    partido_id: int,
    datos: ProgramacionEntrada,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Le da cancha y horario, ocupándola de verdad en la agenda."""
    partido = _partido(sesion, partido_id)
    _traducir(servicio.programar)(
        sesion,
        partido,
        cancha_id=datos.cancha_id,
        comienza_at=_con_zona(datos.comienza_at),
        duracion_min=datos.duracion_min,
    )
    sesion.commit()
    return _uno(sesion, partido)


@router.post("/partidos/{partido_id}/liberar", response_model=PartidoSalida)
def liberar(
    partido_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Le saca la cancha al partido y libera el horario en la agenda."""
    partido = _partido(sesion, partido_id)
    _traducir(servicio.desprogramar)(sesion, partido)
    sesion.commit()
    return _uno(sesion, partido)


@router.post("/partidos/{partido_id}/resultado", response_model=PartidoSalida)
def cargar_resultado(
    partido_id: int,
    datos: ResultadoEntrada,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Carga el resultado y pasa al ganador a la ronda siguiente."""
    partido = _partido(sesion, partido_id)
    _traducir(servicio.cargar_resultado)(
        sesion, partido, [(p.puntos_a, p.puntos_b) for p in datos.parciales]
    )
    sesion.commit()
    return _uno(sesion, partido)


@router.delete("/partidos/{partido_id}/resultado", response_model=PartidoSalida)
def borrar_resultado(
    partido_id: int,
    sesion: Session = Depends(obtener_sesion),
    _: object = Depends(require_staff),
):
    """Deja el partido como no jugado y saca al ganador de la ronda siguiente."""
    partido = _partido(sesion, partido_id)
    _traducir(servicio.borrar_resultado)(sesion, partido)
    sesion.commit()
    return _uno(sesion, partido)


def _uno(sesion: Session, partido: PartidoDeTorneo) -> PartidoSalida:
    torneo = _torneo(sesion, partido.torneo_id)
    sesion.refresh(partido)
    # Se pinta contra el fixture completo y no contra el partido suelto porque
    # el nombre de la instancia («Semifinal») depende de cuántas rondas tiene el
    # cuadro, que sólo se sabe mirando a los demás.
    partidos = servicio.partidos_de(sesion, torneo)
    return next(p for p in _pintar(sesion, torneo, partidos) if p.id == partido.id)


def _con_zona(valor: datetime) -> datetime:
    """Un datetime sin offset se toma como hora local del complejo.

    Mismo criterio que el alta de reservas: interpretarlo como UTC —que es lo
    que hace PostgreSQL— pondría el partido tres horas antes. Ver
    `routers/reservas.py`.
    """
    return valor if valor.tzinfo is not None else valor.replace(tzinfo=TZ)
