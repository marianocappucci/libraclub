/**
 * La agenda en un nodo sin conexión (libra-ui ADR-094, libraclub ADR-022): las reservas dadas en el club sin conexión se ven en la
 * grilla con «Sin subir al central» (id negativo), y las que chocaron con «En conflicto».
 *
 * 🔴 `provisoria` es OTRA cosa en LibraClub: el turno retenido esperando el pago del portal. Esa no lleva la etiqueta del nodo.
 */
import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Agenda } from './Agenda'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', name: 'Ana', role: 'staff' }, loading: false }),
}))

vi.mock('@/context/SucursalContext', () => ({
  useSucursal: () => ({ actual: 1, sucursales: [], elegir: vi.fn(), cargando: false }),
}))

const CANCHA = {
  id: 1, sucursal_id: 1, nombre: 'Cancha 1', deporte: 'padel',
  duracion_turno_min: 60, techada: true, iluminacion: true, superficie: null,
  orden: 1, activa: true, observaciones: null,
}

function turno(hora: string, reservaId: number, estado: string, cliente: string) {
  return {
    comienza_at: `2026-08-31T${hora}:00-03:00`, termina_at: `2026-08-31T${hora}:59-03:00`,
    libre: false, precio: '11000.00', reserva_id: reservaId, estado, cliente, motivo: null, cobrado: false,
  }
}

const SEMANA = {
  desde: '2026-08-31',
  canchas: {
    '1': {
      '2026-08-31': [
        turno('18', -48213, 'confirmada', 'Dada en el club'),
        turno('19', 7, 'provisoria', 'Esperando pago'),
        turno('20', 8, 'confirmada', 'Reserva normal'),
        turno('21', 9, 'en_conflicto', 'Chocó'),
      ],
    },
  },
}

function json(cuerpo: unknown) {
  return new Response(JSON.stringify(cuerpo), { status: 200, headers: { 'content-type': 'application/json' } })
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const u = String(url)
    if (u.includes('/api/canchas')) return Promise.resolve(json([CANCHA]))
    if (u.includes('/api/disponibilidad/semana')) return Promise.resolve(json(SEMANA))
    if (u.includes('/api/reservas-en-conflicto')) return Promise.resolve(json([]))
    return Promise.resolve(json(null))
  }))
})

/** El casillero de ese cliente, entero (es un botón). */
const casillero = (cliente: string) => screen.getByText(cliente).closest('button') as HTMLElement

describe('las etiquetas del nodo en la grilla de la agenda', () => {
  it('🔴 la reserva de id negativo lleva «Sin subir al central», y su nombre accesible lo dice', async () => {
    render(<Agenda />)
    await screen.findByText('Dada en el club')

    expect(within(casillero('Dada en el club')).getByText('Sin subir al central')).toBeInTheDocument()
    expect(casillero('Dada en el club')).toHaveAccessibleName(/sin subir al central/)
  })

  it('🔴 la que está en conflicto lleva «En conflicto»', async () => {
    render(<Agenda />)
    await screen.findByText('Chocó')

    expect(within(casillero('Chocó')).getByText('En conflicto')).toBeInTheDocument()
    expect(casillero('Chocó')).toHaveAccessibleName(/en conflicto/)
  })

  it('🔴 una reserva normal no lleva etiqueta', async () => {
    render(<Agenda />)
    await screen.findByText('Reserva normal')

    expect(within(casillero('Reserva normal')).queryByText(/Sin subir|En conflicto/)).toBeNull()
    expect(casillero('Reserva normal')).not.toHaveAccessibleName(/sin subir|conflicto/)
  })

  it('🔴 una `provisoria` del portal (esperando el pago) no se confunde con una sin subir', async () => {
    render(<Agenda />)
    await screen.findByText('Esperando pago')

    expect(within(casillero('Esperando pago')).queryByText(/Sin subir|En conflicto/)).toBeNull()
    // Y la etiqueta del nodo aparece una sola vez en toda la grilla: la de id negativo.
    expect(screen.getAllByText('Sin subir al central')).toHaveLength(1)
  })

  it('el id negativo no se muestra como un número de reserva en ninguna parte', async () => {
    render(<Agenda />)
    await screen.findByText('Dada en el club')
    expect(document.body.textContent).not.toMatch(/-48213/)
  })
})
