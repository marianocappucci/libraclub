import { render, screen, within } from '@testing-library/react'
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

// 🔴 La pantalla ahora **pide los medios al backend** en vez de importar una
// copia. Se stubea el hook y no `fetch`: lo que estos tests miden es lo que la
// pantalla decide, no el pedido — el endpoint tiene su propio test del lado del
// backend (`tests/test_medios_pago.py`), que es donde vive el contrato.
//
// ⚠️ Con este doble, un cambio en la URL o en la forma de la respuesta **no se
// ve acá**. Es el límite de estos tests, y está puesto a propósito.
vi.mock('@/lib/medios-pago', () => ({
  useMediosDePago: () => ({
    medios: [
      { valor: 'efectivo', etiqueta: 'Efectivo' },
      { valor: 'transferencia', etiqueta: 'Transferencia' },
      { valor: 'mercadopago', etiqueta: 'Mercado Pago' },
    ],
    etiqueta: (v: string) =>
      ({ efectivo: 'Efectivo', transferencia: 'Transferencia',
         mercadopago: 'Mercado Pago', tarjeta: 'Tarjeta' })[v] ?? v,
  }),
}))

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

  it('🔴 acá NO se vende: la venta suelta se hace desde la Caja', async () => {
    // Pedido del humano el 2026-08-28: *"todo tiene que ir por el mismo lado"*.
    // Esta pantalla es de carga de productos y stock; el botón «Vender» que
    // estaba acá abría el mismo diálogo que ahora vive en la Caja, y tener dos
    // puertas para lo mismo es lo que dejaba el buffet suelto fuera del
    // mostrador.
    //
    // 🔑 Los tres tests que entraban por ese botón —el carrito, el stock a la
    // vista y el medio de pago— **no se borraron**: están en
    // `DialogoDeConsumo.test.tsx`, montando el diálogo directo.
    render(<Buffet />)
    await screen.findByText('Gaseosa 500ml')
    expect(screen.queryByRole('button', { name: /Vender/ })).not.toBeInTheDocument()
  })
})
