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
    if (url === '/api/clientes-en-conflicto') return { ok: true, status: 200, json: async () => [] } as Response
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
      if (url === '/api/clientes-en-conflicto') return { ok: true, status: 200, json: async () => [] } as Response
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

describe('aviso de clientes por revisar (ADR-022, tercer addendum)', () => {
  const EDICION = {
    operacion_id: 'club-1:2', cliente_id: 7, cliente_nombre: 'Juan Pérez', recibida_at: null,
    campos: [], en_conflicto: 1, se_puede_resolver: true,
  }

  function responderCon(lista: unknown[]) {
    vi.stubGlobal('fetch', async (url: string) => {
      if (url === '/api/clientes-en-conflicto') return { ok: true, status: 200, json: async () => lista } as Response
      if (url === '/api/clientes/ausentismo/reincidentes') {
        return { ok: true, status: 200, json: async () => ({ umbral: 3, dias: 90, reincidentes: [] }) } as Response
      }
      return { ok: true, status: 200, json: async () => CLIENTES } as Response
    })
  }

  it('sin cambios que choquen no dibuja nada', async () => {
    responderCon([])
    render(<MemoryRouter><Clientes /></MemoryRouter>)
    await screen.findByText('Juan Pérez')
    expect(screen.queryByRole('status', { name: 'Clientes por revisar' })).toBeNull()
  })

  it('con uno, avisa y lleva a la lista', async () => {
    responderCon([EDICION])
    render(<MemoryRouter><Clientes /></MemoryRouter>)
    const aviso = await screen.findByRole('status', { name: 'Clientes por revisar' })
    expect(aviso).toHaveTextContent('Hay 1 cliente con cambios de la PC del club que chocan con los de la web.')
    expect(screen.getByRole('link', { name: 'Revisar' })).toHaveAttribute('href', '/clientes/conflictos')
  })

  it('con varios, cuenta', async () => {
    responderCon([EDICION, { ...EDICION, operacion_id: 'club-1:5' }])
    render(<MemoryRouter><Clientes /></MemoryRouter>)
    expect(await screen.findByText(/Hay 2 clientes con cambios/)).toBeInTheDocument()
  })

  it('los que ya no chocan también cuentan, y el aviso dice cuántos son de cada clase', async () => {
    responderCon([
      EDICION,
      { ...EDICION, operacion_id: 'club-1:5', en_conflicto: 0, ya_no_choca: true },
      { ...EDICION, operacion_id: 'club-1:7', en_conflicto: 0, ya_no_choca: true },
    ])
    render(<MemoryRouter><Clientes /></MemoryRouter>)
    const aviso = await screen.findByRole('status', { name: 'Clientes por revisar' })
    expect(aviso).toHaveTextContent(
      'Hay 3 clientes con cambios de la PC del club para revisar: 1 choca con los de la web y 2 ya no chocan y se pueden aplicar.',
    )
  })

  it('si sólo hay de los que ya no chocan, lo dice y sigue llevando a la lista', async () => {
    responderCon([{ ...EDICION, en_conflicto: 0, ya_no_choca: true }])
    render(<MemoryRouter><Clientes /></MemoryRouter>)
    const aviso = await screen.findByRole('status', { name: 'Clientes por revisar' })
    expect(aviso).toHaveTextContent('Hay 1 cliente con cambios de la PC del club que ya no choca con los de la web y se puede aplicar.')
    expect(screen.getByRole('link', { name: 'Revisar' })).toHaveAttribute('href', '/clientes/conflictos')
  })
})
