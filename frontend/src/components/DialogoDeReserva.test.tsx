import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DialogoDeReserva } from './DialogoDeReserva'
import type { Cancha, Turno } from '@/lib/api'

const CANCHA: Cancha = {
  id: 3,
  sucursal_id: 1,
  nombre: 'Cancha 3',
  deporte: 'padel',
  duracion_turno_min: 90,
  techada: true,
  iluminacion: true,
  superficie: null,
  orden: 0,
  activa: true,
  observaciones: null,
}

const TURNO: Turno = {
  // Con offset, tal cual lo manda el backend.
  comienza_at: '2026-09-01T20:00:00-03:00',
  termina_at: '2026-09-01T21:30:00-03:00',
  libre: true,
  precio: '12000.00',
  reserva_id: null,
  estado: null,
  cliente: null,
  motivo: null, cobrado: false,
}

/** Las llamadas que el diálogo hizo, para poder asertar sobre el cuerpo. */
let llamadas: { url: string; metodo: string; cuerpo: Record<string, unknown> | null }[]

/**
 * El doble de la API.
 *
 * 🔴 Distingue por **método** y no sólo por URL. La primera versión devolvía la
 * lista de clientes para cualquier llamada a `/api/clientes`, incluido el POST
 * del alta: el componente leía `.id` de un array, quedaba `undefined`, y el test
 * fallaba con "Elegí un cliente" — un rojo que hablaba del arnés y no del
 * código.
 */
function responder(url: string, metodo: string): { status: number; body: unknown } {
  if (url === '/api/clientes' && metodo === 'GET') {
    return { status: 200, body: [{ id: 7, nombre: 'Juan Pérez', telefono: null }] }
  }
  if (url === '/api/clientes') return { status: 201, body: { id: 99, nombre: 'Nuevo' } }
  return { status: 201, body: { id: 55 } }
}

let siguienteRespuesta:
  | ((url: string, metodo: string) => { status: number; body: unknown })
  | null = null

beforeEach(() => {
  llamadas = []
  siguienteRespuesta = null
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    llamadas.push({
      url,
      metodo: init?.method ?? 'GET',
      cuerpo: init?.body ? JSON.parse(String(init.body)) : null,
    })
    const metodo = init?.method ?? 'GET'
    const r = (siguienteRespuesta ?? responder)(url, metodo)
    return {
      ok: r.status < 400,
      status: r.status,
      json: async () => r.body,
    } as Response
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function abrir(onCreada = vi.fn()) {
  render(
    <DialogoDeReserva
      abierto
      cancha={CANCHA}
      turno={TURNO}
      onCerrar={vi.fn()}
      onCreada={onCreada}
    />,
  )
  return onCreada
}

describe('alta de reserva desde la grilla', () => {
  it('muestra la cancha, la hora local y el precio del turno', async () => {
    abrir()
    expect(await screen.findByText('Cancha 3')).toBeInTheDocument()
    // 20:00 y no 23:00: el offset del ISO se respeta.
    expect(screen.getByText(/desde las 20:00/)).toBeInTheDocument()
    expect(screen.getByText(/12\.000/)).toBeInTheDocument()
  })

  it('con un solo turno NO manda precio: decide el tarifario', async () => {
    const onCreada = abrir()
    await screen.findByRole('combobox', { name: /cliente/i })
    await userEvent.click(screen.getByRole('button', { name: 'Reservar' }))

    await waitFor(() => expect(onCreada).toHaveBeenCalled())
    const alta = llamadas.find((l) => l.url === '/api/reservas')
    expect(alta).toBeTruthy()
    expect(alta!.cuerpo).toMatchObject({
      cancha_id: 3,
      cliente_id: 7,
      // 🔴 El instante viaja **tal cual vino**. Si el diálogo lo reconstruyera a
      // partir del día y la hora, acá aparecería sin offset o en UTC, y la
      // reserva quedaría corrida tres horas.
      comienza_at: '2026-09-01T20:00:00-03:00',
      duracion_min: 90,
    })
    expect(alta!.cuerpo).not.toHaveProperty('precio')
  })

  it('con varios turnos manda el precio explícito, y lo muestra antes', async () => {
    const onCreada = abrir()
    await screen.findByRole('combobox', { name: /cliente/i })
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /turnos/i }), '3')

    // La cuenta está a la vista antes de confirmar: el backend no prorratea ni
    // multiplica, así que el número lo decide —y lo ve— el operador.
    expect(screen.getByText(/36\.000/)).toBeInTheDocument()
    expect(screen.getByText(/3 ×/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Reservar' }))
    await waitFor(() => expect(onCreada).toHaveBeenCalled())

    const alta = llamadas.find((l) => l.url === '/api/reservas')!
    expect(alta.cuerpo).toMatchObject({ duracion_min: 270, precio: '36000.00' })
  })

  it('da de alta el cliente nuevo y reserva con su id', async () => {
    const onCreada = abrir()
    await screen.findByRole('combobox', { name: /cliente/i })
    await userEvent.click(screen.getByRole('button', { name: 'Cliente nuevo' }))
    await userEvent.type(
      screen.getByRole('textbox', { name: /nombre del cliente/i }),
      'Ana Gómez',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Reservar' }))

    await waitFor(() => expect(onCreada).toHaveBeenCalled())
    const altaCliente = llamadas.find(
      (l) => l.url === '/api/clientes' && l.metodo === 'POST',
    )!
    expect(altaCliente.cuerpo).toMatchObject({ nombre: 'Ana Gómez' })
    const alta = llamadas.find((l) => l.url === '/api/reservas')!
    // El id del cliente recién creado, no el del select.
    expect(alta.cuerpo).toMatchObject({ cliente_id: 99 })
  })

  it('un 409 se muestra con qué hacer, y NO cierra el diálogo', async () => {
    siguienteRespuesta = (url, metodo) =>
      url === '/api/clientes' && metodo === 'GET'
        ? { status: 200, body: [{ id: 7, nombre: 'Juan Pérez', telefono: null }] }
        : {
            status: 409,
            body: { detail: 'La cancha ya tiene una reserva de 20:00 a 21:30 ese día.' },
          }
    const onCreada = abrir()
    await screen.findByRole('combobox', { name: /cliente/i })
    await userEvent.click(screen.getByRole('button', { name: 'Reservar' }))

    const aviso = await screen.findByRole('alert')
    expect(aviso).toHaveTextContent('ya tiene una reserva de 20:00 a 21:30')
    expect(aviso).toHaveTextContent(/recargá la grilla/i)
    // 🔑 El control: si cerrara igual, el operador creería que reservó.
    expect(onCreada).not.toHaveBeenCalled()
  })

  it('un 422 dice que falta cargar la tarifa', async () => {
    siguienteRespuesta = (url, metodo) =>
      url === '/api/clientes' && metodo === 'GET'
        ? { status: 200, body: [{ id: 7, nombre: 'Juan Pérez', telefono: null }] }
        : {
            status: 422,
            body: { detail: 'No hay tarifa cargada para Cancha 3 el 01-09-2026 a las 20:00.' },
          }
    const onCreada = abrir()
    await screen.findByRole('combobox', { name: /cliente/i })
    await userEvent.click(screen.getByRole('button', { name: 'Reservar' }))

    const aviso = await screen.findByRole('alert')
    expect(aviso).toHaveTextContent('No hay tarifa cargada')
    expect(aviso).toHaveTextContent(/Cargala en Tarifas/i)
    expect(onCreada).not.toHaveBeenCalled()
  })
})
