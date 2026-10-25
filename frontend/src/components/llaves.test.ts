import { describe, expect, it } from 'vitest'

import {
  ANCHO_DE_PARTIDO,
  ANCHO_DEL_CABLE,
  ALTO_DE_FILA,
  anchoDelCuadro,
  disponerLlaves,
  trazoDelConector,
} from './llaves'
import { cuadroDe } from '@/test/cuadros'

/**
 * La geometría del cuadro, sin DOM:
 *
 * 1. cada partido con orígenes queda a la altura media EXACTA de ellos;
 * 2. con byes hay partidos con un solo origen (o ninguno), y la línea de ése es
 *    recta, sin ramas colgando;
 * 3. el orden vertical dentro de una ronda es el del servidor (`orden`).
 */

function disposicion(n: number) {
  const { partidos } = cuadroDe(n)
  const d = disponerLlaves(partidos)
  return { ...d, porId: new Map(d.nodos.map((x) => [x.partido.id, x])) }
}

describe('disponerLlaves', () => {
  it('un cuadro de 16: ocho filas, y cada partido a la altura media de sus dos orígenes', () => {
    const { nodos, porId, filas, conectores } = disposicion(16)
    expect(nodos).toHaveLength(15)
    expect(filas).toBe(8)
    // Un conector por cada partido de la ronda 2 en adelante: 4 + 2 + 1.
    expect(conectores).toHaveLength(7)
    for (const nodo of nodos.filter((n) => n.partido.ronda >= 2)) {
      expect(nodo.origenes).toHaveLength(2)
      const [arriba, abajo] = nodo.origenes.map((id) => porId.get(id)!.y)
      expect(nodo.y).toBe((arriba + abajo) / 2)
      expect(arriba).toBeLessThan(abajo)
    }
    // La final, al medio del cuadro entero.
    expect(porId.get(1400)!.y).toBe(4)
  })

  it('los orígenes son los que dicen avanza_a_id y avanza_a_slot, `a` arriba', () => {
    const { nodos, porId } = disposicion(8)
    for (const nodo of nodos) {
      for (const id of nodo.origenes) {
        expect(porId.get(id)!.partido.avanza_a_id).toBe(nodo.partido.id)
      }
      const lados = nodo.origenes.map((id) => porId.get(id)!.partido.avanza_a_slot)
      expect(lados).toEqual([...lados].sort())
    }
  })

  it('con 5 competidores: la final queda entre un partido con bye y otro que entró directo', () => {
    const { porId, filas, conectores } = disposicion(5)
    // Ronda 1: 1 partido. Ronda 2: el que lo recibe (1 origen) y uno sin
    // origen, que entró directo. Final: los dos.
    expect(filas).toBe(2)
    expect(porId.get(1100)!.y).toBe(0.5)
    expect(porId.get(1200)!.y).toBe(0.5) // un solo origen: a su misma altura
    expect(porId.get(1201)!.y).toBe(1.5)
    expect(porId.get(1200)!.origenes).toEqual([1100])
    expect(porId.get(1201)!.origenes).toEqual([])
    expect(porId.get(1300)!.y).toBe(1)
    expect(conectores.map((c) => [c.hacia, c.desde])).toEqual([
      [1200, [1100]],
      [1300, [1200, 1201]],
    ])
  })

  it('con 12 competidores la ronda 2 queda en línea con la 1 y la altura media sigue exacta', () => {
    const { nodos, porId } = disposicion(12)
    for (const nodo of nodos) {
      if (nodo.origenes.length === 1) {
        expect(nodo.y).toBe(porId.get(nodo.origenes[0])!.y)
      }
      if (nodo.origenes.length === 2) {
        const [a, b] = nodo.origenes.map((id) => porId.get(id)!.y)
        expect(nodo.y).toBe((a + b) / 2)
      }
    }
    // Ocho competidores por cada lado de la final, cuatro partidos en la 1ª.
    expect(nodos.filter((n) => n.partido.ronda === 1)).toHaveLength(4)
  })

  for (const n of [5, 6, 8, 12, 16, 32]) {
    it(`${n} competidores: el orden vertical de cada ronda es el del servidor`, () => {
      const { nodos } = disposicion(n)
      const rondas = new Set(nodos.map((x) => x.partido.ronda))
      for (const ronda of rondas) {
        const deLaRonda = nodos.filter((x) => x.partido.ronda === ronda)
        const porAltura = [...deLaRonda].sort((a, b) => a.y - b.y).map((x) => x.partido.orden)
        expect(porAltura).toEqual([...deLaRonda].map((x) => x.partido.orden).sort((a, b) => a - b))
        // Y no hay dos partidos de la misma ronda en la misma altura.
        expect(new Set(deLaRonda.map((x) => x.y)).size).toBe(deLaRonda.length)
      }
    })

    it(`${n} competidores: ningún conector sin partido en las dos puntas`, () => {
      const { conectores, porId, nodos } = disposicion(n)
      for (const c of conectores) {
        expect(porId.has(c.hacia)).toBe(true)
        expect(c.desde.length).toBeGreaterThan(0)
        for (const id of c.desde) expect(porId.get(id)!.partido.avanza_a_id).toBe(c.hacia)
      }
      // Todo partido que alimenta a otro tiene su conector (nada sin unir).
      const conLinea = new Set(conectores.flatMap((c) => c.desde))
      for (const nodo of nodos.filter((x) => x.partido.avanza_a_id !== null)) {
        expect(conLinea.has(nodo.partido.id)).toBe(true)
      }
    })
  }

  it('ignora un avanza_a_id que no está en el cuadro', () => {
    const { partidos } = cuadroDe(4)
    const sueltos = partidos.map((p) => (p.ronda === 1 ? { ...p, avanza_a_id: 999 } : p))
    // Los dos de la ronda 1 pasan a ser raíces: sin destino no hay conector.
    const { conectores } = disponerLlaves(sueltos.filter((p) => p.ronda === 1))
    expect(conectores).toEqual([])
  })
})

describe('el trazo', () => {
  it('une dos orígenes con una vertical y entra al partido siguiente', () => {
    const { conectores, porId } = disposicion(4)
    const final = conectores.find((c) => c.hacia === 1200)!
    const salida = ANCHO_DE_PARTIDO
    const medio = ANCHO_DE_PARTIDO + ANCHO_DEL_CABLE / 2
    const entrada = ANCHO_DE_PARTIDO + ANCHO_DEL_CABLE
    const y1 = 0.5 * ALTO_DE_FILA
    const y2 = 1.5 * ALTO_DE_FILA
    expect(trazoDelConector(final, porId)).toBe(
      `M${salida} ${y1}H${medio}M${salida} ${y2}H${medio}M${medio} ${y1}V${y2}M${medio} ${ALTO_DE_FILA}H${entrada}`,
    )
  })

  it('con un solo origen la línea es recta, sin vertical', () => {
    const { conectores, porId } = disposicion(6)
    const recto = conectores.find((c) => c.hacia === 1200)!
    expect(recto.desde).toHaveLength(1)
    expect(trazoDelConector(recto, porId)).not.toContain('V')
  })

  it('el ancho del cuadro suma columnas y huecos', () => {
    expect(anchoDelCuadro(1)).toBe(ANCHO_DE_PARTIDO)
    expect(anchoDelCuadro(4)).toBe(4 * ANCHO_DE_PARTIDO + 3 * ANCHO_DEL_CABLE)
  })
})
