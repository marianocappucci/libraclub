import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El extracto de un cliente y el cobro.
 *
 * Lo que se prueba es lo que esta pantalla decide, no el fetch:
 *
 * 1. que Cargo y Abono se separen **por `tipo`**. El motor manda el `monto`
 *    siempre positivo, así que una pantalla que mirara el signo del número
 *    pondría todo del lado del cargo — incluidos los pagos. Es el mismo defecto
 *    que cuidaba el test del Debe/Haber, que este reemplaza;
 * 2. que los dos totales se partan por ese mismo criterio;
 * 3. que los campos del diálogo lleguen al backend, y no se pierdan en el
 *    camino después de haberse tecleado.
 */

const ver = vi.fn()
const pagar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    cuentaCorriente: { ...(real.cuentaCorriente as object), ver, pagar },
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

const { CuentaCorrienteDetalle } = await import('./CuentaCorrienteDetalle')

const MOVIMIENTOS = [
  { fecha: '2026-09-01', tipo: 'debito', concepto: 'Reserva del 01-09-2026 20:00',
    monto: 10000, referencia: 'reserva-3', medio: '', usuario_nombre: 'Admin' },
  // 🔑 El pago viene con monto POSITIVO, igual que el débito. Es la trampa que
  // este test existe para encontrar.
  { fecha: '2026-09-05', tipo: 'credito', concepto: 'Pago a cuenta',
    monto: 4000, referencia: 'TRF-99', medio: 'transferencia', usuario_nombre: 'Encargada' },
]

const CUENTA = {
  cliente_id: 7, cliente: 'Los Martes', saldo: 6000, movimientos: MOVIMIENTOS,
}

function montar() {
  return render(
    <MemoryRouter initialEntries={['/cuenta-corriente/7']}>
      <Routes>
        <Route path="/cuenta-corriente/:id" element={<CuentaCorrienteDetalle />} />
        <Route path="/cuenta-corriente" element={<p>listado</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

function tarjeta(nombre: string): HTMLElement {
  return screen.getByText(nombre).closest('[data-slot="card"]') as HTMLElement
}

beforeEach(() => {
  ver.mockReset().mockResolvedValue(CUENTA)
  pagar.mockReset().mockResolvedValue({ cliente_id: 7, cliente: 'Los Martes', saldo: 5000 })
})

describe('extracto de la cuenta', () => {
  it('🔑 separa Cargo de Abono por el tipo y no por el signo del monto', async () => {
    montar()
    const deuda = (await screen.findByText(/Reserva del 01-09-2026/)).closest('tr')!
    const pago = screen.getByText('Pago a cuenta').closest('tr')!

    expect(within(deuda).getByText('Cargo')).toBeInTheDocument()
    // Si la pantalla mirara el signo del número, este pago caería en Cargo.
    expect(within(pago).getByText('Abono')).toBeInTheDocument()
    expect(within(pago).queryByText('Cargo')).not.toBeInTheDocument()

    // Y el signo de la columna Monto sale del mismo lado. `−` es el menos
    // tipográfico (U+2212), no un guion.
    expect(deuda).toHaveTextContent(/\+\s*\$/)
    expect(pago).toHaveTextContent(/−\s*\$/)
  })

  it('🔑 los totales también se parten por tipo', async () => {
    montar()
    await screen.findByText(/Reserva del 01-09-2026/)
    // Sumar por signo daría 14.000 en cargado y 0 en abonado.
    expect(tarjeta('Total cargado')).toHaveTextContent(/10\.000,00/)
    expect(tarjeta('Total abonado')).toHaveTextContent(/4\.000,00/)
    expect(tarjeta('Total cargado')).not.toHaveTextContent(/14\.000,00/)
  })

  it('muestra el usuario y el medio de cada movimiento', async () => {
    montar()
    const pago = (await screen.findByText('Pago a cuenta')).closest('tr')!
    expect(pago).toHaveTextContent('Encargada')
    expect(pago).toHaveTextContent('Transferencia')
    expect(pago).toHaveTextContent('TRF-99')
  })

  it('el saldo del título lo trae el backend, no la resta de los totales', async () => {
    // Se manda un saldo que NO es cargado − abonado: si la pantalla lo
    // recalculara, mostraría 6.000 y no 1.234.
    ver.mockResolvedValue({ ...CUENTA, saldo: 1234 })
    montar()
    expect(await screen.findByText(/Debe/)).toHaveTextContent(/1\.234,00/)
  })
})

describe('el cobro', () => {
  async function abrirElDialogo() {
    montar()
    await userEvent.click(await screen.findByRole('button', { name: /Registrar pago/ }))
    return screen.findByRole('dialog')
  }

  it('precarga el monto con lo que el cliente debe', async () => {
    await abrirElDialogo()
    expect(screen.getByLabelText('Monto')).toHaveValue('6000')
  })

  it('🔑 la fecha, el concepto y la referencia que se teclean llegan al backend', async () => {
    await abrirElDialogo()

    await userEvent.clear(screen.getByLabelText('Monto'))
    await userEvent.type(screen.getByLabelText('Monto'), '1000')
    // `fireEvent` para el `type="date"`: escribirlo tecla por tecla depende del
    // formato de la máquina, y acá lo que importa es el valor que viaja.
    fireEvent.change(screen.getByLabelText('Fecha'), { target: { value: '2026-09-10' } })
    await userEvent.type(screen.getByLabelText('Concepto'), 'Seña del torneo')
    await userEvent.type(screen.getByLabelText(/Referencia/), 'TRF-4412')
    await userEvent.selectOptions(screen.getByLabelText('Medio'), 'transferencia')

    await userEvent.click(screen.getByRole('button', { name: /Registrar pago/ }))

    await waitFor(() =>
      expect(pagar).toHaveBeenCalledWith(7, {
        monto: '1000',
        medio_pago: 'transferencia',
        fecha: '2026-09-10',
        concepto: 'Seña del torneo',
        referencia: 'TRF-4412',
      }),
    )
  })

  it('el error del pago sin caja abierta se muestra y no se traga', async () => {
    // El backend contesta 409 con este texto cuando no hay turno abierto.
    pagar.mockRejectedValue(new Error('No hay una caja abierta. Abrí el turno antes de cobrar.'))
    await abrirElDialogo()

    await userEvent.click(screen.getByRole('button', { name: /Registrar pago/ }))
    expect(await screen.findByText(/No hay una caja abierta/)).toBeInTheDocument()
    // Y el diálogo sigue abierto: cerrarlo con el error adentro lo esconde.
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('un cobro que salió bien recarga el extracto', async () => {
    await abrirElDialogo()
    await userEvent.click(screen.getByRole('button', { name: /Registrar pago/ }))
    // Una vez al montar y otra después del pago: sin la segunda, la pantalla
    // sigue mostrando el saldo viejo con la plata ya cobrada.
    await waitFor(() => expect(ver).toHaveBeenCalledTimes(2))
  })
})
