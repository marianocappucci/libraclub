import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El diálogo de consumo, en sus dos modos.
 *
 * Nació cubriendo sólo el caso `reservaId`: cargar el consumo a la cancha **sin
 * cobrarlo**, que la pantalla de buffet no ejercitaba —ahí el diálogo se abría
 * siempre con `reservaId = null`— y por eso la mutación *"el consumo de una
 * cancha también manda medio de pago"* le sobrevivía.
 *
 * 🔑 **Y desde el 2026-08-28 cubre también el otro**, el de la venta suelta.
 * Esos tres tests estaban en `Buffet.test.tsx` y entraban por su botón
 * «Vender»; ese botón se retiró cuando la venta suelta se mudó a la Caja —*"todo
 * tiene que ir por el mismo lado"*—, así que se mudaron acá, montando el diálogo
 * directo. Borrarlos habría dejado sin cobertura el carrito, el stock a la vista
 * y el medio de pago de la venta que **sí** cobra.
 */

const productos = vi.fn()
const consumir = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    buffet: { ...(real.buffet as object), productos, consumir },
  }
})

const { DialogoDeConsumo } = await import('./DialogoDeConsumo')

beforeEach(() => {
  productos.mockReset()
  consumir.mockReset()
  productos.mockResolvedValue([
    { item_id: 1, nombre: 'Gaseosa 500ml', precio: 1200, activo: true,
      stock: 24, stock_minimo: 6, bajo_minimo: false },
    { item_id: 2, nombre: 'Agua', precio: 900, activo: true,
      stock: 4, stock_minimo: 6, bajo_minimo: true },
  ])
  consumir.mockResolvedValue({ id: 1, numero: 'BUF-000001', total: 1200, reserva_id: 7 })
  // 🔴 **Los medios de pago vienen del backend, no de una constante.** Montado
  // directo, el diálogo no tiene quién le conteste `/api/caja/medios-pago` y su
  // selector queda vacío — con lo cual el modo que **sí** cobra viajaría sin
  // medio y el test lo leería como un cambio de comportamiento. Entrando por la
  // pantalla de Buffet esto no hacía falta: el stub estaba allá.
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(
    JSON.stringify([
      { valor: 'efectivo', etiqueta: 'Efectivo' },
      { valor: 'transferencia', etiqueta: 'Transferencia' },
    ]),
    { headers: { 'content-type': 'application/json' } },
  ))))
})

describe('cargar consumo a una cancha', () => {
  it('NO manda medio de pago: se cobra con el turno', async () => {
    render(
      <DialogoDeConsumo
        abierto
        sucursalId={1}
        reservaId={7}
        onCerrar={() => {}}
        onCargado={() => {}}
      />,
    )
    const dialogo = await screen.findByRole('dialog')
    await userEvent.click(within(dialogo).getByText('Gaseosa 500ml'))
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Cargar' }))

    await waitFor(() => expect(consumir).toHaveBeenCalled())
    const cuerpo = consumir.mock.calls[0][1]
    // 🔑 Si mandara medio de pago, el backend lo cobraría en el acto **y** otra
    // vez al facturar el turno. Es la diferencia entre fiar y cobrar dos veces.
    expect(cuerpo.medio_pago).toBeNull()
    expect(cuerpo.reserva_id).toBe(7)
  })

  it('no ofrece elegir cómo cobrar, y lo explica', async () => {
    render(
      <DialogoDeConsumo
        abierto
        sucursalId={1}
        reservaId={7}
        onCerrar={() => {}}
        onCargado={() => {}}
      />,
    )
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).queryByText('Cobrar con')).not.toBeInTheDocument()
    expect(within(dialogo).getByText(/se cobra y se factura junto con el turno/i))
      .toBeInTheDocument()
  })

  it('el botón dice Cargar y no Cobrar', async () => {
    render(
      <DialogoDeConsumo
        abierto
        sucursalId={1}
        reservaId={7}
        onCerrar={() => {}}
        onCargado={() => {}}
      />,
    )
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByRole('button', { name: 'Cargar' })).toBeInTheDocument()
    expect(within(dialogo).queryByRole('button', { name: 'Cobrar' })).not.toBeInTheDocument()
  })
})

describe('la venta suelta, que se cobra en el acto', () => {
  // 🔴 Estos tres entraban por el botón «Vender» de la pantalla de Buffet, que
  // se retiró: la venta suelta se hace desde la Caja. Se mudaron y no se
  // borraron porque son lo único que cubre el carrito y el cobro del modo que
  // **sí** mueve plata.
  function montar() {
    return render(
      <DialogoDeConsumo
        abierto
        sucursalId={1}
        reservaId={null}
        onCerrar={() => {}}
        onCargado={() => {}}
      />,
    )
  }

  it('el carrito suma por precio de lista y manda medio de pago', async () => {
    montar()
    const dialogo = await screen.findByRole('dialog')
    // Se espera a que los medios lleguen: el default se fija en un efecto,
    // y sin esperarlo el cobro saldría con el medio en blanco por carrera.
    await waitFor(() => expect(
      within(dialogo).getByLabelText('Cobrar con')).toHaveValue('efectivo'))
    // Dos gaseosas y un agua: 1200×2 + 900 = 3300.
    await userEvent.click(await within(dialogo).findByText('Gaseosa 500ml'))
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
    // 🔑 Venta suelta: se cobra en el acto, así que va el medio de pago. Es la
    // diferencia con el otro describe de este mismo archivo.
    expect(cuerpo.reserva_id).toBeNull()
    expect(cuerpo.medio_pago).toBe('efectivo')
  })

  it('el stock se ve al vender, no sólo en la tabla', async () => {
    montar()
    const dialogo = await screen.findByRole('dialog')
    // El encargado tiene que ver que quedan 4 antes de prometer 6.
    expect(await within(dialogo).findByText('4 en stock')).toBeInTheDocument()
  })

  it('quitar la última unidad saca la línea del carrito', async () => {
    montar()
    const dialogo = await screen.findByRole('dialog')
    await userEvent.click(await within(dialogo).findByText('Agua'))
    // El control de cantidad sólo existe si la línea está en el carrito. Se
    // asierta sobre él y no sobre el importe: `$ 900,00` aparece tres veces
    // —precio del producto, importe de la línea y total—, así que contarlo
    // haría un test que se rompe al agregar cualquier columna.
    expect(within(dialogo).getByLabelText('Quitar uno de Agua')).toBeInTheDocument()
    expect(within(dialogo).getByRole('button', { name: 'Cobrar' })).toBeEnabled()

    await userEvent.click(within(dialogo).getByLabelText('Quitar uno de Agua'))
    expect(within(dialogo).queryByLabelText('Quitar uno de Agua')).not.toBeInTheDocument()
    expect(within(dialogo).getByRole('button', { name: 'Cobrar' })).toBeDisabled()
  })
})
