import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Clientes } from './Clientes'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', name: 'Ana', role: 'staff' }, loading: false }),
}))

const CLIENTES = [
  { id: 7, nombre: 'Juan Pérez', telefono: null, email: null, documento: null, cuit: null,
    activo: true, acepta_avisos: true, observaciones: null },
  { id: 8, nombre: 'Ana Gómez', telefono: null, email: null, documento: null, cuit: null,
    activo: true, acepta_avisos: true, observaciones: null },
]

beforeEach(() => {
  vi.stubGlobal('fetch', async (url: string) => {
    if (url === '/api/clientes/ausentismo/reincidentes') {
      return { ok: true, status: 200, json: async () => ({
        umbral: 3, dias: 90,
        reincidentes: [{ cliente_id: 7, ausentes: 4, ultimo_ausente_at: '2026-09-05T20:00:00-03:00' }],
      }) } as Response
    }
    return { ok: true, status: 200, json: async () => CLIENTES } as Response
  })
})

afterEach(() => vi.unstubAllGlobals())

describe('clientes dados de alta sin conexión en el listado', () => {
  it('el de id negativo lleva la etiqueta «Provisorio» y los del central no', async () => {
    vi.stubGlobal('fetch', async (url: string) => {
      if (url === '/api/clientes/ausentismo/reincidentes') {
        return { ok: true, status: 200, json: async () => ({ umbral: 3, dias: 90, reincidentes: [] }) } as Response
      }
      return {
        ok: true, status: 200,
        json: async () => [{ ...CLIENTES[0], id: -2, nombre: 'Carla Nueva' }, CLIENTES[1]],
      } as Response
    })
    render(<MemoryRouter><Clientes /></MemoryRouter>)

    expect(await screen.findByText('Carla Nueva')).toBeInTheDocument()
    expect(screen.getAllByText('Provisorio')).toHaveLength(1)
    // Y se puede editar: la columna de acciones sigue ahí para las dos filas.
    expect(screen.getAllByRole('button', { name: /editar/i }).length).toBeGreaterThanOrEqual(2)
  })
})

describe('ausentismo en el listado de clientes', () => {
  it('marca al que viene faltando, con cuántas veces y la última', async () => {
    render(<MemoryRouter><Clientes /></MemoryRouter>)

    // La fecha en dd-mm-aaaa y en hora local: el 20:00 del 05 no se corre al 06.
    expect(await screen.findByText('4 ausencias · última 05-09-2026')).toBeInTheDocument()
  })

  it('al que no faltó no le pone nada', async () => {
    // 🔑 El control: una marca que saliera en todas las filas pasaría el test de
    // arriba sin decir nada sobre quién faltó.
    render(<MemoryRouter><Clientes /></MemoryRouter>)

    await screen.findByText('4 ausencias · última 05-09-2026')
    expect(screen.getAllByText(/ausencias/)).toHaveLength(1)
    expect(screen.getByText('Ana Gómez')).toBeInTheDocument()
  })
})
