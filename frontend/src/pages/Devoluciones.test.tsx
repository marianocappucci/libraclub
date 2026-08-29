import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Devoluciones } from './Devoluciones'

// El rol se cambia por test: ver es de staff, reintentar es de admin.
const rol = { valor: 'admin' }

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', name: 'Ana', role: rol.valor }, loading: false }),
}))

const PENDIENTE = {
  id: 7,
  reserva_id: 42,
  monto: '5000.00',
  referencia: 'libraclub-42-abc',
  payment_id: 'mp-123',
  detalle_devolucion: 'Falta devolver la seña: la instancia no tiene MercadoPago configurado.',
  created_at: '2026-08-29T18:00:00-03:00',
}

let llamadas: { url: string; metodo: string }[]
let pendientes: (typeof PENDIENTE)[]

beforeEach(() => {
  rol.valor = 'admin'
  llamadas = []
  pendientes = [PENDIENTE]
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    llamadas.push({ url, metodo: init?.method ?? 'GET' })
    if (init?.method === 'POST') {
      // El reintento contesta 200 aunque siga pendiente: el texto ES el
      // resultado. Acá se simula el que sí funciona, y la lista queda vacía.
      pendientes = []
      return { ok: true, status: 200, json: async () => ({
        pago_id: 7, estado: 'devuelto', detalle: 'Se devolvió la seña.',
      }) } as Response
    }
    return { ok: true, status: 200, json: async () => pendientes } as Response
  })
})

afterEach(() => vi.unstubAllGlobals())

function abrir() {
  return render(<MemoryRouter><Devoluciones /></MemoryRouter>)
}

describe('devoluciones pendientes', () => {
  it('🔴 muestra la deuda y POR QUÉ sigue pendiente', async () => {
    // Sin el motivo en la fila, la respuesta a «¿por qué no se devolvió?» es
    // mirar los logs del contenedor.
    abrir()

    expect(await screen.findByText(/#42/)).toBeInTheDocument()
    expect(screen.getByText(/no tiene MercadoPago configurado/i)).toBeInTheDocument()
  })

  it('reintentar muestra el resultado y saca la fila de la lista', async () => {
    abrir()
    await screen.findByText(/#42/)

    await userEvent.click(screen.getByRole('button', { name: /reintentar/i }))

    await waitFor(() =>
      expect(screen.getByText('Se devolvió la seña.')).toBeInTheDocument(),
    )
    expect(llamadas.filter((l) => l.metodo === 'POST')).toEqual([
      { url: '/api/devoluciones/7/reintentar', metodo: 'POST' },
    ])
    expect(await screen.findByText(/No hay devoluciones pendientes/i)).toBeInTheDocument()
  })

  it('🔑 el encargado ve la deuda pero no puede devolver', async () => {
    // Mover plata hacia afuera es del dueño; contestarle al jugador que llama,
    // del encargado. El backend lo exige igual — la pantalla sólo evita ofrecer
    // un botón que va a dar 403.
    rol.valor = 'staff'
    abrir()

    expect(await screen.findByText(/#42/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /reintentar/i })).toBeNull()
  })
})
