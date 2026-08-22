import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El portal público, que es lo que ve alguien de internet.
 *
 * Lo que se fija acá:
 *
 * 1. que se pueda **mirar sin cuenta**, y que la cuenta se pida al elegir turno;
 * 2. que el diálogo de pago muestre **el reloj** y deje de ofrecer pagar cuando
 *    se venció;
 * 3. que el portal **no dibuje el menú del backoffice**;
 * 4. que «Mis reservas» traduzca el par (estado, pago) y no el estado crudo.
 */

const canchas = vi.fn()
const disponibilidad = vi.fn()
const reservar = vi.fn()
const misReservas = vi.fn()
const cancelar = vi.fn()
const yo = vi.fn()
const login = vi.fn()
const registro = vi.fn()
const simularPago = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    portal: {
      ...(real.portal as object),
      canchas, disponibilidad, reservar, misReservas, cancelar,
      yo, login, registro, logout: vi.fn(), simularPago,
    },
  }
})

const { JugadorProvider } = await import('./JugadorContext')
const { PortalReservar } = await import('./PortalReservar')
const { PortalLayout } = await import('./PortalLayout')
const { MisReservas } = await import('./MisReservas')

const CANCHA = {
  id: 1, nombre: 'Cancha 1', deporte: 'padel', techada: true,
  iluminacion: true, duracion_turno_min: 90,
}

function enHoras(n: number): string {
  return new Date(Date.now() + n * 3_600_000).toISOString()
}

const TURNO = {
  comienza_at: enHoras(30),
  termina_at: enHoras(31.5),
  precio: 8000,
}

function montar(componente: React.ReactNode) {
  return render(
    <MemoryRouter>
      <JugadorProvider>{componente}</JugadorProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  canchas.mockResolvedValue([CANCHA])
  disponibilidad.mockResolvedValue([TURNO])
  misReservas.mockResolvedValue([])
  yo.mockResolvedValue(null)
  vi.stubGlobal('confirm', vi.fn(() => true))
})

describe('portal: elegir turno', () => {
  it('se ven los turnos SIN estar registrado', async () => {
    // 🔑 Pedir la cuenta antes de que el jugador vea si hay lugar el viernes es
    // la forma más rápida de que se vaya.
    montar(<PortalReservar />)
    expect(await screen.findByText('Cancha 1')).toBeInTheDocument()
    expect(await screen.findByText('$ 8.000,00')).toBeInTheDocument()
  })

  it('al elegir un turno sin cuenta se pide la cuenta, no se reserva', async () => {
    montar(<PortalReservar />)
    await userEvent.click(await screen.findByText('$ 8.000,00'))
    expect(await screen.findByText(/Creá tu cuenta/)).toBeInTheDocument()
    expect(reservar).not.toHaveBeenCalled()
  })

  it('con cuenta, elegir un turno lo reserva', async () => {
    yo.mockResolvedValue({ id: 1, nombre: 'Juan', email: 'j@x.com' })
    reservar.mockResolvedValue({
      reserva_id: 5, pago_id: 9, referencia: 'lc-5-abc', monto: 8000,
      vence_at: enHoras(0.25), url_de_pago: null,
    })
    simularPago.mockRejectedValue(new Error('Not Found'))
    montar(<PortalReservar />)
    await userEvent.click(await screen.findByText('$ 8.000,00'))
    await waitFor(() =>
      expect(reservar).toHaveBeenCalledWith({
        cancha_id: 1, comienza_at: TURNO.comienza_at,
      }),
    )
  })

  it('sin turnos libres explica por qué, no muestra una lista vacía', async () => {
    disponibilidad.mockResolvedValue([])
    montar(<PortalReservar />)
    expect(await screen.findByText(/No quedan turnos libres/)).toBeInTheDocument()
  })
})

describe('portal: el paso del pago', () => {
  async function llegarAlPago(venceEnHoras = 0.25) {
    yo.mockResolvedValue({ id: 1, nombre: 'Juan', email: 'j@x.com' })
    reservar.mockResolvedValue({
      reserva_id: 5, pago_id: 9, referencia: 'lc-5-abc', monto: 8000,
      vence_at: enHoras(venceEnHoras), url_de_pago: null,
    })
    simularPago.mockRejectedValue(new Error('no existe ese pago'))
    montar(<PortalReservar />)
    await userEvent.click(await screen.findByText('$ 8.000,00'))
    return screen.findByRole('dialog')
  }

  it('muestra cuánto tiempo queda para pagar', async () => {
    // 🔴 Sin el reloj, el jugador completa la tarjeta sin saber que el turno se
    // le está por caer.
    const dialogo = await llegarAlPago()
    expect(within(dialogo).getByText(/Te guardamos el turno/)).toBeInTheDocument()
    expect(within(dialogo).getByText('$ 8.000,00')).toBeInTheDocument()
  })

  it('vencido, deja de ofrecer pagar y lo dice', async () => {
    // Apretar un botón que ya no funciona daría un error del servidor que el
    // jugador no puede interpretar.
    const dialogo = await llegarAlPago(-1)
    expect(within(dialogo).getByText(/Se venció el tiempo para pagar/)).toBeInTheDocument()
    expect(
      within(dialogo).queryByRole('button', { name: /Simular pago aprobado/ }),
    ).not.toBeInTheDocument()
  })

  it('sin credenciales de MercadoPago lo dice, en vez de un botón muerto', async () => {
    const dialogo = await llegarAlPago()
    expect(
      within(dialogo).getByText(/todavía no tiene los pagos online configurados/),
    ).toBeInTheDocument()
  })

  it('el simulador aparece sólo si el servidor lo tiene', async () => {
    // 🔑 Se pregunta al servidor y no a una variable de build: el bundle es el
    // mismo en dev y en producción, así que una bandera del frontend mostraría
    // el botón donde no tiene que estar.
    const dialogo = await llegarAlPago()
    expect(
      await within(dialogo).findByRole('button', { name: /Simular pago aprobado/ }),
    ).toBeInTheDocument()
  })

  it('en producción el simulador NO aparece', async () => {
    yo.mockResolvedValue({ id: 1, nombre: 'Juan', email: 'j@x.com' })
    reservar.mockResolvedValue({
      reserva_id: 5, pago_id: 9, referencia: 'lc-5-abc', monto: 8000,
      vence_at: enHoras(0.25), url_de_pago: null,
    })
    // Lo que contesta una instancia de producción: la RUTA no existe.
    simularPago.mockRejectedValue(new Error('Not Found'))
    montar(<PortalReservar />)
    await userEvent.click(await screen.findByText('$ 8.000,00'))
    const dialogo = await screen.findByRole('dialog')
    await waitFor(() => expect(simularPago).toHaveBeenCalled())
    expect(
      within(dialogo).queryByRole('button', { name: /Simular pago aprobado/ }),
    ).not.toBeInTheDocument()
  })
})

describe('portal: el marco', () => {
  it('NO dibuja el menú del backoffice', async () => {
    // 🔴 Ese menú lleva a Caja, Usuarios y Logs. Mostrárselo a un visitante le
    // diría qué existe del otro lado y le daría links para probar.
    yo.mockResolvedValue({ id: 1, nombre: 'Juan', email: 'j@x.com' })
    montar(<PortalLayout />)
    await screen.findByText('Reservar cancha')
    for (const prohibido of ['Caja', 'Usuarios', 'Logs', 'Configuración', 'Tarifas']) {
      expect(screen.queryByText(prohibido)).not.toBeInTheDocument()
    }
  })

  it('sin sesión no ofrece "Mis reservas"', async () => {
    montar(<PortalLayout />)
    await screen.findByText('Reservar cancha')
    expect(screen.queryByText('Mis reservas')).not.toBeInTheDocument()
  })
})

describe('portal: mis reservas', () => {
  const BASE = {
    id: 1, cancha: 'Cancha 1', comienza_at: enHoras(48), termina_at: enHoras(49.5),
    precio: 8000, vence_at: null,
  }

  it('traduce el par (estado, pago) y no el estado crudo', async () => {
    // 🔑 Una provisoria con pago pendiente es «falta pagar»; la misma con el
    // pago vencido es «se venció». El estado crudo obliga a deducir cuál es.
    yo.mockResolvedValue({ id: 1, nombre: 'Juan', email: 'j@x.com' })
    misReservas.mockResolvedValue([
      { ...BASE, id: 1, estado: 'provisoria', pago: 'pendiente' },
      { ...BASE, id: 2, estado: 'provisoria', pago: 'vencido' },
      { ...BASE, id: 3, estado: 'confirmada', pago: 'aprobado' },
    ])
    montar(<MisReservas />)
    expect(await screen.findByText('Falta pagar')).toBeInTheDocument()
    expect(screen.getByText('Se venció sin pagar')).toBeInTheDocument()
    expect(screen.getByText('Confirmada')).toBeInTheDocument()
    // Y no aparece ninguno de los estados internos.
    expect(screen.queryByText('provisoria')).not.toBeInTheDocument()
  })

  it('no ofrece cancelar una reserva que ya pasó', async () => {
    yo.mockResolvedValue({ id: 1, nombre: 'Juan', email: 'j@x.com' })
    misReservas.mockResolvedValue([
      { ...BASE, id: 1, comienza_at: enHoras(-48), termina_at: enHoras(-46.5),
        estado: 'jugada', pago: 'aprobado' },
    ])
    montar(<MisReservas />)
    await screen.findByText('Confirmada')
    expect(screen.queryByRole('button', { name: /Cancelar/ })).not.toBeInTheDocument()
  })

  it('sí ofrece cancelar una futura, y la cancela', async () => {
    // Control del test de arriba: si nunca ofreciera cancelar, aquél pasaría
    // igual con el filtro roto.
    yo.mockResolvedValue({ id: 1, nombre: 'Juan', email: 'j@x.com' })
    misReservas.mockResolvedValue([{ ...BASE, estado: 'confirmada', pago: 'aprobado' }])
    cancelar.mockResolvedValue({ id: 1, estado: 'cancelada' })
    montar(<MisReservas />)
    await userEvent.click(await screen.findByRole('button', { name: /Cancelar el turno/ }))
    await waitFor(() => expect(cancelar).toHaveBeenCalledWith(1))
  })

  it('sin sesión pide entrar, no revienta', async () => {
    montar(<MisReservas />)
    expect(await screen.findByText(/Entrá a tu cuenta/)).toBeInTheDocument()
    expect(misReservas).not.toHaveBeenCalled()
  })
})
