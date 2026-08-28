/**
 * El detalle del turno, en su propia pantalla.
 *
 * 🔴 **Estos tests estaban en `Caja.test.tsx`** y se mudaron con el componente
 * el 2026-08-28, cuando el humano pidió que *"lo que la caja mueva entre todas
 * las canchas no tenga por qué verse en la pantalla de caja"*. Se mudaron y no
 * se borraron por una razón concreta: acá vive **la anulación**, que es el único
 * botón que corrige un cobro mal cargado. Sacar la lista sin darle un lugar
 * habría dejado esa acción sin camino.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { MovimientosDeCaja } from './MovimientosDeCaja'

const MOVIMIENTOS = [
  { id: 11, fecha: '2026-08-28', tipo: 'ingreso' as const, concepto: 'Turno cancha 1', monto: 14000, medio_pago: 'efectivo' },
  { id: 12, fecha: '2026-08-28', tipo: 'egreso' as const, concepto: 'Retiro a banco', monto: 5000, medio_pago: 'efectivo' },
]

const estado = { hayTurno: true, movimientos: MOVIMIENTOS }
const llamadas: { metodo: string; ruta: string }[] = []

function json(cuerpo: unknown, status = 200) {
  return new Response(JSON.stringify(cuerpo), {
    status, headers: { 'content-type': 'application/json' },
  })
}

function montar() {
  return render(<MemoryRouter><MovimientosDeCaja /></MemoryRouter>)
}

beforeEach(() => {
  llamadas.length = 0
  estado.hayTurno = true
  estado.movimientos = MOVIMIENTOS
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const u = String(url)
    llamadas.push({ metodo: init?.method ?? 'GET', ruta: u })
    if (u.includes('/api/caja/medios-pago')) {
      return Promise.resolve(json([
        { valor: 'efectivo', etiqueta: 'Efectivo' },
        { valor: 'transferencia', etiqueta: 'Transferencia' },
      ]))
    }
    if (u.includes('/api/caja/turnos/actual')) {
      if (!estado.hayTurno) return Promise.resolve(json(null))
      return Promise.resolve(json({
        turno: {
          id: 3, usuario_id: 1, caja_id: 5, caja_nombre: 'Mostrador',
          apertura: '2026-08-28T09:00:00-03:00', cierre: null, monto_inicial: 1000,
          monto_declarado_cierre: null, monto_esperado_cierre: null,
          estado: 'abierto', notas: '',
        },
        resumen: {
          movimientos: estado.movimientos,
          pagos_por_medio: { efectivo: 9000 },
          total_ventas: 9000,
          efectivo_ventas: 9000,
        },
      }))
    }
    return Promise.resolve(json(null))
  }))
})

describe('el detalle del turno', () => {
  it('🔴 muestra los movimientos, que antes llegaban y se tiraban', async () => {
    montar()
    expect(await screen.findByText('Turno cancha 1')).toBeInTheDocument()
    expect(screen.getByText('Retiro a banco')).toBeInTheDocument()
  })

  it('🔑 el egreso se muestra en negativo', async () => {
    // Es lo que hace que la lista se pueda sumar de arriba abajo y dé el
    // esperado: sin el signo, un retiro se lee como un cobro.
    montar()
    const fila = (await screen.findByText('Retiro a banco')).closest('div')!.parentElement!
    expect(fila.textContent).toMatch(/−/)
  })

  it('🔴 anular pega en el endpoint de ESE movimiento', async () => {
    const user = userEvent.setup()
    montar()
    await screen.findByText('Turno cancha 1')

    // 🔑 Se anula el **segundo** de la lista, no el primero. Con el primero, un
    // `anular(11)` hardcodeado pasaría igual — es lo que delató la mutación.
    await user.click(screen.getByRole('button', { name: 'Anular Retiro a banco' }))

    await waitFor(() => {
      expect(llamadas.some(
        (l) => l.metodo === 'DELETE' && l.ruta.endsWith('/api/caja/movimientos/12'),
      )).toBe(true)
    })
    expect(llamadas.some((l) => l.ruta.endsWith('/api/caja/movimientos/11'))).toBe(false)
  })

  it('🔑 sin caja abierta lo dice, y no muestra una lista vacía', async () => {
    // Son dos situaciones distintas —no hay turno, o el turno no movió nada— y
    // una lista vacía las cuenta igual.
    estado.hayTurno = false
    montar()
    expect(await screen.findByText(/No hay una caja abierta/i)).toBeInTheDocument()
  })

  it('🔑 con el turno abierto y sin movimientos, también lo dice', async () => {
    estado.movimientos = []
    montar()
    expect(await screen.findByText(/Todavía no cargaste nada/i)).toBeInTheDocument()
  })
})
