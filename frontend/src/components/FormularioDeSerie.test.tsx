import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FormularioDeSerie } from './FormularioDeSerie'
import type { Cancha, Cliente } from '@/lib/api'

const CANCHA = {
  id: 3, sucursal_id: 1, nombre: 'Cancha 3', deporte: 'padel', duracion_turno_min: 90, techada: true,
  iluminacion: true, superficie: null, orden: 0, activa: true, observaciones: null,
} as Cancha

const JUAN = { id: 7, nombre: 'Juan Pérez', telefono: null } as Cliente

let llamadas: { url: string; metodo: string; cuerpo: Record<string, unknown> | null }[]

beforeEach(() => {
  llamadas = []
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    const metodo = init?.method ?? 'GET'
    llamadas.push({ url, metodo, cuerpo: init?.body ? JSON.parse(String(init.body)) : null })
    const body =
      url === '/api/clientes'
        ? { id: 99, nombre: 'Los Martes', telefono: null }
        : { serie: { cancha: 'Cancha 3', cliente: 'Los Martes' }, creadas: [], salteadas: [] }
    return { ok: true, status: 201, json: async () => body } as Response
  })
})

afterEach(() => vi.unstubAllGlobals())

describe('cancha fija: el cliente se da de alta en el mismo campo (ADR-071)', () => {
  it('crea el cliente en el panel, queda elegido y la serie sale con su id', async () => {
    const user = userEvent.setup()
    render(<FormularioDeSerie abierto canchas={[CANCHA]} clientes={[JUAN]} onCerrar={vi.fn()} onCreada={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: 'Agregar nuevo cliente' }))
    const panel = screen.getByRole('group', { name: 'Nuevo cliente' })
    await user.type(within(panel).getByLabelText(/nombre/i), 'Los Martes')
    await user.click(within(panel).getByRole('button', { name: 'Crear cliente' }))
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Nuevo cliente' })).toBeNull())

    expect(llamadas.find((l) => l.url === '/api/clientes' && l.metodo === 'POST')!.cuerpo).toEqual({
      nombre: 'Los Martes', telefono: null, email: null,
    })
    expect(screen.getByRole('combobox', { name: /cliente/i })).toHaveValue('Los Martes')

    await user.click(screen.getByRole('button', { name: 'Crear y generar turnos' }))
    await waitFor(() => expect(llamadas.some((l) => l.url.startsWith('/api/reservas/series') && l.metodo === 'POST')).toBe(true))
    expect(llamadas.find((l) => l.url.startsWith('/api/reservas/series') && l.metodo === 'POST')!.cuerpo).toMatchObject({
      cliente_id: 99, cancha_id: 3,
    })
  })

  it('sin clientes cargados el formulario igual deja dar uno de alta', async () => {
    render(<FormularioDeSerie abierto canchas={[CANCHA]} clientes={[]} onCerrar={vi.fn()} onCreada={vi.fn()} />)
    expect(await screen.findByRole('button', { name: 'Agregar nuevo cliente' })).toBeEnabled()
  })
})
