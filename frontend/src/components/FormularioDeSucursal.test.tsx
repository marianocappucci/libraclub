import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FormularioDeSucursal } from './FormularioDeSucursal'
import type { Sucursal } from '@/lib/api'

const EXISTENTE: Sucursal = {
  id: 4,
  nombre: 'Complejo Centro',
  direccion: 'San Martín 100',
  localidad: 'Suipacha',
  telefono: '2324-401122',
  email: 'centro@complejo.com',
  punto_venta_arca: 3,
  horas_de_cancelacion: 24,
  activa: true,
  observaciones: 'La del techo nuevo',
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

function abrir(sucursal: Sucursal | null) {
  const onGuardada = vi.fn()
  render(
    <FormularioDeSucursal
      abierto
      sucursal={sucursal}
      onCerrar={vi.fn()}
      onGuardada={onGuardada}
    />,
  )
  return onGuardada
}

describe('formulario de sucursal', () => {
  it('🔑 un punto de venta vacío viaja como null, no como 0 ni como cadena', async () => {
    const onGuardada = abrir(null)
    await userEvent.type(screen.getByRole('textbox', { name: /nombre/i }), 'Complejo Sur')
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardada).toHaveBeenCalled())

    const cuerpo = llamadas.find((l) => l.metodo === 'POST')!.cuerpo
    // `Number('')` es 0, y el schema pide `ge=1`: mandar 0 sería un 422 sobre un
    // campo que el operador dejó vacío a propósito. Y `null` es lo único que el
    // índice único parcial deja repetir entre sucursales sin facturar.
    expect(cuerpo.punto_venta_arca).toBeNull()
  })

  it('los campos de texto vacíos viajan como null, no como cadena vacía', async () => {
    const onGuardada = abrir(null)
    await userEvent.type(screen.getByRole('textbox', { name: /nombre/i }), 'Complejo Sur')
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardada).toHaveBeenCalled())

    const cuerpo = llamadas.find((l) => l.metodo === 'POST')!.cuerpo
    // Con `""` la fila queda con una cadena vacía y la tabla muestra un hueco
    // donde debería mostrar el guión de "no tiene".
    for (const campo of ['direccion', 'localidad', 'telefono', 'email', 'observaciones']) {
      expect(cuerpo[campo], campo).toBeNull()
    }
  })

  it('🔑 al editar manda TODOS los campos, no sólo el tocado', async () => {
    const onGuardada = abrir(EXISTENTE)
    await userEvent.clear(screen.getByRole('textbox', { name: /nombre/i }))
    await userEvent.type(screen.getByRole('textbox', { name: /nombre/i }), 'Centro')
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardada).toHaveBeenCalled())

    const envio = llamadas.find((l) => l.metodo === 'PUT')!
    expect(envio.url).toBe('/api/sucursales/4')
    // El PUT reemplaza la fila: mandar sólo el nombre borraría el punto de venta
    // —y con él, la capacidad de facturar de esa sucursal— sin que nadie lo pida.
    expect(envio.cuerpo).toMatchObject({
      nombre: 'Centro',
      punto_venta_arca: 3,
      localidad: 'Suipacha',
      telefono: '2324-401122',
      observaciones: 'La del techo nuevo',
      activa: true,
      // La política de cancelación viaja igual que el punto de venta: mandar
      // sólo el nombre la borraría, y con ella la devolución automática de la
      // seña — sin que nadie lo haya pedido.
      horas_de_cancelacion: 24,
    })
  })

  it('🔑 vaciar la ventana de cancelación manda null, no cero', async () => {
    // `0` sería una política de «devolvemos hasta el minuto cero», o sea
    // siempre. `null` es «esta sucursal no devuelve automáticamente», que es lo
    // que el operador quiso decir al borrar el campo. Un `Number('')` da `0` y
    // por eso el `set` mira si el string está vacío antes de convertir.
    const onGuardada = abrir(EXISTENTE)
    await userEvent.clear(screen.getByRole('spinbutton', { name: /horas de anticipación/i }))
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardada).toHaveBeenCalled())

    expect(llamadas.find((l) => l.metodo === 'PUT')!.cuerpo.horas_de_cancelacion).toBeNull()
  })

  it('no llama a la API sin nombre', async () => {
    abrir(null)
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/necesita un nombre/i)
    expect(llamadas.filter((l) => l.metodo !== 'GET')).toHaveLength(0)
  })
})
