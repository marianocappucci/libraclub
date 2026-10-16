import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { elegirEnBuscable } from '@/test/select-buscable'
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

const REINCIDENTES = '/api/clientes/ausentismo/reincidentes'

/** Los reincidentes que contesta el doble. Vacío salvo en los tests del aviso. */
let reincidentes: { cliente_id: number; ausentes: number; ultimo_ausente_at: string }[]

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
  if (url === REINCIDENTES) return { status: 200, body: { umbral: 3, dias: 90, reincidentes } }
  if (url === '/api/clientes') return { status: 201, body: { id: 99, nombre: 'Ana Gómez', telefono: null } }
  return { status: 201, body: { id: 55 } }
}

let siguienteRespuesta:
  | ((url: string, metodo: string) => { status: number; body: unknown })
  | null = null

beforeEach(() => {
  llamadas = []
  reincidentes = []
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

  it('da de alta el cliente en el panel (ADR-071), queda elegido y la reserva sale con su id', async () => {
    const user = userEvent.setup()
    const onCreada = abrir()
    await screen.findByRole('combobox', { name: /cliente/i })
    // Mientras no se crea, la reserva sale con el cliente de la lista (Juan, id 7).
    await user.click(screen.getByRole('button', { name: 'Agregar nuevo cliente' }))
    const panel = screen.getByRole('group', { name: 'Nuevo cliente' })
    await user.type(within(panel).getByLabelText(/nombre/i), 'Ana Gómez')
    await user.type(within(panel).getByLabelText('Teléfono'), '3515550000')
    await user.type(within(panel).getByLabelText('Email'), 'ana@example.com')
    await user.click(within(panel).getByRole('button', { name: 'Crear cliente' }))

    // El POST sale al crear en el panel, antes de reservar, con teléfono y email.
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Nuevo cliente' })).toBeNull())
    const altaCliente = llamadas.find((l) => l.url === '/api/clientes' && l.metodo === 'POST')!
    expect(altaCliente.cuerpo).toEqual({ nombre: 'Ana Gómez', telefono: '3515550000', email: 'ana@example.com' })
    expect(llamadas.some((l) => l.url === '/api/reservas')).toBe(false)
    // Quedó elegido: el campo muestra su nombre.
    expect(screen.getByRole('combobox', { name: /cliente/i })).toHaveValue('Ana Gómez')

    await user.click(screen.getByRole('button', { name: 'Reservar' }))
    await waitFor(() => expect(onCreada).toHaveBeenCalled())
    // El id del cliente recién creado, no el del primero de la lista; y no se creó dos veces.
    expect(llamadas.find((l) => l.url === '/api/reservas')!.cuerpo).toMatchObject({ cliente_id: 99 })
    expect(llamadas.filter((l) => l.url === '/api/clientes' && l.metodo === 'POST')).toHaveLength(1)
  })

  it('el cliente se crea en el panel, no al reservar: si la reserva falla, no se vuelve a crear', async () => {
    // Antes el POST de cliente salía junto con el de la reserva; un 409 dejaba un cliente huérfano y el reintento creaba otro.
    siguienteRespuesta = (url, metodo) =>
      url === '/api/reservas' ? { status: 409, body: { detail: 'Ocupada.' } } : responder(url, metodo)
    const user = userEvent.setup()
    abrir()
    await screen.findByRole('combobox', { name: /cliente/i })
    await user.click(screen.getByRole('button', { name: 'Agregar nuevo cliente' }))
    await user.type(screen.getByLabelText(/nombre/i), 'Ana Gómez')
    await user.click(screen.getByRole('button', { name: 'Crear cliente' }))
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Nuevo cliente' })).toBeNull())

    await user.click(screen.getByRole('button', { name: 'Reservar' }))
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: 'Reservar' }))
    await waitFor(() => expect(llamadas.filter((l) => l.url === '/api/reservas')).toHaveLength(2))

    expect(llamadas.filter((l) => l.url === '/api/clientes' && l.metodo === 'POST')).toHaveLength(1)
  })

  it('si el alta falla, el panel muestra el motivo y no se pierde lo cargado', async () => {
    siguienteRespuesta = (url, metodo) =>
      url === '/api/clientes' && metodo === 'POST'
        ? { status: 422, body: { detail: 'El nombre es demasiado largo.' } }
        : responder(url, metodo)
    const user = userEvent.setup()
    abrir()
    await screen.findByRole('combobox', { name: /cliente/i })
    await user.click(screen.getByRole('button', { name: 'Agregar nuevo cliente' }))
    await user.type(screen.getByLabelText(/nombre/i), 'Ana Gómez')
    await user.click(screen.getByRole('button', { name: 'Crear cliente' }))

    // El texto del backend, no el «Error de conexión.» genérico del componente.
    expect(await screen.findByText('El nombre es demasiado largo.')).toBeInTheDocument()
    expect(screen.getByLabelText(/nombre/i)).toHaveValue('Ana Gómez')
    expect(llamadas.some((l) => l.url === '/api/reservas')).toBe(false)
  })

  it('sin clientes cargados el campo está vacío y el alta sigue a un click', async () => {
    siguienteRespuesta = (url, metodo) =>
      url === '/api/clientes' && metodo === 'GET' ? { status: 200, body: [] } : responder(url, metodo)
    const user = userEvent.setup()
    const onCreada = abrir()
    await screen.findByRole('combobox', { name: /cliente/i })
    await user.click(screen.getByRole('button', { name: 'Reservar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/elegí un cliente/i)
    expect(onCreada).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Agregar nuevo cliente' }))
    await user.type(screen.getByLabelText(/nombre/i), 'Ana Gómez')
    await user.click(screen.getByRole('button', { name: 'Crear cliente' }))
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Nuevo cliente' })).toBeNull())
    await user.click(screen.getByRole('button', { name: 'Reservar' }))

    await waitFor(() => expect(onCreada).toHaveBeenCalled())
    expect(llamadas.find((l) => l.url === '/api/reservas')!.cuerpo).toMatchObject({ cliente_id: 99 })
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

describe('ausentismo: avisa y NO bloquea', () => {
  const DOS_CLIENTES = [
    { id: 7, nombre: 'Juan Pérez', telefono: null },
    { id: 8, nombre: 'Ana Gómez', telefono: null },
  ]

  beforeEach(() => {
    reincidentes = [
      { cliente_id: 7, ausentes: 3, ultimo_ausente_at: '2026-09-05T20:00:00-03:00' },
    ]
  })

  it('muestra cuántas veces faltó el elegido y la fecha de la última', async () => {
    abrir()
    const aviso = await screen.findByRole('status')
    expect(aviso).toHaveTextContent(
      'Juan Pérez faltó sin avisar 3 veces en los últimos 90 días (la última, el 05-09-2026).',
    )
  })

  it('🔴 con el aviso a la vista, se reserva igual', async () => {
    // Decisión del humano: contar y avisar, sin bloquear. Si alguien atara el
    // botón al aviso, este test se pone rojo.
    const onCreada = abrir()
    await screen.findByRole('status')
    await userEvent.click(screen.getByRole('button', { name: 'Reservar' }))

    await waitFor(() => expect(onCreada).toHaveBeenCalled())
    expect(llamadas.find((l) => l.url === '/api/reservas')!.cuerpo).toMatchObject({
      cliente_id: 7,
    })
  })

  it('el aviso sigue al cliente elegido: el que no faltó no lo lleva', async () => {
    // 🔑 El control. Un aviso que saliera para cualquiera pasaría el primer test
    // sin decir nada sobre quién faltó.
    siguienteRespuesta = (url, metodo) =>
      url === '/api/clientes' && metodo === 'GET'
        ? { status: 200, body: DOS_CLIENTES }
        : responder(url, metodo)
    abrir()
    await screen.findByRole('status')

    await elegirEnBuscable(userEvent.setup(), screen.getByRole('combobox', { name: /cliente/i }), 'Ana Gómez')

    expect(screen.queryByRole('status')).toBeNull()
  })

  it('si el pedido de ausencias falla, el diálogo anda igual', async () => {
    siguienteRespuesta = (url, metodo) =>
      url === REINCIDENTES ? { status: 500, body: { detail: 'se cayó' } } : responder(url, metodo)
    const onCreada = abrir()
    await screen.findByRole('combobox', { name: /cliente/i })

    await userEvent.click(screen.getByRole('button', { name: 'Reservar' }))

    await waitFor(() => expect(onCreada).toHaveBeenCalled())
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
