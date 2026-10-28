/**
 * El detalle de una reserva `pendiente_pago` dice hasta cuándo tiene el jugador para pagar la seña (libraclub ADR-029, 2026-10-28).
 *
 * El dato es el `vence_at` que manda el backend (24 h desde que se tomó, y como mucho 2 h antes del turno): la pantalla no hace
 * ninguna cuenta. Las anteriores al plazo no lo tienen y lo dicen, en vez de callar: una reserva que no se libera sola es algo que
 * el mostrador tiene que saber.
 */
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DetalleDeReserva } from './DetalleDeReserva'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', name: 'Ana', role: 'staff' }, loading: false }),
}))

function json(cuerpo: unknown) {
  return new Response(JSON.stringify(cuerpo), { status: 200, headers: { 'content-type': 'application/json' } })
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((ruta: string) => {
    const u = String(ruta)
    if (u.includes('/consumos')) return Promise.resolve(json({ total: 0, lineas: [] }))
    if (u.includes('/mp/estado')) return Promise.resolve(json({ disponible: false, auto_facturar: false }))
    if (u.includes('/caja/medios-pago')) return Promise.resolve(json([]))
    return Promise.resolve(json(null))
  }))
})

const CANCHA = {
  id: 1, sucursal_id: 1, nombre: 'Cancha 1', deporte: 'padel',
  duracion_turno_min: 90, techada: true, iluminacion: true, superficie: null,
  orden: 1, activa: true, observaciones: null,
}

function montar(estado: string, venceAt: string | null) {
  return render(
    <DetalleDeReserva
      abierto cancha={CANCHA}
      turno={{
        comienza_at: '2026-09-01T20:00:00-03:00', termina_at: '2026-09-01T21:30:00-03:00',
        libre: false, precio: '14000.00', reserva_id: 5, estado, cliente: 'Ana Gomez',
        motivo: null, cobrado: false, vence_at: venceAt,
      }}
      onCerrar={vi.fn()} onCambiada={vi.fn()}
    />,
  )
}

describe('el plazo de la seña en el detalle de la reserva', () => {
  it('una pendiente de pago dice hasta cuándo tiene para pagar', async () => {
    montar('pendiente_pago', '2026-09-01T10:00:00-03:00')

    expect(await screen.findByTestId('plazo-de-sena')).toHaveTextContent(
      'Tiene hasta el 01-09-2026 10:00 para pagar la seña',
    )
  })

  it('una pendiente de pago anterior al plazo dice que no vence sola', async () => {
    montar('pendiente_pago', null)

    expect(await screen.findByTestId('plazo-de-sena')).toHaveTextContent('Sin vencimiento')
  })

  it.each(['confirmada', 'provisoria', 'jugada'])('una reserva %s no muestra el plazo de la seña', async (estado) => {
    montar(estado, '2026-09-01T10:00:00-03:00')

    await screen.findByText('Reserva')
    expect(screen.queryByTestId('plazo-de-sena')).toBeNull()
  })
})
