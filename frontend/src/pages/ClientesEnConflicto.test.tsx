/** La lista de clientes por revisar (ADR-022, tercer y cuarto addendum): qué datos chocan en cada uno, cuáles ya no chocan y a dónde lleva «Revisar». */
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ClientesEnConflicto } from './ClientesEnConflicto'

const EDICION = {
  operacion_id: 'club-1:2', cliente_id: 7, cliente_nombre: 'Juan Pérez', recibida_at: '2026-09-02T10:00:00-03:00',
  en_conflicto: 2, ya_no_choca: false, se_puede_resolver: true,
  campos: [
    { campo: 'telefono', etiqueta: 'Teléfono', estado: 'conflicto', antes: '111', web: '222', pc: '333' },
    { campo: 'email', etiqueta: 'Email', estado: 'conflicto', antes: null, web: 'w@x.com', pc: 'p@x.com' },
    { campo: 'documento', etiqueta: 'Documento', estado: 'se_aplica', antes: null, web: null, pc: '30123456' },
  ],
}

// La web volvió el teléfono al valor anterior: sigue en revisión pero ya no choca (cuarto addendum).
const YA_NO_CHOCA = {
  operacion_id: 'club-1:5', cliente_id: 9, cliente_nombre: 'Ana Gómez', recibida_at: '2026-09-03T10:00:00-03:00',
  en_conflicto: 0, ya_no_choca: true, se_puede_resolver: true,
  campos: [
    { campo: 'telefono', etiqueta: 'Teléfono', estado: 'se_aplica', antes: '111', web: '111', pc: '333' },
    { campo: 'email', etiqueta: 'Email', estado: 'igual', antes: null, web: 'a@x.com', pc: 'a@x.com' },
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

  it('la que chocaba se marca «Hay que elegir» y la que dejó de chocar «Ya no choca: se puede aplicar»', async () => {
    responder([EDICION, YA_NO_CHOCA])
    render(<MemoryRouter><ClientesEnConflicto /></MemoryRouter>)

    const juan = (await screen.findByText('Juan Pérez')).closest('li')!
    const ana = screen.getByText('Ana Gómez').closest('li')!
    expect(within(juan).getByText('Hay que elegir')).toBeInTheDocument()
    expect(within(juan).queryByText(/Ya no choca/)).toBeNull()
    expect(within(ana).getByText('Ya no choca: se puede aplicar')).toBeInTheDocument()
    expect(within(ana).queryByText('Hay que elegir')).toBeNull()
    // Dice qué se aplica (el email ya estaba igual, no se nombra) y lleva a su pantalla.
    expect(within(ana).getByText(/1 dato para aplicar: Teléfono/)).toBeInTheDocument()
    expect(within(ana).queryByText(/Email/)).toBeNull()
    expect(within(ana).getByRole('link', { name: 'Revisar' })).toHaveAttribute('href', '/clientes/conflictos/club-1%3A5')
  })

  it('si en la web ya está todo igual, lo dice', async () => {
    responder([{ ...YA_NO_CHOCA, campos: YA_NO_CHOCA.campos.map((c) => ({ ...c, estado: 'igual' })) }])
    render(<MemoryRouter><ClientesEnConflicto /></MemoryRouter>)
    expect(await screen.findByText(/Ya está todo igual en la web/)).toBeInTheDocument()
  })

  it('sin nada para revisar lo dice', async () => {
    responder([])
    render(<MemoryRouter><ClientesEnConflicto /></MemoryRouter>)
    expect(await screen.findByText('No hay cambios de clientes para revisar.')).toBeInTheDocument()
  })

  it('no habla en jerga', async () => {
    responder([EDICION, YA_NO_CHOCA])
    const { container } = render(<MemoryRouter><ClientesEnConflicto /></MemoryRouter>)
    await screen.findByText('Juan Pérez')
    expect(container.textContent).not.toMatch(/nodo|outbox|central|sincroniz/i)
  })
})
