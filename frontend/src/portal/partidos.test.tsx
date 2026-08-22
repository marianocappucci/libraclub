import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * «Falta uno» del lado de la pantalla.
 *
 * 🔴 **Lo que más importa es que no dibuje contacto que el servidor no mandó.**
 * El permiso lo decide el backend —manda `null` a quien no juega ahí— y acá no
 * puede haber ninguna rama que lo complete de otro lado.
 */

const abiertos = vi.fn()
const mios = vi.fn()
const ver = vi.fn()
const sumarme = vi.fn()
const bajarme = vi.fn()
const cerrar = vi.fn()
const yo = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    portal: { ...(real.portal as object), yo, logout: vi.fn() },
    partidos: {
      ...(real.partidos as object),
      abiertos, mios, ver, sumarme, bajarme, cerrar, publicar: vi.fn(),
    },
  }
})

const { JugadorProvider } = await import('./JugadorContext')
const { Partidos } = await import('./Partidos')

function enHoras(n: number): string {
  return new Date(Date.now() + n * 3_600_000).toISOString()
}

const EN_LISTA = {
  id: 7, cancha: 'Cancha 1', deporte: 'padel',
  comienza_at: enHoras(48), termina_at: enHoras(49.5),
  organizador: 'Juan', faltan: 2, nota: 'Nivel intermedio',
}

/** Lo que el servidor le manda a quien NO juega ahí. */
const SIN_CONTACTO = {
  id: 7, cancha: 'Cancha 1', comienza_at: enHoras(48), termina_at: enHoras(49.5),
  organizador: 'Juan', organizador_telefono: null, faltan: 2,
  nota: 'Nivel intermedio', abierta: true,
  soy_organizador: false, estoy_anotado: false, anotados: [],
}

/** Lo que le manda a quien sí. */
const CON_CONTACTO = {
  ...SIN_CONTACTO, organizador_telefono: '2255-999999', faltan: 1,
  estoy_anotado: true,
  anotados: [{ nombre: 'Pedro', telefono: '2255-888888', soy_yo: true }],
}

function montar() {
  return render(
    <MemoryRouter>
      <JugadorProvider>
        <Partidos />
      </JugadorProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  yo.mockResolvedValue({ id: 1, nombre: 'Pedro', email: 'p@x.com' })
  abiertos.mockResolvedValue([EN_LISTA])
  mios.mockResolvedValue([])
  ver.mockResolvedValue(SIN_CONTACTO)
})

describe('falta uno', () => {
  it('lista los partidos con lo que hace falta para elegir', async () => {
    montar()
    expect(await screen.findByText(/Faltan 2/)).toBeInTheDocument()
    expect(screen.getByText(/organiza Juan/)).toBeInTheDocument()
    expect(screen.getByText(/Nivel intermedio/)).toBeInTheDocument()
  })

  it('el detalle NO muestra teléfono si el servidor no lo mandó', async () => {
    // 🔴 El permiso lo decide el backend. Acá no puede haber una rama que
    // complete el dato de otro lado.
    montar()
    await userEvent.click(await screen.findByText(/Faltan 2/))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).queryByText(/2255-/)).not.toBeInTheDocument()
    // Y explica por qué, para que no parezca que nadie cargó su número.
    expect(within(dialogo).getByText(/Cuando te sumes vas a ver/)).toBeInTheDocument()
  })

  it('al sumarse muestra el contacto que llega en la respuesta', async () => {
    // Control del test de arriba: si nunca dibujara teléfonos, aquél pasaría
    // igual y la pantalla sería inútil.
    sumarme.mockResolvedValue(CON_CONTACTO)
    montar()
    await userEvent.click(await screen.findByText(/Faltan 2/))
    const dialogo = await screen.findByRole('dialog')
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Sumarme' }))

    await waitFor(() => expect(sumarme).toHaveBeenCalledWith(7))
    expect(await within(dialogo).findByText('2255-999999')).toBeInTheDocument()
    expect(within(dialogo).queryByText(/Cuando te sumes vas a ver/)).not.toBeInTheDocument()
  })

  it('estando anotado ofrece bajarse y no sumarse', async () => {
    ver.mockResolvedValue(CON_CONTACTO)
    mios.mockResolvedValue([CON_CONTACTO])
    abiertos.mockResolvedValue([])
    montar()
    await userEvent.click(await screen.findByText('Anotado'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByRole('button', { name: 'Bajarme' })).toBeInTheDocument()
    expect(within(dialogo).queryByRole('button', { name: 'Sumarme' })).not.toBeInTheDocument()
  })

  it('el organizador ve «dejar de buscar», no «sumarme»', async () => {
    ver.mockResolvedValue({ ...CON_CONTACTO, soy_organizador: true, estoy_anotado: false })
    montar()
    await userEvent.click(await screen.findByText(/Faltan 2/))
    const dialogo = await screen.findByRole('dialog')
    expect(
      within(dialogo).getByRole('button', { name: 'Dejar de buscar' }),
    ).toBeInTheDocument()
    expect(within(dialogo).queryByRole('button', { name: 'Sumarme' })).not.toBeInTheDocument()
  })

  it('un partido completo no ofrece sumarse', async () => {
    ver.mockResolvedValue({ ...SIN_CONTACTO, faltan: 0 })
    montar()
    await userEvent.click(await screen.findByText(/Faltan 2/))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByText('Completo')).toBeInTheDocument()
    expect(within(dialogo).queryByRole('button', { name: 'Sumarme' })).not.toBeInTheDocument()
  })

  it('sin partidos explica dónde se publica', async () => {
    abiertos.mockResolvedValue([])
    montar()
    expect(await screen.findByText(/publicalo desde «Mis reservas»/)).toBeInTheDocument()
  })

  it('sin sesión pide entrar y no llama a la API', async () => {
    yo.mockResolvedValue(null)
    montar()
    expect(await screen.findByText(/Entrá a tu cuenta/)).toBeInTheDocument()
    expect(abiertos).not.toHaveBeenCalled()
  })

  it('los partidos donde ya estoy anotado no se repiten abajo', async () => {
    // Si apareciera en las dos listas, el mismo partido se vería dos veces y
    // uno de los dos diría "faltan 2" cuando ya estoy adentro.
    mios.mockResolvedValue([CON_CONTACTO])
    abiertos.mockResolvedValue([EN_LISTA])
    montar()
    await screen.findByText('Anotado')
    expect(screen.queryByText(/Faltan 2/)).not.toBeInTheDocument()
  })
})
