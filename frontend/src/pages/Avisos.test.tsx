import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * La pantalla «Avisos» (ADR-030): los tipos son de LibraClub (`/api/avisos/tipos`, por `@/lib/api`); la
 * configuración de WhatsApp y el registro son del motor y los pinta el kit (`ConfiguracionDeAvisos` y
 * `RegistroDeAvisos`, ADR-097), que habla con `/api/avisos/{config,envios,…}` por el cliente del kit. Se dobla ese
 * cliente (no el componente): lo que se mide es que los componentes reales reciban lo que esta pantalla les pasa
 * —`demo`, `esAdmin`, el rótulo de cada tipo— y que se rendericen sólo para el administrador.
 */

const tipos = vi.fn()
const guardarTipos = vi.fn()
let rol = 'admin'

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return { ...real, avisos: { tipos, guardarTipos } }
})

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'u', name: 'U', role: rol }, loading: false }),
}))

const get = vi.fn()
const put = vi.fn()
const post = vi.fn()

vi.mock('libra-ui/api-client', async (original) => {
  const real = await original<Record<string, unknown>>()
  return { ...real, api: { get, put, post, del: vi.fn() } }
})

const { Avisos } = await import('./Avisos')

const TIPOS = {
  confirmacion: true, recordatorio: true, cancelacion: true, sena_por_vencer: true, demo: false,
}

const CONFIG_DEL_MOTOR = {
  whatsapp: {
    modo: 'registro', modos: ['apagado', 'registro', 'evolution'], url: '', instancia: '', apikey_cargada: false,
    disponible: true, motivo: '',
  },
  email: { disponible: true },
}

const envio = {
  plantilla: '', variables: {}, intentos: 1, id_externo: '', enviado_at: '', updated_at: '2026-09-01 19:00:00',
  asunto: '', cuerpo: '',
}
const ENVIOS = [
  {
    ...envio, id: 3, canal: 'whatsapp', clave: 'reserva:5:sena_por_vencer:-', tipo: 'sena_por_vencer',
    destino: '5492255123456', proveedor: 'registro', estado: 'registrado',
    detalle: 'Registrado en modo prueba: no se mandó nada.', created_at: '2026-09-01 19:00:00',
  },
  {
    ...envio, id: 2, canal: 'email', clave: 'reserva:5:confirmacion:-', tipo: 'confirmacion',
    destino: 'jugador@ejemplo.com', proveedor: 'smtp', estado: 'enviado', detalle: '',
    created_at: '2026-09-01 18:00:00',
  },
]

beforeEach(() => {
  rol = 'admin'
  for (const f of [tipos, guardarTipos, get, put, post]) f.mockReset()
  tipos.mockResolvedValue(TIPOS)
  get.mockImplementation(async (url: string) => {
    if (url.startsWith('/api/avisos/config')) return CONFIG_DEL_MOTOR
    if (url.startsWith('/api/avisos/envios')) return ENVIOS
    throw new Error(`pedido inesperado: ${url}`)
  })
})

describe('pantalla de avisos: qué tipos salen', () => {
  it('muestra los cuatro avisos prendidos', async () => {
    render(<Avisos />)

    for (const nombre of ['Confirmación', 'Recordatorio', 'Cancelación', 'Seña por vencer']) {
      expect(await screen.findByRole('switch', { name: nombre })).toBeChecked()
    }
  })

  it('🔴 ya no hay un «Modo» de WhatsApp acá: es del motor y una sola fuente de verdad', async () => {
    render(<Avisos />)
    await screen.findByRole('switch', { name: 'Confirmación' })

    expect(screen.queryByRole('combobox', { name: 'Modo' })).not.toBeInTheDocument()
  })

  it('guardar manda sólo los cuatro tipos (sin el dato de la demo) y avisa; sin cambios el botón está apagado', async () => {
    const user = userEvent.setup()
    guardarTipos.mockImplementation(async (c) => ({ ...c, demo: false }))
    render(<Avisos />)
    const guardar = await screen.findByRole('button', { name: 'Guardar' })
    expect(guardar).toBeDisabled()

    await user.click(screen.getByRole('switch', { name: 'Recordatorio' }))
    expect(guardar).toBeEnabled()
    await user.click(guardar)

    await waitFor(() => expect(guardarTipos).toHaveBeenCalledWith({
      confirmacion: true, recordatorio: false, cancelacion: true, sena_por_vencer: true,
    }))
    expect(await screen.findByRole('status')).toHaveTextContent('Configuración guardada.')
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeDisabled()
  })

  it('🔑 el mostrador ve los tipos de sólo lectura y nada más: ni WhatsApp ni el registro', async () => {
    rol = 'staff'
    render(<Avisos />)

    expect(await screen.findByRole('switch', { name: 'Confirmación' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Guardar' })).not.toBeInTheDocument()
    expect(screen.getByText(/Sólo un administrador cambia esto/)).toBeInTheDocument()
    expect(screen.queryByRole('tab')).not.toBeInTheDocument()
    // Y no pide al motor lo que el motor le negaría (403): el router es de administrador.
    expect(get).not.toHaveBeenCalled()
  })

  it('un error al guardar se muestra y no se pierde lo editado', async () => {
    const user = userEvent.setup()
    guardarTipos.mockRejectedValue(new Error('No tenés permiso.'))
    render(<Avisos />)
    await user.click(await screen.findByRole('switch', { name: 'Cancelación' }))
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('No tenés permiso.')
    expect(screen.getByRole('switch', { name: 'Cancelación' })).not.toBeChecked()
  })
})

describe('pantalla de avisos: WhatsApp y correo (el kit)', () => {
  async function abrirWhatsApp() {
    const user = userEvent.setup()
    render(<Avisos />)
    await user.click(await screen.findByRole('tab', { name: 'WhatsApp y correo' }))
    return user
  }

  it('es el componente del kit sobre el router del motor, y dice cómo está WhatsApp', async () => {
    await abrirWhatsApp()

    expect(await screen.findByText('En registro')).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/api/avisos/config')
  })

  it('en una demo lo avisa de entrada (`demo` sale de `/api/avisos/tipos`)', async () => {
    tipos.mockResolvedValue({ ...TIPOS, demo: true })
    await abrirWhatsApp()

    expect(await screen.findByText(/Esto es una demo/)).toBeInTheDocument()
  })

  it('fuera de una demo no muestra el aviso de demo', async () => {
    await abrirWhatsApp()
    await screen.findByText('En registro')

    expect(screen.queryByText(/Esto es una demo/)).not.toBeInTheDocument()
  })
})

describe('pantalla de avisos: registro (el kit)', () => {
  async function abrirElRegistro() {
    const user = userEvent.setup()
    render(<Avisos />)
    await user.click(await screen.findByRole('tab', { name: 'Registro' }))
    return user
  }

  it('🔴 un aviso registrado dice que no salió y se distingue de uno enviado', async () => {
    await abrirElRegistro()

    const registrado = (await screen.findByText('5492255123456')).closest('tr')!
    expect(within(registrado).getByText('Registrado')).toBeInTheDocument()
    expect(within(registrado).getByText('WhatsApp')).toBeInTheDocument()
    expect(within(registrado).queryByText('Enviado')).not.toBeInTheDocument()

    const enviado = screen.getByText('jugador@ejemplo.com').closest('tr')!
    expect(within(enviado).getByText('Enviado')).toBeInTheDocument()
    expect(within(enviado).getByText('Correo')).toBeInTheDocument()
  })

  it('el administrador ve el destino completo (el kit lo enmascararía sin `esAdmin`)', async () => {
    await abrirElRegistro()

    expect(await screen.findByText('5492255123456')).toBeInTheDocument()
    expect(screen.queryByText(/•••/)).not.toBeInTheDocument()
  })

  it('el tipo se rotula con el vocabulario de LibraClub y no con el del código', async () => {
    await abrirElRegistro()

    const fila = (await screen.findByText('5492255123456')).closest('tr')!
    expect(within(fila).getByText('Seña por vencer')).toBeInTheDocument()
    expect(within(fila).queryByText('Sena por vencer')).not.toBeInTheDocument()
  })

  it('pide el registro al router del motor', async () => {
    await abrirElRegistro()
    await screen.findByText('5492255123456')

    expect(get).toHaveBeenCalledWith('/api/avisos/envios?limite=200')
  })

  it('sin avisos dice que todavía no se registró ninguno', async () => {
    get.mockImplementation(async (url: string) => (url.startsWith('/api/avisos/envios') ? [] : CONFIG_DEL_MOTOR))
    await abrirElRegistro()

    expect(await screen.findByText('Todavía no se registró ningún aviso.')).toBeInTheDocument()
  })
})
