import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Evento } from '@/lib/api'
import { FormularioDeTorneo } from './FormularioDeTorneo'

/**
 * El formulario de un torneo arma tres decisiones del americano que el backend
 * valida con CHECKs y 422: cómo se juega el partido, qué pasa después de las
 * zonas y de qué categoría es. Estos tests miran **lo que viaja**, que es donde
 * se rompe: un fútbol con `games_por_set`, o un torneo sin llaves que sigue
 * mandando `clasifican_por_zona`, es un 422 que el operador no entiende.
 */

let llamadas: { url: string; metodo: string; cuerpo: Record<string, unknown> }[]

beforeEach(() => {
  llamadas = []
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    llamadas.push({
      url,
      metodo: init?.method ?? 'GET',
      cuerpo: init?.body ? JSON.parse(String(init.body)) : {},
    })
    return { ok: true, status: 201, json: async () => ({ id: 1 }) } as Response
  })
})

afterEach(() => vi.unstubAllGlobals())

const EVENTO: Evento = {
  id: 3, sucursal_id: 1, nombre: 'Americano de primavera', desde: '2026-10-10',
  hasta: '2026-10-11', observaciones: null, cancha_ids: [],
}

function abrir(evento: Evento | null = null) {
  const onCreado = vi.fn()
  render(
    <FormularioDeTorneo
      abierto
      sucursalId={1}
      evento={evento}
      onCerrar={vi.fn()}
      onCreado={onCreado}
    />,
  )
  return onCreado
}

async function crear(nombre: string) {
  const campo = screen.getByLabelText('Nombre')
  await userEvent.clear(campo)
  await userEvent.type(campo, nombre)
  await userEvent.click(screen.getByRole('button', { name: /^Crear/ }))
  await waitFor(() => expect(llamadas.some((l) => l.metodo === 'POST')).toBe(true))
  return llamadas.find((l) => l.metodo === 'POST')!.cuerpo
}

describe('cómo se juega cada partido', () => {
  it('en pádel arranca al mejor de 3 sets a 6 games', async () => {
    abrir()
    expect(screen.getByRole('radio', { name: /Al mejor de 3 sets/ })).toBeChecked()
    const cuerpo = await crear('Apertura')
    expect(cuerpo.sets_para_ganar).toBe(2)
    expect(cuerpo.games_por_set).toBe(6)
  })

  it('un set a 9 games viaja como un set y 9 games', async () => {
    abrir()
    await userEvent.click(screen.getByRole('radio', { name: /Un set a 9 games/ }))
    const cuerpo = await crear('Relámpago')
    expect(cuerpo.sets_para_ganar).toBe(1)
    expect(cuerpo.games_por_set).toBe(9)
  })

  it('un set a 6 games viaja como un set y 6 games', async () => {
    abrir()
    await userEvent.click(screen.getByRole('radio', { name: /Un set a 6 games/ }))
    const cuerpo = await crear('Relámpago')
    expect([cuerpo.sets_para_ganar, cuerpo.games_por_set]).toEqual([1, 6])
  })

  it('🔴 en fútbol no viajan los games, que el backend rechaza', async () => {
    abrir()
    await userEvent.click(screen.getByRole('radio', { name: /Un set a 9 games/ }))
    await userEvent.selectOptions(screen.getByLabelText('Deporte'), 'futbol')
    // El selector de sets y games es de pádel y de tenis: en fútbol se vuelve el
    // campo numérico de siempre.
    expect(screen.queryByRole('radio', { name: /Un set a 9 games/ })).toBeNull()
    const cuerpo = await crear('Liga')
    expect(cuerpo.deporte).toBe('futbol')
    expect(cuerpo.games_por_set).toBeNull()
    expect(cuerpo.sets_para_ganar).toBe(1)
  })
})

describe('después de las zonas', () => {
  async function porZonas() {
    await userEvent.click(screen.getByRole('radio', { name: /Por zonas/ }))
  }

  it('por defecto pasan a llaves los dos primeros', async () => {
    abrir()
    await porZonas()
    expect(screen.getByRole('radio', { name: /Pasan a llaves/ })).toBeChecked()
    const cuerpo = await crear('Con llaves')
    expect(cuerpo.formato).toBe('zonas')
    expect(cuerpo.cantidad_zonas).toBe(2)
    expect(cuerpo.clasifican_por_zona).toBe(2)
    expect(cuerpo.termina_en_zonas).toBe(false)
  })

  it('se puede elegir que pase sólo el primero', async () => {
    abrir()
    await porZonas()
    await userEvent.selectOptions(screen.getByLabelText('Cuántos pasan por zona'), '1')
    const cuerpo = await crear('Con llaves')
    expect(cuerpo.clasifican_por_zona).toBe(1)
  })

  it('🔑 «termina en las zonas» manda el booleano y NO los clasificados', async () => {
    abrir()
    await porZonas()
    await userEvent.click(screen.getByRole('radio', { name: /Termina en las zonas/ }))
    expect(screen.queryByLabelText('Cuántos pasan por zona')).toBeNull()
    const cuerpo = await crear('Sin llaves')
    expect(cuerpo.termina_en_zonas).toBe(true)
    expect(cuerpo.clasifican_por_zona).toBeNull()
    expect(cuerpo.cantidad_zonas).toBe(2)
  })

  it('volver a eliminación limpia lo de las zonas, que el backend rechaza', async () => {
    abrir()
    await porZonas()
    await userEvent.click(screen.getByRole('radio', { name: /Termina en las zonas/ }))
    await userEvent.click(screen.getByRole('radio', { name: /Eliminación directa/ }))
    const cuerpo = await crear('Llaves')
    expect(cuerpo.formato).toBe('eliminacion')
    expect(cuerpo.cantidad_zonas).toBeNull()
    expect(cuerpo.clasifican_por_zona).toBeNull()
    expect(cuerpo.termina_en_zonas).toBe(false)
  })

  it('la opción de las zonas sólo existe en el formato por zonas', () => {
    abrir()
    expect(screen.queryByRole('radio', { name: /Termina en las zonas/ })).toBeNull()
  })
})

describe('la categoría', () => {
  it('un torneo suelto la lleva si se la cargan, y es opcional', async () => {
    abrir()
    await userEvent.type(screen.getByLabelText(/Categoría/), 'Damas 5ta')
    const cuerpo = await crear('Apertura')
    expect(cuerpo.categoria).toBe('Damas 5ta')
    expect(cuerpo.evento_id).toBeNull()
  })

  it('sin categoría, el botón igual se habilita', async () => {
    abrir()
    await userEvent.type(screen.getByLabelText('Nombre'), 'Apertura')
    expect(screen.getByRole('button', { name: 'Crear torneo' })).toBeEnabled()
  })
})

describe('una categoría de un evento', () => {
  it('lleva el evento en el título y hereda sus fechas sin pedirlas', () => {
    abrir(EVENTO)
    expect(
      screen.getByRole('heading', { name: 'Nueva categoría de Americano de primavera' }),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText('Desde')).toBeNull()
    expect(screen.getByText(/Todas las categorías juegan los mismos días/)).toBeInTheDocument()
  })

  it('exige la categoría, y con ella propone el nombre', async () => {
    abrir(EVENTO)
    const crearBoton = screen.getByRole('button', { name: 'Crear categoría' })
    expect(crearBoton).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Categoría/), 'Mixto')
    expect(screen.getByLabelText('Nombre')).toHaveValue('Americano de primavera — Mixto')
    expect(crearBoton).toBeEnabled()
  })

  it('si el nombre se tocó a mano, la categoría ya no lo pisa', async () => {
    abrir(EVENTO)
    await userEvent.type(screen.getByLabelText('Nombre'), 'Mi nombre')
    await userEvent.type(screen.getByLabelText(/Categoría/), 'Mixto')
    expect(screen.getByLabelText('Nombre')).toHaveValue('Mi nombre')
  })

  it('manda el evento, la categoría y las fechas del evento', async () => {
    abrir(EVENTO)
    await userEvent.type(screen.getByLabelText(/Categoría/), 'Caballeros 6ta')
    await userEvent.click(screen.getByRole('button', { name: 'Crear categoría' }))
    await waitFor(() => expect(llamadas.some((l) => l.metodo === 'POST')).toBe(true))
    const cuerpo = llamadas.find((l) => l.metodo === 'POST')!.cuerpo
    expect(cuerpo.evento_id).toBe(3)
    expect(cuerpo.categoria).toBe('Caballeros 6ta')
    expect(cuerpo.desde).toBe('2026-10-10')
    expect(cuerpo.hasta).toBe('2026-10-11')
    expect(cuerpo.nombre).toBe('Americano de primavera — Caballeros 6ta')
  })
})
