/** Cuadros de prueba para el dibujo de las llaves.
 *
 * Los de byes (5, 6 y 12 competidores) son la salida literal de
 * `app.servicios.fixture.llaves(n)`, que es lo que el servidor guarda como
 * `avanza_a_id` / `avanza_a_slot`: así los tests prueban la forma real del
 * cuadro y no una que me imaginé. Nombres ficticios.
 */
import type { PartidoDeTorneo } from '@/lib/api'

/** `[ronda, orden, a, b, avanza_a (ronda, orden) | null, slot | null]`. */
type Cruce = [number, number, number | null, number | null, [number, number] | null, string | null]

const CRUCES: Record<number, Cruce[]> = {
  5: [
    [1, 0, 3, 4, [2, 0], 'b'], [2, 0, 0, null, [3, 0], 'a'],
    [2, 1, 1, 2, [3, 0], 'b'], [3, 0, null, null, null, null],
  ],
  6: [
    [1, 0, 3, 4, [2, 0], 'b'], [1, 1, 2, 5, [2, 1], 'b'],
    [2, 0, 0, null, [3, 0], 'a'], [2, 1, 1, null, [3, 0], 'b'],
    [3, 0, null, null, null, null],
  ],
  12: [
    [1, 0, 7, 8, [2, 0], 'b'], [1, 1, 4, 11, [2, 1], 'b'],
    [1, 2, 6, 9, [2, 2], 'b'], [1, 3, 5, 10, [2, 3], 'b'],
    [2, 0, 0, null, [3, 0], 'a'], [2, 1, 3, null, [3, 0], 'b'],
    [2, 2, 1, null, [3, 1], 'a'], [2, 3, 2, null, [3, 1], 'b'],
    [3, 0, null, null, [4, 0], 'a'], [3, 1, null, null, [4, 0], 'b'],
    [4, 0, null, null, null, null],
  ],
}

/** Un cuadro completo (potencia de dos), armado como lo arma el servidor. */
function completo(competidores: number): Cruce[] {
  const cruces: Cruce[] = []
  const rondas = Math.log2(competidores)
  for (let ronda = 1; ronda <= rondas; ronda++) {
    const cuantos = competidores / 2 ** ronda
    for (let orden = 0; orden < cuantos; orden++) {
      cruces.push([
        ronda,
        orden,
        ronda === 1 ? orden * 2 : null,
        ronda === 1 ? orden * 2 + 1 : null,
        ronda === rondas ? null : [ronda + 1, Math.floor(orden / 2)],
        ronda === rondas ? null : orden % 2 === 0 ? 'a' : 'b',
      ])
    }
  }
  return cruces
}

const INSTANCIAS = ['Final', 'Semifinal', 'Cuartos de final', 'Octavos de final', '16avos de final']

export function cuadroDe(competidores: number): { rondas: number; partidos: PartidoDeTorneo[] } {
  const cruces = CRUCES[competidores] ?? completo(competidores)
  const rondas = Math.max(...cruces.map((c) => c[0]))
  const id = (ronda: number, orden: number) => 1000 + ronda * 100 + orden
  const nombre = (n: number | null) => (n === null ? null : `Jugador ${n + 1}`)
  const partidos = cruces.map(([ronda, orden, a, b, avanza, slot]): PartidoDeTorneo => ({
    id: id(ronda, orden), etapa: 'llaves', zona_id: null, zona: null, ronda, orden,
    instancia: INSTANCIAS[rondas - ronda] ?? `Ronda ${ronda}`,
    competidor_a_id: a === null ? null : a + 1, competidor_a: nombre(a),
    competidor_b_id: b === null ? null : b + 1, competidor_b: nombre(b),
    avanza_a_id: avanza ? id(avanza[0], avanza[1]) : null, avanza_a_slot: slot,
    reserva_id: null, cancha: null, comienza_at: null, termina_at: null,
    ganador_id: null, finalizado: false, parciales: [],
  }))
  return { rondas, partidos }
}
