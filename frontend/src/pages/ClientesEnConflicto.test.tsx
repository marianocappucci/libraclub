/** La lista de clientes por revisar (ADR-022, tercer addendum): qué datos chocan en cada uno y a dónde lleva «Revisar». */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ClientesEnConflicto } from './ClientesEnConflicto'

const EDICION = {
  operacion_id: 'club-1:2', cliente_id: 7, cliente_nombre: 'Juan Pérez', recibida_at: '2026-09-02T10:00:00-03:00',
  en_conflicto: 2, se_puede_resolver: true,
  campos: [
    { campo: 'telefono', etiqueta: 'Teléfono', estado: 'conflicto', antes: '111', web: '222', pc: '333' },
    { campo: 'email', etiqueta: 'Email', estado: 'conflicto', antes: null, web: 'w@x.com', pc: 'p@x.com' },
    { campo: 'documento', etiqueta: 'Documento', estado: 'se_aplica', antes: null, web: null, pc: '30123456' },
  ],
}

function responder(lista: unknown) {
  vi.stubGlobal('fetch', async () => ({ ok: true, status: 200, json: async () => lista }) as Response)
}

afterEach(() => vi.unstubAllGlobals())

describe('clientes por revisar', () => {
  it('dice cuáles son los datos que chocan en cada cliente y lleva a su pantalla', async () => {
    responder([EDICION])
    render(<MemoryRouter><ClientesEnConflicto /></MemoryRouter>)

    expect(await screen.findByText('Juan Pérez')).toBeInTheDocument()
    expect(screen.getByText(/2 datos para elegir: Teléfono, Email/)).toBeInTheDocument()
    expect(screen.queryByText(/Documento/)).toBeNull()
    expect(screen.getByRole('link', { name: 'Revisar' })).toHaveAttribute('href', '/clientes/conflictos/club-1%3A2')
  })

  it('sin nada para revisar lo dice', async () => {
    responder([])
    render(<MemoryRouter><ClientesEnConflicto /></MemoryRouter>)
    expect(await screen.findByText('No hay cambios de clientes para revisar.')).toBeInTheDocument()
  })

  it('no habla en jerga', async () => {
    responder([EDICION])
    const { container } = render(<MemoryRouter><ClientesEnConflicto /></MemoryRouter>)
    await screen.findByText('Juan Pérez')
    expect(container.textContent).not.toMatch(/nodo|outbox|central|sincroniz/i)
  })
})
