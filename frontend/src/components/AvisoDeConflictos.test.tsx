/**
 * El aviso de reservas en conflicto (ADR-022): lista cada una con la que ganó y deja resolverla.
 *
 * Lo que se mide: que sin conflictos no dibuje nada, que diga contra quién chocó, que mover y cancelar le peguen
 * a la API con lo que corresponde, que un 409 se vea con su texto, y que en el equipo del local se vea sin botones.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AvisoDeConflictos } from './AvisoDeConflictos'

const CONFLICTO = {
  reserva: {
    id: 12, cancha_id: 1, cliente_id: 5, estado: 'en_conflicto', origen: 'mostrador',
    comienza_at: '2026-09-01T20:00:00-03:00', termina_at: '2026-09-01T21:30:00-03:00',
    precio: '10000.00', sena: null, motivo: null, observaciones: null,
    conflicto_con_id: 9, estado_previo: 'confirmada',
  },
  cancha_nombre: 'Cancha 1',
  cliente_nombre: 'Juan Pérez',
  ganadora: {
    id: 9, estado: 'confirmada', origen: 'portal',
    comienza_at: '2026-09-01T20:00:00-03:00', termina_at: '2026-09-01T21:30:00-03:00',
    cliente_nombre: 'Ana Gómez',
  },
  se_puede_resolver: true,
}

function json(cuerpo: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(cuerpo), {
    status, headers: { 'content-type': 'application/json' },
  }))
}

let llamadas: { url: string; init?: RequestInit }[]

function responder(lista: unknown[], resolver?: () => Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    llamadas.push({ url: String(url), init })
    if (init?.method === 'POST') return resolver ? resolver() : json({ id: 12, estado: 'confirmada' })
    return json(lista)
  }))
}

beforeEach(() => {
  llamadas = []
})

describe('el aviso de reservas en conflicto', () => {
  it('sin conflictos no dibuja nada', async () => {
    responder([])
    const { container } = render(<AvisoDeConflictos sucursalId={1} />)
    await waitFor(() => expect(llamadas.length).toBeGreaterThan(0))
    expect(container).toBeEmptyDOMElement()
  })

  it('una respuesta que no es una lista tampoco lo rompe', async () => {
    vi.stubGlobal('fetch', vi.fn(() => json(null)))
    const { container } = render(<AvisoDeConflictos sucursalId={1} />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('dice quién reservó, cuándo y contra quién chocó', async () => {
    responder([CONFLICTO])
    render(<AvisoDeConflictos sucursalId={1} />)

    expect(await screen.findByText('Hay 1 reserva en conflicto')).toBeInTheDocument()
    expect(screen.getByText('Juan Pérez')).toBeInTheDocument()
    expect(screen.getByText(/Se quedó con la cancha Ana Gómez/)).toBeInTheDocument()
    expect(llamadas[0].url).toBe('/api/reservas-en-conflicto?sucursal_id=1')
  })

  it('cancelar le pega a la API y recarga la lista', async () => {
    const onResuelto = vi.fn()
    responder([CONFLICTO])
    render(<AvisoDeConflictos sucursalId={1} onResuelto={onResuelto} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Cancelar reserva' }))

    await waitFor(() => expect(onResuelto).toHaveBeenCalled())
    const post = llamadas.find((l) => l.init?.method === 'POST')!
    expect(post.url).toBe('/api/reservas-en-conflicto/12/resolver')
    expect(JSON.parse(String(post.init?.body))).toMatchObject({ accion: 'cancelar' })
  })

  it('mover manda el nuevo horario tal cual, sin zona: lo toma el servidor como hora del complejo', async () => {
    responder([CONFLICTO])
    render(<AvisoDeConflictos sucursalId={1} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Mover de horario' }))
    const campo = screen.getByLabelText(/Nuevo horario/)
    await userEvent.type(campo, '2026-09-01T22:00')
    await userEvent.click(screen.getByRole('button', { name: 'Mover' }))

    await waitFor(() => expect(llamadas.some((l) => l.init?.method === 'POST')).toBe(true))
    const post = llamadas.find((l) => l.init?.method === 'POST')!
    expect(JSON.parse(String(post.init?.body))).toEqual({ accion: 'mover', comienza_at: '2026-09-01T22:00' })
  })

  it('mover sin horario intenta el original (sirve si la que ganó se canceló)', async () => {
    responder([CONFLICTO])
    render(<AvisoDeConflictos sucursalId={1} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Mover de horario' }))
    await userEvent.click(screen.getByRole('button', { name: 'Mover' }))

    await waitFor(() => expect(llamadas.some((l) => l.init?.method === 'POST')).toBe(true))
    const post = llamadas.find((l) => l.init?.method === 'POST')!
    expect(JSON.parse(String(post.init?.body))).toEqual({ accion: 'mover' })
  })

  it('un 409 se ve con su texto y la reserva sigue en la lista', async () => {
    responder([CONFLICTO], () => json({ detail: 'La cancha ya tiene una reserva de 20:00 a 21:30 ese día.' }, 409))
    render(<AvisoDeConflictos sucursalId={1} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Cancelar reserva' }))

    expect(await screen.findByText(/La cancha ya tiene una reserva de 20:00 a 21:30/)).toBeInTheDocument()
    expect(screen.getByText('Juan Pérez')).toBeInTheDocument()
  })

  it('en el equipo del local se ve sin botones', async () => {
    responder([{ ...CONFLICTO, se_puede_resolver: false }])
    render(<AvisoDeConflictos sucursalId={1} />)

    expect(await screen.findByText(/Se resuelve desde el central/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancelar reserva' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Mover de horario' })).toBeNull()
  })
})
