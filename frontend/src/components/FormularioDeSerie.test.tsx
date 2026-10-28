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

describe('cancha fija: la pantalla de resultado no se borra si el padre recarga', () => {
  const LUCIA = { id: 8, nombre: 'Lucía Gómez', telefono: null } as Cliente

  async function crearSerie() {
    const user = userEvent.setup()
    const props = { canchas: [CANCHA], onCerrar: vi.fn(), onCreada: vi.fn() }
    const vista = render(<FormularioDeSerie abierto clientes={[JUAN]} {...props} />)
    await user.click(await screen.findByRole('button', { name: 'Crear y generar turnos' }))
    expect(await screen.findByText('Cancha fija creada')).toBeInTheDocument()
    return { ...vista, props }
  }

  it('otra lista de clientes (y canchas) tras crear no resetea el formulario', async () => {
    const { rerender, props } = await crearSerie()
    // Lo que hace TurnosFijos en onCreada: recarga y llegan arrays nuevos.
    rerender(<FormularioDeSerie abierto {...props} canchas={[{ ...CANCHA }]} clientes={[{ ...JUAN }, LUCIA]} />)
    expect(screen.getByText('Cancha fija creada')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Listo' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Crear y generar turnos' })).toBeNull()
  })

  it('al volver a abrir sí arranca de cero', async () => {
    const { rerender, props } = await crearSerie()
    rerender(<FormularioDeSerie abierto={false} {...props} clientes={[JUAN]} />)
    rerender(<FormularioDeSerie abierto {...props} clientes={[JUAN]} />)
    expect(await screen.findByText('Nueva cancha fija')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Crear y generar turnos' })).toBeInTheDocument()
    expect(screen.queryByText('Cancha fija creada')).toBeNull()
  })
})

describe('los turnos fijos no llevan promoción (libraclub ADR-029, 2026-10-28)', () => {
  it('el formulario lo dice antes de cargar la serie', async () => {
    render(<FormularioDeSerie abierto canchas={[CANCHA]} clientes={[JUAN]} onCerrar={vi.fn()} onCreada={vi.fn()} />)

    expect(await screen.findByTestId('aviso-sin-promocion')).toHaveTextContent(
      'Los turnos fijos pagan la tarifa de lista: no llevan promoción ni hora valle.',
    )
  })
})
