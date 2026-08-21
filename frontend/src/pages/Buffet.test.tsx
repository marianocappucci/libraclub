import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Lo que esta pantalla decide y un test puede hacer fallar:
 *
 * 1. que el **bajo mínimo** se vea en la fila del producto, no sólo como un
 *    contador: el que mira la tabla para reponer necesita saber CUÁL.
 * 2. que el carrito **sume por precio de lista** y no invente el total.
 * 3. que la venta de mostrador mande **medio de pago**, y la cargada a una
 *    cancha **no** — es la diferencia entre cobrar y fiar al turno.
 */

const productos = vi.fn()
const consumir = vi.fn()
const ajustar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    buffet: {
      ...(real.buffet as object),
      productos,
      consumir,
      ajustar,
      crearProducto: vi.fn(),
      editarProducto: vi.fn(),
    },
  }
})

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'u', name: 'U', role: 'admin' }, loading: false }),
}))

vi.mock('@/context/SucursalContext', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    useSucursal: () => ({
      sucursales: [], actual: 1, elegir: () => {}, recargar: () => {}, cargando: false,
    }),
  }
})

const { Buffet } = await import('./Buffet')

const GASEOSA = {
  item_id: 1, nombre: 'Gaseosa 500ml', precio: 1200, activo: true,
  stock: 24, stock_minimo: 6, bajo_minimo: false,
}
const AGUA = {
  item_id: 2, nombre: 'Agua', precio: 900, activo: true,
  stock: 4, stock_minimo: 6, bajo_minimo: true,
}

beforeEach(() => {
  productos.mockReset()
  consumir.mockReset()
  ajustar.mockReset()
  productos.mockResolvedValue([GASEOSA, AGUA])
  consumir.mockResolvedValue({ id: 1, numero: 'BUF-000001', total: 0, reserva_id: null })
})

describe('pantalla de buffet', () => {
  it('marca en la fila el producto que hay que reponer', async () => {
    render(<Buffet />)
    const fila = (await screen.findByText('Agua')).closest('tr')!
    // 🔑 En la fila, no sólo en el cartel de arriba: el cartel dice cuántos,
    // la fila dice cuál — y es la fila la que se mira para reponer.
    //
    // ⚠️ Se asierta **la marca** y no que el número esté: el `4` se dibuja igual
    // marcado o no, así que el assert obvio pasa con el resaltado apagado.
    // Verificado mutándolo.
    expect(within(fila).getByText('4')).toHaveClass('text-amber-700')

    const sana = screen.getByText('Gaseosa 500ml').closest('tr')!
    // Control negativo: sin él, pintar TODAS las filas también pasaría.
    expect(within(sana).getByText('24')).not.toHaveClass('text-amber-700')
  })

  it('avisa arriba qué falta, con el nombre y la cantidad', async () => {
    render(<Buffet />)
    const aviso = await screen.findByText(/Hay que reponer/)
    expect(aviso.parentElement).toHaveTextContent('Agua (4)')
    expect(aviso.parentElement).not.toHaveTextContent('Gaseosa')
  })

  it('sin nada bajo mínimo no hay cartel', async () => {
    productos.mockResolvedValue([GASEOSA])
    render(<Buffet />)
    await screen.findByText('Gaseosa 500ml')
    expect(screen.queryByText(/Hay que reponer/)).not.toBeInTheDocument()
  })

  it('el carrito suma por precio de lista y manda medio de pago', async () => {
    render(<Buffet />)
    await userEvent.click(await screen.findByRole('button', { name: /Vender/ }))

    const dialogo = await screen.findByRole('dialog')
    // Dos gaseosas y un agua: 1200×2 + 900 = 3300.
    const gaseosa = within(dialogo).getByText('Gaseosa 500ml')
    await userEvent.click(gaseosa)
    await userEvent.click(within(dialogo).getByLabelText('Agregar uno de Gaseosa 500ml'))
    await userEvent.click(within(dialogo).getByText('Agua'))

    expect(within(dialogo).getByText('$ 3.300,00')).toBeInTheDocument()

    await userEvent.click(within(dialogo).getByRole('button', { name: 'Cobrar' }))
    await waitFor(() => expect(consumir).toHaveBeenCalled())

    const [sucursalId, cuerpo] = consumir.mock.calls[0]
    expect(sucursalId).toBe(1)
    expect(cuerpo.lineas).toEqual([
      { item_id: 1, cantidad: '2' },
      { item_id: 2, cantidad: '1' },
    ])
    // 🔑 Venta de mostrador: se cobra en el acto, así que va el medio de pago.
    expect(cuerpo.reserva_id).toBeNull()
    expect(cuerpo.medio_pago).toBe('efectivo')
  })

  it('el stock se ve al vender, no sólo en la tabla', async () => {
    render(<Buffet />)
    await userEvent.click(await screen.findByRole('button', { name: /Vender/ }))
    const dialogo = await screen.findByRole('dialog')
    // El encargado tiene que ver que quedan 4 antes de prometer 6.
    expect(within(dialogo).getByText('4 en stock')).toBeInTheDocument()
  })

  it('quitar la última unidad saca la línea del carrito', async () => {
    render(<Buffet />)
    await userEvent.click(await screen.findByRole('button', { name: /Vender/ }))
    const dialogo = await screen.findByRole('dialog')
    await userEvent.click(within(dialogo).getByText('Agua'))
    // El control de cantidad sólo existe si la línea está en el carrito. Se
    // asierta sobre él y no sobre el importe: `$ 900,00` aparece tres veces
    // —precio del producto, importe de la línea y total—, así que contarlo
    // haría un test que se rompe al agregar cualquier columna.
    expect(within(dialogo).getByLabelText('Quitar uno de Agua')).toBeInTheDocument()
    expect(within(dialogo).getByRole('button', { name: 'Cobrar' })).toBeEnabled()

    await userEvent.click(within(dialogo).getByLabelText('Quitar uno de Agua'))
    expect(within(dialogo).queryByLabelText('Quitar uno de Agua')).not.toBeInTheDocument()
    // Sin líneas no se puede cobrar: el botón queda deshabilitado.
    expect(within(dialogo).getByRole('button', { name: 'Cobrar' })).toBeDisabled()
  })
})
