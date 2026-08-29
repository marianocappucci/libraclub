import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FormularioDeCliente } from './FormularioDeCliente'
import type { Cliente } from '@/lib/api'

const EXISTENTE: Cliente = {
  id: 9,
  nombre: 'Juan Pérez',
  telefono: '2324-401122',
  email: null,
  // Con cero adelante: es el caso que se rompe si alguien lo guarda como entero.
  documento: '04123456',
  cuit: '20-04123456-3',
  activo: true,
  acepta_avisos: true,
  observaciones: 'Juega los martes',
}

let llamadas: { url: string; metodo: string; cuerpo: Record<string, unknown> }[]

beforeEach(() => {
  llamadas = []
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    llamadas.push({
      url,
      metodo: init?.method ?? 'GET',
      cuerpo: init?.body ? JSON.parse(String(init.body)) : {},
    })
    return { ok: true, status: 201, json: async () => ({ id: 1 }) } as Response
  })
})

afterEach(() => vi.unstubAllGlobals())

function abrir(cliente: Cliente | null) {
  const onGuardado = vi.fn()
  render(
    <FormularioDeCliente
      abierto
      cliente={cliente}
      onCerrar={vi.fn()}
      onGuardado={onGuardado}
    />,
  )
  return onGuardado
}

describe('formulario de cliente', () => {
  it('los campos vacíos viajan como null, no como cadena vacía', async () => {
    const onGuardado = abrir(null)
    await userEvent.type(screen.getByRole('textbox', { name: /nombre/i }), 'Ana Gómez')
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardado).toHaveBeenCalled())

    const cuerpo = llamadas.find((l) => l.metodo === 'POST')!.cuerpo
    for (const campo of ['telefono', 'email', 'documento', 'cuit', 'observaciones']) {
      expect(cuerpo[campo], campo).toBeNull()
    }
    expect(cuerpo).toMatchObject({ nombre: 'Ana Gómez', activo: true })
  })

  it('🔑 conserva el cero adelante del documento', async () => {
    const onGuardado = abrir(EXISTENTE)
    // Se precarga como texto, no como número: `04123456` como entero sería
    // 4123456, y ese DNI deja de coincidir con el del cliente.
    expect(screen.getByRole('textbox', { name: /documento/i })).toHaveValue('04123456')

    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardado).toHaveBeenCalled())
    expect(llamadas.find((l) => l.metodo === 'PUT')!.cuerpo).toMatchObject({
      documento: '04123456',
      cuit: '20-04123456-3',
    })
  })

  it('🔑 al editar manda TODOS los campos, no sólo el tocado', async () => {
    const onGuardado = abrir(EXISTENTE)
    await userEvent.clear(screen.getByRole('textbox', { name: /^teléfono$/i }))
    await userEvent.type(screen.getByRole('textbox', { name: /^teléfono$/i }), '11-2222-3333')
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardado).toHaveBeenCalled())

    const envio = llamadas.find((l) => l.metodo === 'PUT')!
    expect(envio.url).toBe('/api/clientes/9')
    expect(envio.cuerpo).toMatchObject({
      nombre: 'Juan Pérez',
      telefono: '11-2222-3333',
      documento: '04123456',
      observaciones: 'Juega los martes',
      activo: true,
    })
  })

  it('dar de baja es un campo del formulario, no el botón de borrar', async () => {
    // Borrar a un cliente con reservas devuelve 409: lo que el operador quiere
    // casi siempre es sacarlo de las listas, y eso es `activo = false`.
    const onGuardado = abrir(EXISTENTE)
    await userEvent.click(screen.getByRole('checkbox', { name: /activo/i }))
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardado).toHaveBeenCalled())
    expect(llamadas.find((l) => l.metodo === 'PUT')!.cuerpo).toMatchObject({
      activo: false,
    })
  })

  it('🔑 el que pide no recibir avisos se apaga desde acá', async () => {
    // Sin esta casilla, honrar un «no me escriban más» —que llega por
    // teléfono— sería un UPDATE a mano en la base. El alta nace en `true`
    // porque quien deja su email al reservar espera que le llegue el turno.
    const onGuardado = abrir(EXISTENTE)
    const casilla = screen.getByRole('checkbox', { name: /recibe avisos/i })
    expect(casilla).toBeChecked()

    await userEvent.click(casilla)
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardado).toHaveBeenCalled())

    const cuerpo = llamadas.find((l) => l.metodo === 'PUT')!.cuerpo
    expect(cuerpo).toMatchObject({ acepta_avisos: false })
    // El control: apagar los avisos no da de baja al cliente. Son dos casillas
    // distintas y es fácil que la segunda escriba sobre la primera.
    expect(cuerpo).toMatchObject({ activo: true })
  })
})
