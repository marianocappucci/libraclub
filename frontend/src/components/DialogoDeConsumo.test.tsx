import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El diálogo con `reservaId`, que es el caso del gate de F4 y el que la
 * pantalla de buffet no ejercita: cargar el consumo a la cancha **sin cobrarlo**.
 *
 * Existe porque la mutación *"el consumo de una cancha también manda medio de
 * pago"* sobrevivía a los tests de `Buffet.tsx`: ahí el diálogo se abre siempre
 * con `reservaId = null`.
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
  ])
  consumir.mockResolvedValue({ id: 1, numero: 'BUF-000001', total: 1200, reserva_id: 7 })
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
