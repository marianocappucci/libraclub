/** La geometría del cuadro de llaves: dónde va cada partido y qué líneas los unen.
 *
 * Es una función pura de los partidos —sin DOM, sin medir nada—, y por eso se
 * puede probar entera. La pantalla (`Fixture.tsx`) sólo la dibuja.
 *
 * 🔑 **Cada partido se ubica por lo que le alimenta, no por la ronda ni por el
 * orden.** Los partidos que nadie alimenta —las hojas del árbol— se apilan uno
 * debajo del otro; los demás quedan **exactamente a la altura media de sus
 * orígenes** (`avanza_a_id`). Con un cuadro completo son los partidos de la
 * ronda 1 y sale el bracket de siempre.
 *
 * 🔑 **Con byes no hay partidos fantasma.** Un bye no genera partido: el que
 * sortea con suerte aparece directo en la ronda siguiente (`servicios/fixture.py`,
 * `llaves()`), así que ese partido tiene un solo origen. Con un solo origen el
 * partido queda a su misma altura y la línea es recta; el competidor que entró
 * directo no tiene línea, porque no viene de ningún partido. Nunca hay un
 * conector sin un partido en cada punta.
 *
 * El alto de cada partido es fijo (`ALTO_DE_PARTIDO`): es lo que permite que la
 * altura media sea exacta y no «más o menos».
 */
import type { PartidoDeTorneo } from '@/lib/api'

// Todo en rem, para que escale con la tipografía del usuario.
/** Ancho de la tarjeta de un partido. */
export const ANCHO_DE_PARTIDO = 17
/** Ancho del hueco entre dos columnas, por donde pasan las líneas. */
export const ANCHO_DEL_CABLE = 2.5
/** Alto de la tarjeta. Fijo: dos competidores y una línea de cancha y horario. */
export const ALTO_DE_PARTIDO = 4.75
/** Alto de una fila de partidos: la tarjeta más el aire de arriba y abajo. */
export const ALTO_DE_FILA = 5.75
/** Alto del título de cada columna («Semifinal»). */
export const ALTO_DE_TITULO = 1.75

export interface NodoDeLlave {
  partido: PartidoDeTorneo
  /** 0 = la primera ronda. */
  columna: number
  /** El centro del partido, en filas desde arriba: una hoja ocupa `[k, k+1]` y
   *  su centro es `k + 0.5`. */
  y: number
  /** Los partidos que lo alimentan, de arriba abajo (`a` antes que `b`). Con
   *  byes puede ser uno solo, o ninguno. */
  origenes: number[]
}

export interface ConectorDeLlave {
  /** El partido al que entran las líneas. */
  hacia: number
  /** Los partidos de los que salen, de arriba abajo. Nunca vacío. */
  desde: number[]
}

export interface DisposicionDeLlaves {
  nodos: NodoDeLlave[]
  conectores: ConectorDeLlave[]
  /** Cuántas filas ocupa el cuadro entero. */
  filas: number
}

/** `a` va arriba de `b`; si falta, el orden del partido. */
function porLado(a: PartidoDeTorneo, b: PartidoDeTorneo): number {
  const lado = (p: PartidoDeTorneo) => (p.avanza_a_slot === 'b' ? 1 : 0)
  return lado(a) - lado(b) || a.orden - b.orden
}

export function disponerLlaves(partidos: PartidoDeTorneo[]): DisposicionDeLlaves {
  const porId = new Map(partidos.map((p) => [p.id, p]))
  const alimentan = new Map<number, PartidoDeTorneo[]>()
  for (const partido of partidos) {
    // Un `avanza_a_id` que no está en el cuadro (otra etapa) no es un origen.
    if (partido.avanza_a_id === null || !porId.has(partido.avanza_a_id)) continue
    alimentan.set(partido.avanza_a_id, [
      ...(alimentan.get(partido.avanza_a_id) ?? []),
      partido,
    ])
  }

  // Lo que nadie recibe: la final (y, si el cuadro llegara a tener otra salida,
  // cada una con su árbol, una debajo de la otra).
  const raices = partidos
    .filter((p) => p.avanza_a_id === null || !porId.has(p.avanza_a_id))
    .sort((a, b) => b.ronda - a.ronda || a.orden - b.orden)

  const nodos: NodoDeLlave[] = []
  let hojas = 0
  const ubicar = (partido: PartidoDeTorneo): NodoDeLlave => {
    const origenes = (alimentan.get(partido.id) ?? []).sort(porLado).map(ubicar)
    // Una hoja ocupa la fila que sigue; el resto, la altura media de sus
    // orígenes (con uno solo, la suya).
    const y = origenes.length
      ? (origenes[0].y + origenes[origenes.length - 1].y) / 2
      : hojas++ + 0.5
    const nodo: NodoDeLlave = {
      partido,
      columna: partido.ronda - 1,
      y,
      origenes: origenes.map((o) => o.partido.id),
    }
    nodos.push(nodo)
    return nodo
  }
  for (const raiz of raices) ubicar(raiz)

  const conectores = nodos
    .filter((n) => n.origenes.length > 0)
    .map((n) => ({ hacia: n.partido.id, desde: n.origenes }))
  return { nodos, conectores, filas: hojas }
}

/** Dónde empieza (izquierda) una columna, en rem. */
export function xDeColumna(columna: number): number {
  return columna * (ANCHO_DE_PARTIDO + ANCHO_DEL_CABLE)
}

/** El ancho del cuadro con `columnas` rondas, en rem. */
export function anchoDelCuadro(columnas: number): number {
  return Math.max(columnas, 1) * ANCHO_DE_PARTIDO + Math.max(columnas - 1, 0) * ANCHO_DEL_CABLE
}

/** El centro vertical de un nodo, en rem, contado desde la primera fila. */
export function yEnRem(y: number): number {
  return y * ALTO_DE_FILA
}

/** El trazo SVG (en rem) de un conector: de cada origen una horizontal corta
 *  hasta la mitad del hueco, una vertical que une los orígenes con el destino y
 *  una horizontal que entra al partido siguiente. */
export function trazoDelConector(
  conector: ConectorDeLlave,
  nodos: Map<number, NodoDeLlave>,
): string {
  const destino = nodos.get(conector.hacia)
  if (!destino) return ''
  const xEntrada = xDeColumna(destino.columna)
  // La vertical va siempre en el hueco justo antes del destino.
  const xMedio = xEntrada - ANCHO_DEL_CABLE / 2
  const yDestino = yEnRem(destino.y)
  const tramos: string[] = []
  const ys = [yDestino]
  for (const id of conector.desde) {
    const origen = nodos.get(id)
    if (!origen) continue
    const y = yEnRem(origen.y)
    ys.push(y)
    tramos.push(`M${xDeColumna(origen.columna) + ANCHO_DE_PARTIDO} ${y}H${xMedio}`)
  }
  const arriba = Math.min(...ys)
  const abajo = Math.max(...ys)
  if (arriba !== abajo) tramos.push(`M${xMedio} ${arriba}V${abajo}`)
  tramos.push(`M${xMedio} ${yDestino}H${xEntrada}`)
  return tramos.join('')
}
