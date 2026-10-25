import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { PartidoDeTorneo } from '@/lib/api'
import { Fixture } from './Fixture'
import { cuadroDe } from '@/test/cuadros'

/**
 * El cuadro de llaves dibujado, en lo que jsdom puede medir (no hay layout, así
 * que se lee lo que el componente declara: las alturas `data-y`, los orígenes y
 * los conectores). Cómo se ve de verdad se miró con capturas.
 */

function montar(n: number, cambios: (p: PartidoDeTorneo[]) => PartidoDeTorneo[] = (p) => p) {
  const { rondas, partidos } = cuadroDe(n)
  const onAbrir = vi.fn()
  render(<Fixture fixture={{ rondas, partidos: cambios(partidos) }} onAbrir={onAbrir} />)
  const cuadro = screen.getByTestId('cuadro-de-llaves')
  const tarjetas = Array.from(cuadro.querySelectorAll<HTMLElement>('li[data-partido]'))
  const conectores = Array.from(cuadro.querySelectorAll<SVGPathElement>('path[data-conector]'))
  return { cuadro, tarjetas, conectores, onAbrir, partidos }
}

const ids = (texto: string | null) => (texto ? texto.split(',').map(Number) : [])

describe('las líneas del cuadro', () => {
  it('con 16 hay un conector por cada partido de la ronda 2 en adelante, de dos orígenes', () => {
    const { tarjetas, conectores, partidos } = montar(16)
    expect(tarjetas).toHaveLength(15)
    expect(conectores).toHaveLength(7)
    const deRondaDosEnAdelante = partidos.filter((p) => p.ronda >= 2).map((p) => p.id)
    expect(conectores.map((c) => Number(c.dataset.hacia)).sort()).toEqual(
      [...deRondaDosEnAdelante].sort(),
    )
    for (const c of conectores) expect(ids(c.dataset.desde ?? null)).toHaveLength(2)
    // Cada partido de ronda ≥ 2 declara sus dos orígenes, y son los que dicen
    // avanza_a_id de los partidos de la ronda anterior.
    for (const t of tarjetas) {
      const partido = partidos.find((p) => p.id === Number(t.dataset.partido))!
      const origenes = ids(t.dataset.origenes ?? null)
      expect(origenes).toHaveLength(partido.ronda === 1 ? 0 : 2)
      for (const o of origenes) {
        expect(partidos.find((p) => p.id === o)!.avanza_a_id).toBe(partido.id)
      }
    }
  })

  it('cada partido queda exactamente a la altura media de sus dos orígenes', () => {
    const { tarjetas } = montar(16)
    const y = new Map(tarjetas.map((t) => [Number(t.dataset.partido), Number(t.dataset.y)]))
    // Y también en lo que se dibuja: el `top` de la tarjeta (en rem).
    const top = new Map(tarjetas.map((t) => [Number(t.dataset.partido), parseFloat(t.style.top)]))
    for (const t of tarjetas.filter((x) => ids(x.dataset.origenes ?? null).length === 2)) {
      const [a, b] = ids(t.dataset.origenes ?? null)
      const id = Number(t.dataset.partido)
      expect(y.get(id)).toBe((y.get(a)! + y.get(b)!) / 2)
      expect(top.get(id)).toBeCloseTo((top.get(a)! + top.get(b)!) / 2, 9)
    }
  })

  for (const n of [5, 6, 12]) {
    it(`con ${n} competidores (byes) no queda ninguna línea colgando`, () => {
      const { tarjetas, conectores, partidos } = montar(n)
      const enPantalla = new Set(tarjetas.map((t) => Number(t.dataset.partido)))
      // Un bye no genera un partido: hay menos partidos en la ronda 1 que
      // lugares, y todos los que hay están dibujados.
      expect(enPantalla.size).toBe(partidos.length)
      for (const c of conectores) {
        const desde = ids(c.dataset.desde ?? null)
        expect(desde.length).toBeGreaterThanOrEqual(1)
        expect(desde.length).toBeLessThanOrEqual(2)
        expect(enPantalla.has(Number(c.dataset.hacia))).toBe(true)
        for (const o of desde) {
          expect(enPantalla.has(o)).toBe(true)
          expect(partidos.find((p) => p.id === o)!.avanza_a_id).toBe(Number(c.dataset.hacia))
        }
        // Tiene trazo: ningún <path> vacío.
        expect(c.getAttribute('d')).toMatch(/^M/)
      }
      // Hay un conector por cada partido con origen, y cada partido que avanza
      // sale en alguno.
      const conOrigen = tarjetas.filter((t) => ids(t.dataset.origenes ?? null).length > 0)
      expect(conectores).toHaveLength(conOrigen.length)
      const salen = new Set(conectores.flatMap((c) => ids(c.dataset.desde ?? null)))
      for (const p of partidos.filter((x) => x.avanza_a_id !== null)) {
        expect(salen.has(p.id)).toBe(true)
      }
    })
  }

  it('con un bye, el partido que recibe a un solo origen queda a su misma altura', () => {
    const { tarjetas, conectores } = montar(6)
    const y = (id: number) =>
      Number(tarjetas.find((t) => t.dataset.partido === String(id))!.dataset.y)
    // 6 competidores: dos partidos en la ronda 1 y los dos de la ronda 2 con un
    // solo origen cada uno (el otro lado es un bye).
    const rectos = conectores.filter((c) => ids(c.dataset.desde ?? null).length === 1)
    expect(rectos).toHaveLength(2)
    for (const c of rectos) {
      expect(y(Number(c.dataset.hacia))).toBe(y(ids(c.dataset.desde ?? null)[0]))
      expect(c.getAttribute('d')).not.toContain('V')
    }
  })

  it('el orden vertical de cada ronda no cambia: sigue el `orden` del partido', () => {
    for (const n of [6, 12, 16]) {
      document.body.innerHTML = ''
      const { tarjetas, partidos } = montar(n)
      for (const ronda of new Set(partidos.map((p) => p.ronda))) {
        const deLaRonda = tarjetas
          .filter((t) => partidos.find((p) => p.id === Number(t.dataset.partido))!.ronda === ronda)
          .sort((a, b) => Number(a.dataset.y) - Number(b.dataset.y))
          .map((t) => partidos.find((p) => p.id === Number(t.dataset.partido))!.orden)
        expect(deLaRonda).toEqual([...deLaRonda].sort((a, b) => a - b))
      }
      document.body.innerHTML = ''
    }
  })

  it('las líneas son del color del borde del tema y no estorban al toque', () => {
    const { cuadro, conectores } = montar(8)
    for (const c of conectores) expect(c.getAttribute('stroke')).toContain('var(--border)')
    const svg = cuadro.querySelector('svg')!
    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(svg.getAttribute('class')).toContain('pointer-events-none')
  })

  it('una columna por ronda, con su título', () => {
    montar(16)
    for (const titulo of ['Octavos de final', 'Cuartos de final', 'Semifinal', 'Final']) {
      expect(screen.getByRole('heading', { name: titulo, level: 4 })).toBeInTheDocument()
    }
  })
})

describe('la tarjeta de cada partido', () => {
  it('se abre al tocarla y tiene un nombre accesible con la instancia y los dos', async () => {
    const { onAbrir } = montar(8)
    const tarjeta = screen.getByRole('button', { name: 'Cuartos de final: Jugador 1 contra Jugador 2' })
    await userEvent.click(tarjeta)
    expect(onAbrir).toHaveBeenCalledTimes(1)
    expect(onAbrir.mock.calls[0][0].competidor_a).toBe('Jugador 1')
  })

  it('muestra el resultado, el ganador en negrita, la cancha y el horario', () => {
    montar(4, (partidos) =>
      partidos.map((p) =>
        p.ronda === 1 && p.orden === 0
          ? {
              ...p, finalizado: true, ganador_id: p.competidor_a_id,
              parciales: [{ numero: 1, puntos_a: 6, puntos_b: 3 }],
              cancha: 'Cancha 2', comienza_at: '2026-10-10T18:00:00-03:00',
            }
          : p,
      ),
    )
    const tarjeta = screen.getByRole('button', { name: 'Semifinal: Jugador 1 contra Jugador 2' })
    expect(within(tarjeta).getByText('Jugador 1')).toHaveClass('font-semibold')
    expect(within(tarjeta).getByText('Jugador 2')).not.toHaveClass('font-semibold')
    expect(within(tarjeta).getByText('6-3')).toBeInTheDocument()
    expect(within(tarjeta).getByText('Cancha 2')).toBeInTheDocument()
    expect(within(tarjeta).getByText(/18:00/)).toBeInTheDocument()
  })

  it('un cruce que espera ganadores no se marca «Sin cancha»', () => {
    montar(4)
    const final = screen.getByRole('button', { name: /^Final:/ })
    expect(within(final).queryByText('Sin cancha')).toBeNull()
    expect(within(final).getAllByText('a definir').length).toBeGreaterThan(0)
  })
})

describe('el cuadro scrollea solo', () => {
  it('el contenedor tiene overflow-x y el cuadro un ancho propio', () => {
    const { cuadro } = montar(16)
    expect(cuadro.parentElement).toHaveClass('overflow-x-auto')
    // Cuatro columnas de 17rem y tres huecos de 2.5rem.
    expect(cuadro.style.width).toBe('75.5rem')
  })
})
