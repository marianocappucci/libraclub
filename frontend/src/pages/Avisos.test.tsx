import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const config = vi.fn()
const guardarConfig = vi.fn()
const registro = vi.fn()
let rol = 'admin'

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return { ...real, avisos: { config, guardarConfig, registro } }
})

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'u', name: 'U', role: rol }, loading: false }),
}))

const { Avisos } = await import('./Avisos')

const CONFIG = {
  whatsapp: 'apagado', confirmacion: true, recordatorio: true, cancelacion: true, sena_por_vencer: true,
}

const base = {
  creado_at: '2026-09-01T22:00:00Z', cancha: 'Cancha 1', comienza_at: '2026-09-02T23:00:00Z',
  intentos: 1, reserva_id: 5, asunto: null,
}
const REGISTRO = [
  {
    ...base, id: 3, tipo: 'sena_por_vencer', canal: 'whatsapp', estado: 'registrado',
    destino: '5492255123456', detalle: 'Registrado en modo prueba: no se mandó nada.',
    cuerpo: '*Tu turno se libera a las 19:06*\n\nHola Juan,',
  },
  {
    ...base, id: 2, tipo: 'confirmacion', canal: 'email', estado: 'enviado',
    destino: 'jugador@ejemplo.com', detalle: null, asunto: 'Turno confirmado', cuerpo: 'Hola Juan,',
  },
  {
    ...base, id: 1, tipo: 'recordatorio', canal: 'whatsapp', estado: 'omitido',
    destino: '', detalle: 'El cliente no tiene un teléfono que WhatsApp reconozca.', cuerpo: null,
  },
]

beforeEach(() => {
  rol = 'admin'
  config.mockReset()
  guardarConfig.mockReset()
  registro.mockReset()
  config.mockResolvedValue(CONFIG)
  registro.mockResolvedValue(REGISTRO)
})

describe('pantalla de avisos: configuración', () => {
  it('muestra los cuatro avisos prendidos y WhatsApp apagado', async () => {
    render(<Avisos />)

    for (const nombre of ['Confirmación', 'Recordatorio', 'Cancelación', 'Seña por vencer']) {
      expect(await screen.findByRole('switch', { name: nombre })).toBeChecked()
    }
    expect(screen.getByRole('combobox', { name: 'Modo' })).toHaveValue('apagado')
  })

  it('🔑 el texto de WhatsApp dice que en modo de prueba no se manda a nadie', async () => {
    render(<Avisos />)
    expect(await screen.findByText(/no se mandan a nadie/)).toBeInTheDocument()
  })

  it('guardar manda la configuración entera y avisa; sin cambios el botón está apagado', async () => {
    const user = userEvent.setup()
    guardarConfig.mockImplementation(async (c) => c)
    render(<Avisos />)
    const guardar = await screen.findByRole('button', { name: 'Guardar' })
    expect(guardar).toBeDisabled()

    await user.click(screen.getByRole('switch', { name: 'Recordatorio' }))
    await user.selectOptions(screen.getByRole('combobox', { name: 'Modo' }), 'registro')
    expect(guardar).toBeEnabled()
    await user.click(guardar)

    await waitFor(() => expect(guardarConfig).toHaveBeenCalledWith({
      whatsapp: 'registro', confirmacion: true, recordatorio: false, cancelacion: true,
      sena_por_vencer: true,
    }))
    expect(await screen.findByRole('status')).toHaveTextContent('Configuración guardada.')
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeDisabled()
  })

  it('🔑 el mostrador ve la configuración pero no puede cambiarla', async () => {
    rol = 'staff'
    render(<Avisos />)

    expect(await screen.findByRole('switch', { name: 'Confirmación' })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: 'Modo' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Guardar' })).not.toBeInTheDocument()
  })

  it('un error al guardar se muestra y no se pierde lo editado', async () => {
    const user = userEvent.setup()
    guardarConfig.mockRejectedValue(new Error('No tenés permiso.'))
    render(<Avisos />)
    await user.click(await screen.findByRole('switch', { name: 'Cancelación' }))
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('No tenés permiso.')
    expect(screen.getByRole('switch', { name: 'Cancelación' })).not.toBeChecked()
  })
})

describe('pantalla de avisos: registro', () => {
  async function abrirElRegistro() {
    const user = userEvent.setup()
    render(<Avisos />)
    await user.click(await screen.findByRole('tab', { name: 'Registro' }))
    return user
  }

  it('🔴 un aviso registrado dice que no salió; no se confunde con uno enviado', async () => {
    await abrirElRegistro()

    const registrado = (await screen.findByText('5492255123456')).closest('tr')!
    expect(within(registrado).getByText('Registrado (no salió)')).toBeInTheDocument()
    expect(within(registrado).getByText('WhatsApp')).toBeInTheDocument()
    expect(within(registrado).getByText('Seña por vencer')).toBeInTheDocument()
    expect(within(registrado).queryByText('Enviado')).not.toBeInTheDocument()

    const enviado = screen.getByText('jugador@ejemplo.com').closest('tr')!
    expect(within(enviado).getByText('Enviado')).toBeInTheDocument()
    expect(within(enviado).getByText('Correo')).toBeInTheDocument()
  })

  it('un aviso omitido muestra el motivo y no tiene mensaje para ver', async () => {
    await abrirElRegistro()

    const omitido = (await screen.findByText(/teléfono que WhatsApp reconozca/)).closest('tr')!
    expect(within(omitido).getByText('Omitido')).toBeInTheDocument()
    expect(within(omitido).queryByRole('button')).not.toBeInTheDocument()
  })

  it('el mensaje se abre en un diálogo, tal como se armó', async () => {
    const user = await abrirElRegistro()

    await user.click(await screen.findByRole('button', { name: 'Ver el mensaje a 5492255123456' }))

    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByText(/Tu turno se libera a las 19:06/)).toBeInTheDocument()
    expect(within(dialogo).getByText(/Seña por vencer · 5492255123456/)).toBeInTheDocument()
  })

  it('sin avisos dice que todavía no se mandó ninguno', async () => {
    registro.mockResolvedValue([])
    await abrirElRegistro()
    expect(await screen.findByText('Todavía no se mandó ningún aviso.')).toBeInTheDocument()
  })
})
