import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El listado de cobranza, después de converger con el de Contalibra.
 *
 * La tabla la dibuja `libra-ui/data-table` y la prueba el kit. Lo que se fija
 * acá es lo que **decide esta pantalla**:
 *
 * 1. que el total por cobrar sea el que manda el backend y no uno sumado acá —
 *    el mock devuelve a propósito un total que NO es la suma de la columna;
 * 2. que un saldo negativo se lea "a favor" y no como un número con menos;
 * 3. que abrir una cuenta lleve a la del cliente que se tocó, y no a otra.
 */

const deudores = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    cuentaCorriente: { ...(real.cuentaCorriente as object), deudores },
  }
})

const { CuentaCorriente } = await import('./CuentaCorriente')

const DEUDOR = { cliente_id: 7, cliente: 'Los Martes', saldo: 6000 }
const A_FAVOR = { cliente_id: 9, cliente: 'Adelantados FC', saldo: -2500 }

/** Sirve para leer a qué cuenta se navegó, sin montar la pantalla de detalle. */
function DetalleFalso() {
  const { id } = useParams()
  return <p>detalle del cliente {id}</p>
}

function montar() {
  return render(
    <MemoryRouter initialEntries={['/cuenta-corriente']}>
      <Routes>
        <Route path="/cuenta-corriente" element={<CuentaCorriente />} />
        <Route path="/cuenta-corriente/:id" element={<DetalleFalso />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  deudores.mockReset()
  // 🔑 6000 y no 3500: el saldo a favor de Adelantados **no** compensa la deuda
  // de Los Martes. Si esta pantalla sumara la columna daría 3500, y el test de
  // abajo lo agarra.
  deudores.mockResolvedValue({ deudores: [DEUDOR, A_FAVOR], total_deuda: 6000 })
})

describe('listado de cuenta corriente', () => {
  it('🔑 muestra el total que manda el backend, no la suma de la columna', async () => {
    montar()
    const total = (await screen.findByText('Total por cobrar')).closest(
      '[data-slot="card"]',
    )!
    expect(total).toHaveTextContent(/6\.000,00/)
    // La suma de la columna, que es lo que saldría si se calculara acá.
    expect(total).not.toHaveTextContent(/3\.500,00/)
  })

  it('sin nada que cobrar no ocupa la pantalla con una tarjeta en cero', async () => {
    // El control del test de arriba: si la tarjeta se dibujara siempre, este
    // pasaría igual y aquél no estaría probando que el total llegó.
    deudores.mockResolvedValue({ deudores: [A_FAVOR], total_deuda: 0 })
    montar()
    expect(await screen.findByText('Adelantados FC')).toBeInTheDocument()
    expect(screen.queryByText('Total por cobrar')).not.toBeInTheDocument()
  })

  it('un saldo a favor se dice, no se muestra en negativo', async () => {
    montar()
    const fila = (await screen.findByText('Adelantados FC')).closest('tr')!
    expect(fila).toHaveTextContent(/a favor/i)
    expect(fila).not.toHaveTextContent('-2')
    // Y el que debe se distingue del que tiene a favor por el TONO, no por el
    // texto: es lo que `data-tono` existe para poder afirmar sin atarse a la
    // clase que emite Tailwind.
    const deudor = (await screen.findByText('Los Martes')).closest('tr')!
    expect(within(deudor).getByText(/Debe/).closest('[data-slot="badge"]'))
      .toHaveAttribute('data-tono', 'atencion')
    expect(within(fila).getByText(/a favor/i).closest('[data-slot="badge"]'))
      .toHaveAttribute('data-tono', 'ok')
  })

  it('🔑 el ojo abre la cuenta del cliente de ESA fila', async () => {
    montar()
    // Se toca el segundo, no el primero: con el primero, un botón que navegara
    // siempre al de arriba pasaría el test igual.
    await userEvent.click(
      await screen.findByRole('button', { name: 'Ver la cuenta de Adelantados FC' }),
    )
    expect(await screen.findByText('detalle del cliente 9')).toBeInTheDocument()
  })

  it('sin deudores explica dónde se fía, en vez de mostrar una tabla vacía', async () => {
    deudores.mockResolvedValue({ deudores: [], total_deuda: 0 })
    montar()
    expect(await screen.findByText(/Cargar a la cuenta/)).toBeInTheDocument()
  })
})
