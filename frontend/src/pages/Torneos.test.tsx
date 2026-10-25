import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * La lista de torneos con los eventos arriba. Lo que decide:
 *
 * 1. que un evento aparezca con cuántas categorías tiene y lleve a su pantalla;
 * 2. que sin eventos la sección no exista (la pantalla es la de siempre);
 * 3. que cada torneo diga su categoría y de qué evento es;
 * 4. que crear un evento sea del admin.
 */

const listar = vi.fn()
const listarEventos = vi.fn()
const listarCanchas = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    torneos: { ...(real.torneos as object), listar },
    eventos: { ...(real.eventos as object), listar: listarEventos },
    canchas: { ...(real.canchas as object), listar: listarCanchas },
  }
})

vi.mock('@/context/SucursalContext', () => ({
  useSucursal: () => ({ actual: 1 }),
}))

let ROL = 'admin'
vi.mock('@/context/AuthContext', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    useAuth: () => ({ user: { role: ROL, name: 'Quien sea' }, loading: false }),
  }
})

const { Torneos } = await import('./Torneos')

const TORNEO = {
  id: 1, sucursal_id: 1, nombre: 'Americano — Damas', deporte: 'padel',
  formato: 'zonas' as const, estado: 'sorteado' as const, desde: '2026-10-10',
  hasta: '2026-10-11', sets_para_ganar: 1, games_por_set: 6, cantidad_zonas: 2,
  clasifican_por_zona: null, termina_en_zonas: true, categoria: 'Damas', evento_id: 3,
  semilla: 5, observaciones: null, competidores: 6, partidos: 6, jugados: 0,
  sin_programar: 6, campeon: null, evento: 'Americano de primavera',
}

beforeEach(() => {
  ROL = 'admin'
  listar.mockReset().mockResolvedValue([TORNEO])
  listarEventos.mockReset().mockResolvedValue([
    { id: 3, sucursal_id: 1, nombre: 'Americano de primavera', desde: '2026-10-10',
      hasta: '2026-10-11', observaciones: null, cancha_ids: [], categorias: 2 },
  ])
  listarCanchas.mockReset().mockResolvedValue([])
})

function montar() {
  return render(
    <MemoryRouter>
      <Torneos />
    </MemoryRouter>,
  )
}

describe('la lista de torneos', () => {
  it('muestra el evento con sus categorías y lleva a su pantalla', async () => {
    montar()
    const seccion = await screen.findByRole('region', { name: 'Eventos' })
    const vinculo = within(seccion).getByRole('link', { name: /Americano de primavera/ })
    expect(vinculo).toHaveAttribute('href', '/torneos/eventos/3')
    expect(within(vinculo).getByText(/2 categorías/)).toBeInTheDocument()
  })

  it('sin eventos no hay sección', async () => {
    listarEventos.mockResolvedValue([])
    montar()
    await screen.findByText('Americano — Damas')
    expect(screen.queryByRole('region', { name: 'Eventos' })).not.toBeInTheDocument()
  })

  it('cada torneo dice su categoría, su evento y el formato sin llaves', async () => {
    montar()
    const descripcion = await screen.findByText(/Por zonas, sin llaves/)
    expect(descripcion).toHaveTextContent('Damas')
    expect(descripcion).toHaveTextContent('Americano de primavera')
  })

  it('el admin crea eventos y torneos', async () => {
    montar()
    await screen.findByText('Americano — Damas')
    expect(screen.getByRole('button', { name: /Nuevo evento/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Nuevo torneo/ })).toBeInTheDocument()
  })

  it('el mostrador no crea ninguno de los dos', async () => {
    ROL = 'staff'
    montar()
    await screen.findByText('Americano — Damas')
    expect(screen.queryByRole('button', { name: /Nuevo evento/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Nuevo torneo/ })).not.toBeInTheDocument()
  })
})
