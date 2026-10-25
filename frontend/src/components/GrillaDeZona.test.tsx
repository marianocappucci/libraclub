import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PartidoDeTorneo, TablaDeZona, Torneo } from '@/lib/api'
import {
  GrillaDeZona,
  GrillasDelTorneo,
  cruceEntre,
  parcialesDesdeLaFila,
  resultadoDesdeLaFila,
} from './GrillaDeZona'

/**
 * Lo que la grilla decide, y que un test puede hacer fallar:
 *
 * 1. que el casillero muestre el resultado **desde el punto de vista de la fila**,
 *    aunque la pareja de la fila haya quedado del lado `b` en el sorteo;
 * 2. que la diagonal quede bloqueada y no se pueda abrir;
 * 3. que un cruce no jugado quede vacío, y uno jugado muestre todos sus sets;
 * 4. que el casillero abra el partido correcto (cargar o corregir el resultado);
 * 5. que las columnas de posiciones salgan de la tabla, y el campeón de zona sólo
 *    con la zona terminada y sin llaves;
 * 6. que imprimir arme la hoja con el título del torneo y la zona elegida.
 *
 * Todos los nombres son ficticios.
 */

const PAREJAS = [
  { id: 1, nombre: 'Aguirre / Bustos' },
  { id: 2, nombre: 'Cabrera / Domínguez' },
  { id: 3, nombre: 'Echeverría / Fuentes' },
]

function partido(
  id: number, a: number, b: number, parciales: [number, number][] = [], ganador: number | null = null,
  extra: Partial<PartidoDeTorneo> = {},
): PartidoDeTorneo {
  const nombre = (n: number) => PAREJAS.find((p) => p.id === n)!.nombre
  return {
    id, etapa: 'grupos', zona_id: 7, zona: 'Zona A', ronda: 1, orden: 0,
    instancia: 'Zona A · Fecha 1',
    competidor_a_id: a, competidor_a: nombre(a),
    competidor_b_id: b, competidor_b: nombre(b),
    avanza_a_id: null, avanza_a_slot: null,
    reserva_id: null, cancha: null, comienza_at: null, termina_at: null,
    ganador_id: ganador,
    finalizado: parciales.length > 0,
    parciales: parciales.map(([puntos_a, puntos_b], i) => ({ numero: i + 1, puntos_a, puntos_b })),
    ...extra,
  }
}

/** 1 le ganó a 2 por 6-4 (quedó del lado a); 3 le ganó a 1 por 6-2 pero quedó del
 *  lado a, o sea que para la pareja 1 el resultado es 2-6; 2 contra 3 sin jugar. */
const PARTIDOS = [
  partido(10, 1, 2, [[6, 4]], 1),
  partido(11, 3, 1, [[6, 2]], 3),
  partido(12, 2, 3),
]

function fila(id: number, jugados: number, ganados: number, dif_sets: number, dif: number) {
  return {
    competidor_id: id, nombre: PAREJAS.find((p) => p.id === id)!.nombre, jugados, ganados,
    empatados: 0, perdidos: jugados - ganados, a_favor: 10, en_contra: 10 - dif,
    diferencia: dif, puntos: ganados * 3, sets_a_favor: 0, sets_en_contra: 0,
    diferencia_sets: dif_sets,
  }
}

const TABLA: TablaDeZona = {
  zona_id: 7, nombre: 'Zona A', con_sets: true, completa: false,
  filas: [fila(3, 1, 1, 1, 4), fila(1, 2, 1, 0, 2), fila(2, 1, 0, -1, -2)],
}

function montar(
  props: Partial<React.ComponentProps<typeof GrillaDeZona>> = {},
) {
  const onAbrir = vi.fn()
  render(
    <GrillaDeZona
      tabla={TABLA}
      partidos={PARTIDOS}
      clasifican={null}
      terminaEnZonas={false}
      onAbrir={onAbrir}
      {...props}
    />,
  )
  return onAbrir
}

describe('el resultado de un casillero', () => {
  it('se lee desde la pareja de la fila', () => {
    // El partido 11 es «3 contra 1» y terminó 6-2 a favor de la 3.
    expect(resultadoDesdeLaFila(PARTIDOS[1], 3)).toBe('6-2')
    // 🔴 Para la pareja 1, que quedó del lado b, es 2-6: dibujar el 6-2 tal cual
    // le atribuiría una victoria que fue de la otra.
    expect(resultadoDesdeLaFila(PARTIDOS[1], 1)).toBe('2-6')
    // Y el partido 10, donde la 1 quedó del lado a, se lee como se guardó.
    expect(resultadoDesdeLaFila(PARTIDOS[0], 1)).toBe('6-4')
    expect(resultadoDesdeLaFila(PARTIDOS[0], 2)).toBe('4-6')
  })

  it('trae todos los sets, dados vuelta de la misma forma', () => {
    const tres = partido(20, 1, 2, [[6, 4], [3, 6], [7, 6]], 1)
    expect(parcialesDesdeLaFila(tres, 1)).toEqual(['6-4', '3-6', '7-6'])
    expect(parcialesDesdeLaFila(tres, 2)).toEqual(['4-6', '6-3', '6-7'])
  })

  it('un partido sin jugar no tiene resultado', () => {
    expect(resultadoDesdeLaFila(PARTIDOS[2], 2)).toBe('')
  })

  it('el cruce se encuentra sin importar de qué lado quedó cada pareja', () => {
    expect(cruceEntre(PARTIDOS, 1, 3)?.id).toBe(11)
    expect(cruceEntre(PARTIDOS, 3, 1)?.id).toBe(11)
    expect(cruceEntre(PARTIDOS, 2, 2)).toBeUndefined()
  })
})

describe('la grilla', () => {
  it('lleva a cada pareja en una fila y en una columna, con ZONA en la esquina', () => {
    montar()
    const tabla = screen.getByRole('table')
    expect(within(tabla).getByText('Zona A')).toBeInTheDocument()
    for (const { nombre } of PAREJAS) {
      expect(within(tabla).getAllByText(nombre)).toHaveLength(2) // fila y columna
    }
  })

  it('muestra el resultado de cada cruce desde la fila', () => {
    montar()
    // 1 contra 2: 6-4 para la 1; visto desde la 2, 4-6.
    expect(
      screen.getByRole('button', { name: 'Aguirre / Bustos contra Cabrera / Domínguez: 6-4' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Cabrera / Domínguez contra Aguirre / Bustos: 4-6' }),
    ).toBeInTheDocument()
    // 1 contra 3: la 3 ganó 6-2, la 1 lo ve como 2-6 y la 3 como 6-2.
    expect(
      screen.getByRole('button', { name: 'Aguirre / Bustos contra Echeverría / Fuentes: 2-6' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Echeverría / Fuentes contra Aguirre / Bustos: 6-2' }),
    ).toBeInTheDocument()
  })

  it('deja vacío el cruce que no se jugó', () => {
    montar()
    // Sin dos puntos ni resultado: el nombre termina en el rival.
    expect(
      screen.getByRole('button', { name: 'Cabrera / Domínguez contra Echeverría / Fuentes' }),
    ).toHaveTextContent('')
  })

  it('bloquea la diagonal: una pareja no juega contra sí misma', () => {
    montar()
    const diagonales = document.querySelectorAll('td.grilla-diagonal')
    expect(diagonales).toHaveLength(PAREJAS.length)
    for (const celda of diagonales) {
      expect(celda).toHaveAttribute('aria-hidden', 'true')
      expect(within(celda as HTMLElement).queryByRole('button')).toBeNull()
    }
  })

  it('🔴 la diagonal va rellena de rojo, entera, y no con una línea fina', () => {
    // jsdom no calcula estilos de una hoja de CSS externa: se lee el fuente.
    const css = readFileSync(join(process.cwd(), 'src/index.css'), 'utf8')
    const bloque = (selector: string) => {
      const desde = css.indexOf(`${selector} {`)
      expect(desde, `falta ${selector}`).toBeGreaterThan(-1)
      return css.slice(desde, css.indexOf('}', desde))
    }
    const pantalla = bloque('\n.grilla-diagonal')
    expect(pantalla).toContain('background-color: var(--destructive)')
    // Sin la diagonal de esquina a esquina.
    expect(css.slice(css.indexOf('La grilla de una zona'))).not.toMatch(/linear-gradient/)
    // En oscuro, un rojo mezclado con el fondo y no el claro del texto.
    expect(bloque('.dark .grilla-diagonal')).toContain('color-mix(')
    // En papel, rojo sólido que se imprime.
    const papel = bloque('  .hoja-grilla .grilla-diagonal,\n  .dark .hoja-grilla .grilla-diagonal')
    expect(papel).toMatch(/background-color: #c00000/)
    expect(papel).toContain('print-color-adjust: exact')
  })

  it('la diagonal es la misma en la hoja para el papel, y tampoco se puede abrir', () => {
    montar({ paraPapel: true, deporte: 'futbol', tabla: { ...TABLA, con_sets: false } })
    const diagonales = document.querySelectorAll('td.grilla-diagonal')
    expect(diagonales).toHaveLength(PAREJAS.length)
    for (const celda of diagonales) {
      expect(celda).toHaveAttribute('aria-hidden', 'true')
      expect(celda.textContent).toBe('')
    }
  })

  it('el casillero abre el partido, de cualquiera de los dos lados', async () => {
    const onAbrir = montar()
    await userEvent.click(
      screen.getByRole('button', { name: 'Echeverría / Fuentes contra Aguirre / Bustos: 6-2' }),
    )
    await userEvent.click(
      screen.getByRole('button', { name: 'Aguirre / Bustos contra Echeverría / Fuentes: 2-6' }),
    )
    expect(onAbrir.mock.calls.map(([p]) => p.id)).toEqual([11, 11])
  })

  it('sin botones cuando es para el papel', () => {
    montar({ paraPapel: true })
    expect(screen.queryAllByRole('button')).toHaveLength(0)
    expect(screen.getAllByText('6-4').length).toBeGreaterThan(0)
  })
})

describe('las columnas de posiciones', () => {
  it('traen los ganados, las diferencias y el puesto', () => {
    montar()
    const filaDe = (nombre: string) =>
      screen.getAllByText(nombre).map((e) => e.closest('tr')!).find((tr) => tr.querySelector('th[scope=row]'))!
    // La 3 va primera: 1 ganado, +1 en sets, +4 en games, puesto 1.
    expect(within(filaDe('Echeverría / Fuentes')).getAllByRole('cell').map((c) => c.textContent)).toEqual(
      expect.arrayContaining(['1', '+1', '+4']),
    )
    const puestos = (n: string) => {
      const celdas = within(filaDe(n)).getAllByRole('cell')
      return celdas[celdas.length - 1].textContent
    }
    expect(puestos('Echeverría / Fuentes')).toBe('1')
    expect(puestos('Aguirre / Bustos')).toBe('2')
    expect(puestos('Cabrera / Domínguez')).toBe('3')
  })

  it('en fútbol no hay columna de sets', () => {
    montar({ tabla: { ...TABLA, con_sets: false } })
    expect(screen.queryByRole('columnheader', { name: 'Sets' })).toBeNull()
    expect(screen.getByRole('columnheader', { name: 'Dif' })).toBeInTheDocument()
  })

  it('🔴 en fútbol la columna son los puntos (Pts) y no los partidos ganados (PG)', () => {
    // La tabla de fútbol se ordena por puntos (ganar 3, empatar 1): con PG se
    // vería un equipo de 0 PG y 2 empates arriba de otro con 0 PG y 2 derrotas
    // sin explicación. La grilla muestra lo MISMO que `TablaDePosiciones`.
    const futbol: TablaDeZona = {
      zona_id: 7, nombre: 'Zona A', con_sets: false, completa: false,
      filas: [
        { ...fila(3, 2, 1, 0, 2), empatados: 1, perdidos: 0, puntos: 4 },
        { ...fila(1, 2, 0, 0, 0), empatados: 2, perdidos: 0, puntos: 2 },
        { ...fila(2, 2, 0, 0, -2), empatados: 0, perdidos: 2, puntos: 0 },
      ],
    }
    montar({ tabla: futbol, deporte: 'futbol' })
    expect(screen.getByRole('columnheader', { name: 'Pts' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'PG' })).toBeNull()
    const derecha = (nombre: string) => {
      const tr = screen.getAllByText(nombre).map((e) => e.closest('tr')!).find((t) => t.querySelector('th[scope=row]'))!
      return within(tr).getAllByRole('cell').slice(-3).map((c) => c.textContent)
    }
    // Pts, Dif, Pos. Los empates cuentan: el de 0 PG y 2 empates tiene 2 puntos.
    expect(derecha('Echeverría / Fuentes')).toEqual(['4', '+2', '1'])
    expect(derecha('Aguirre / Bustos')).toEqual(['2', '0', '2'])
    expect(derecha('Cabrera / Domínguez')).toEqual(['0', '-2', '3'])
  })

  it('en pádel y tenis queda PG, Sets, Games y Pos.', () => {
    montar({ deporte: 'padel' })
    const encabezados = screen.getAllByRole('columnheader').map((h) => h.textContent)
    expect(encabezados.slice(-4)).toEqual(['PG', 'Sets', 'Games', 'Pos.'])
    expect(screen.queryByRole('columnheader', { name: 'Pts' })).toBeNull()
  })

  it('no inventa un puesto para la pareja que todavía no jugó', () => {
    const sinJugar: TablaDeZona = {
      ...TABLA, filas: TABLA.filas.map((f) => ({ ...f, jugados: 0, ganados: 0, perdidos: 0 })),
    }
    montar({ tabla: sinJugar, partidos: [] })
    const celdas = Array.from(document.querySelectorAll('tbody tr')).map(
      (tr) => (tr.lastElementChild as HTMLElement).textContent,
    )
    expect(celdas).toEqual(['', '', ''])
  })

  it('resalta a los que clasifican a llaves', () => {
    montar({ clasifican: 1 })
    const resaltadas = Array.from(document.querySelectorAll('tbody td.bg-primary\\/10'))
    expect(resaltadas.map((c) => c.textContent)).toEqual(['1'])
  })
})

describe('el campeón de la zona', () => {
  it('aparece con la zona terminada en un torneo que termina en las zonas', () => {
    montar({ tabla: { ...TABLA, completa: true }, terminaEnZonas: true })
    expect(screen.getByText('Campeón de Zona A: Echeverría / Fuentes')).toBeInTheDocument()
  })

  it('no aparece con la zona a medias', () => {
    montar({ terminaEnZonas: true })
    expect(screen.queryByText(/Campeón de/)).toBeNull()
  })

  it('ni con llaves: el campeón sale de la final', () => {
    montar({ tabla: { ...TABLA, completa: true }, terminaEnZonas: false })
    expect(screen.queryByText(/Campeón de/)).toBeNull()
  })
})

describe('las grillas del torneo', () => {
  const TORNEO = {
    id: 1, sucursal_id: 1, nombre: 'Americano', deporte: 'padel', formato: 'zonas',
    estado: 'sorteado', desde: '2026-10-10', hasta: '2026-10-11', sets_para_ganar: 1,
    games_por_set: 6, cantidad_zonas: 2, clasifican_por_zona: null, termina_en_zonas: true,
    categoria: 'Caballeros 5ta', evento_id: null, semilla: 5, observaciones: null,
  } as Torneo
  const OTRA_ZONA: TablaDeZona = {
    zona_id: 8, nombre: 'Zona B', con_sets: true, completa: false,
    filas: [fila(1, 0, 0, 0, 0)].map((f) => ({ ...f, nombre: 'Gómez / Herrera', competidor_id: 9 })),
  }

  afterEach(() => vi.restoreAllMocks())

  it('una liga —una sola tabla, sin zona— también tiene su grilla', () => {
    const liga: TablaDeZona = { ...TABLA, zona_id: null, nombre: null }
    const deLaLiga = PARTIDOS.map((p) => ({ ...p, zona_id: null, zona: null }))
    render(
      <GrillasDelTorneo
        torneo={{ ...TORNEO, formato: 'liga', termina_en_zonas: false, cantidad_zonas: null } as Torneo}
        tablas={[liga]}
        partidos={deLaLiga}
        onAbrir={vi.fn()}
      />,
    )
    expect(screen.getByText('Zona única')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Aguirre / Bustos contra Cabrera / Domínguez: 6-4' }),
    ).toBeInTheDocument()
    // Con una sola tabla no hace falta «imprimir todas» y «imprimir esta zona».
    expect(screen.getAllByRole('button', { name: /Imprimir/ })).toHaveLength(1)
  })

  it('titula con el torneo y la categoría, y arma una grilla por zona', () => {
    render(
      <GrillasDelTorneo
        torneo={TORNEO}
        tablas={[TABLA, OTRA_ZONA]}
        partidos={PARTIDOS}
        onAbrir={vi.fn()}
      />,
    )
    expect(
      screen.getByRole('heading', { name: 'Americano · Caballeros 5ta' }),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('table')).toHaveLength(2)
    // Los partidos de la zona A no se cuelan en la B.
    const grillaB = screen.getAllByRole('table')[1]
    expect(within(grillaB).queryByRole('button', { name: /contra/ })).toBeNull()
  })

  it('🔴 el texto de ayuda nombra a quienes juegan según el deporte', () => {
    const de = (deporte: string, con_sets = false) => {
      const { unmount } = render(
        <GrillasDelTorneo
          torneo={{ ...TORNEO, deporte } as Torneo}
          tablas={[{ ...TABLA, con_sets }]}
          partidos={PARTIDOS}
          onAbrir={vi.fn()}
        />,
      )
      const ayuda = screen.getByText(/Cada casillero es el resultado/).textContent
      const caption = document.querySelector('caption')?.textContent
      unmount()
      return { ayuda, caption }
    }
    const padel = de('padel', true)
    expect(padel.ayuda).toContain('de la pareja de la fila contra la de la columna')
    expect(padel.caption).toContain('cada pareja de la fila contra la de la columna')
    expect(de('tenis', true).ayuda).toContain('de la pareja')

    for (const deporte of ['futbol', 'basquet', 'voley', 'hockey']) {
      const { ayuda, caption } = de(deporte)
      expect(ayuda).toContain('del equipo de la fila contra el de la columna')
      expect(ayuda).not.toContain('pareja')
      expect(caption).toContain('cada equipo de la fila contra el de la columna')
    }
    // Ante la duda, «competidor».
    expect(de('otro').ayuda).toContain('del competidor de la fila contra el de la columna')
  })

  it('imprimir arma la hoja de la zona elegida con el título y la manda a la impresora', async () => {
    // Se mide DENTRO de `print()`: es el único momento en que la hoja existe.
    let titulo = ''
    let tablas = -1
    let texto = ''
    const imprimir = vi.spyOn(window, 'print').mockImplementation(() => {
      const hoja = document.getElementById('hoja-impresa')
      titulo = hoja?.querySelector('h1')?.textContent ?? ''
      tablas = hoja?.querySelectorAll('table').length ?? -1
      texto = hoja?.textContent ?? ''
    })
    render(
      <GrillasDelTorneo
        torneo={TORNEO}
        tablas={[TABLA, OTRA_ZONA]}
        partidos={PARTIDOS}
        onAbrir={vi.fn()}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Imprimir Zona B' }))
    await vi.waitFor(() => expect(imprimir).toHaveBeenCalledTimes(1))

    expect(titulo).toBe('Americano · Caballeros 5ta')
    expect(tablas).toBe(1)
    expect(texto).toContain('Zona B')
    expect(texto).not.toContain('Zona A')
    expect(texto).toContain('Un set a 6 games')
    // Terminó de imprimir: la hoja se desmonta.
    await vi.waitFor(() => expect(document.getElementById('hoja-impresa')).toBeNull())
  })

  it('«Imprimir todas» arma una hoja por zona', async () => {
    let paginas = 0
    vi.spyOn(window, 'print').mockImplementation(() => {
      paginas = document.querySelectorAll('#hoja-impresa .grilla-pagina').length
    })
    render(
      <GrillasDelTorneo
        torneo={TORNEO}
        tablas={[TABLA, OTRA_ZONA]}
        partidos={PARTIDOS}
        onAbrir={vi.fn()}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /Imprimir todas/ }))
    await vi.waitFor(() => expect(paginas).toBe(2))
  })
})
