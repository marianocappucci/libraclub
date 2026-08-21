import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Lo que se prueba acá es lo que esta pantalla decide, no el fetch:
 *
 * 1. que el extracto separe Debe de Haber **por `tipo`**. El motor manda el
 *    `monto` siempre positivo, así que una pantalla que mirara el signo del
 *    número pondría todo del lado del Debe — incluidos los pagos.
 * 2. que un saldo negativo se lea "a favor" y no como un número con menos.
 */

const deudores = vi.fn()
const ver = vi.fn()
const pagar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    cuentaCorriente: { ...(real.cuentaCorriente as object), deudores, ver, pagar },
  }
})

const { CuentaCorriente } = await import('./CuentaCorriente')

const MOVIMIENTOS = [
  { fecha: '2026-09-01', tipo: 'debito', concepto: 'Reserva del 01-09-2026 20:00',
    monto: 10000, medio: '', usuario_nombre: 'Admin' },
  // 🔑 El pago viene con monto POSITIVO, igual que el débito. Es la trampa que
  // este test existe para encontrar.
  { fecha: '2026-09-05', tipo: 'credito', concepto: 'Pago a cuenta',
    monto: 4000, medio: 'efectivo', usuario_nombre: 'Admin' },
]

beforeEach(() => {
  deudores.mockReset()
  ver.mockReset()
  pagar.mockReset()
  deudores.mockResolvedValue([{ cliente_id: 7, cliente: 'Los Martes', saldo: 6000 }])
  ver.mockResolvedValue({
    cliente_id: 7, cliente: 'Los Martes', saldo: 6000, movimientos: MOVIMIENTOS,
  })
})

async function abrirElDetalle() {
  render(<CuentaCorriente />)
  await userEvent.click(await screen.findByRole('button', { name: /Los Martes/ }))
  await waitFor(() => expect(ver).toHaveBeenCalledWith(7))
}

describe('pantalla de cuenta corriente', () => {
  it('separa Debe de Haber por el tipo y no por el signo del monto', async () => {
    await abrirElDetalle()

    const deuda = (await screen.findByText(/Reserva del 01-09-2026/)).closest('tr')!
    const pago = screen.getByText('Pago a cuenta').closest('tr')!
    // Columnas: Fecha, Concepto, Debe, Haber.
    const celdasDeuda = within(deuda).getAllByRole('cell')
    const celdasPago = within(pago).getAllByRole('cell')

    expect(celdasDeuda[2]).not.toHaveTextContent('')
    expect(celdasDeuda[3]).toHaveTextContent('')
    // Si la pantalla mirara el signo del número, este pago caería en Debe.
    expect(celdasPago[2]).toHaveTextContent('')
    expect(celdasPago[3]).not.toHaveTextContent('')
  })

  it('un saldo a favor se dice, no se muestra en negativo', async () => {
    deudores.mockResolvedValue([{ cliente_id: 7, cliente: 'Los Martes', saldo: -2500 }])
    render(<CuentaCorriente />)
    const fila = await screen.findByRole('button', { name: /Los Martes/ })
    expect(fila).toHaveTextContent(/a favor/)
    expect(fila).not.toHaveTextContent('-')
  })

  it('sin deudores explica dónde se fía, en vez de mostrar una tabla vacía', async () => {
    deudores.mockResolvedValue([])
    render(<CuentaCorriente />)
    expect(await screen.findByText(/Cargar a la cuenta/)).toBeInTheDocument()
  })

  it('el error del pago sin caja abierta se muestra y no se traga', async () => {
    // El backend contesta 409 con este texto cuando no hay turno abierto.
    pagar.mockRejectedValue(new Error('No hay una caja abierta. Abrí el turno antes de cobrar.'))
    await abrirElDetalle()

    await userEvent.type(screen.getByLabelText('Monto'), '1000')
    await userEvent.click(screen.getByRole('button', { name: /Registrar pago/ }))
    expect(await screen.findByText(/No hay una caja abierta/)).toBeInTheDocument()
  })
})
