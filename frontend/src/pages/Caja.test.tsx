/**
 * La pantalla de Caja: el turno sobre un mostrador, los movimientos a la vista,
 * el egreso y la anulación.
 *
 * 🔴 **Lo que esto arregla no es cosmético.** Antes: el turno no sabía en qué
 * sede estaba, el arqueo sólo podía subir —no había forma de registrar plata que
 * sale— y `movimientos` **llegaba de la API y la pantalla lo tiraba**, así que
 * un monto mal tipeado sólo aparecía como una diferencia al cerrar, cuando ya no
 * se sabía cuál era.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Caja } from './Caja'

vi.mock('@/context/SucursalContext', () => ({
  useSucursal: () => ({ actual: 1, sucursales: [], elegir: vi.fn(), cargando: false }),
}))

const MOSTRADORES = [
  { id: 5, nombre: 'Mostrador', descripcion: '', medios_pago: [], activo: true, es_default: false, sucursal_id: 1 },
  { id: 6, nombre: 'Buffet', descripcion: '', medios_pago: [], activo: true, es_default: false, sucursal_id: 1 },
]

const MOVIMIENTOS = [
  { id: 11, fecha: '2026-08-28', tipo: 'ingreso' as const, concepto: 'Turno cancha 1', monto: 14000, medio_pago: 'efectivo' },
  { id: 12, fecha: '2026-08-28', tipo: 'egreso' as const, concepto: 'Retiro a banco', monto: 5000, medio_pago: 'efectivo' },
]

const estado = {
  hayTurno: true,
  mostradores: MOSTRADORES,
  movimientos: MOVIMIENTOS,
}

const llamadas: { metodo: string; ruta: string; cuerpo: unknown }[] = []

function json(cuerpo: unknown, status = 200) {
  return new Response(JSON.stringify(cuerpo), {
    status, headers: { 'content-type': 'application/json' },
  })
}

function resumen() {
  return {
    movimientos: estado.movimientos,
    pagos_por_medio: { efectivo: 9000 },
    total_ventas: 9000,
    efectivo_ventas: 9000,
  }
}

beforeEach(() => {
  llamadas.length = 0
  estado.hayTurno = true
  estado.mostradores = MOSTRADORES
  estado.movimientos = MOVIMIENTOS
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const u = String(url)
    let cuerpo: unknown = null
    try { cuerpo = init?.body ? JSON.parse(String(init.body)) : null } catch { /* vacío */ }
    llamadas.push({ metodo: init?.method ?? 'GET', ruta: u, cuerpo })

    if (u.includes('/api/cajas/medios-disponibles') || u.includes('/api/caja/medios-pago')) {
      return Promise.resolve(json([
        { valor: 'efectivo', etiqueta: 'Efectivo' },
        { valor: 'transferencia', etiqueta: 'Transferencia' },
      ]))
    }
    if (u.includes('/api/cajas')) return Promise.resolve(json(estado.mostradores))
    if (u.includes('/api/caja/motivos-de-egreso')) {
      return Promise.resolve(json(['Pago a proveedor', 'Retiro a banco']))
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
        resumen: resumen(),
      }))
    }
    return Promise.resolve(json(resumen()))
  }))
})

describe('abrir el turno sobre un mostrador', () => {
  beforeEach(() => { estado.hayTurno = false })

  it('🔑 ofrece los mostradores de la sucursal', async () => {
    render(<Caja />)
    const selector = await screen.findByLabelText('Caja')
    expect(within(selector).getAllByRole('option').map((o) => o.textContent))
      .toEqual(['Mostrador', 'Buffet'])
  })

  it('🔴 manda la caja elegida al abrir', async () => {
    const user = userEvent.setup()
    render(<Caja />)
    await user.selectOptions(await screen.findByLabelText('Caja'), '6')
    await user.click(screen.getByRole('button', { name: /Abrir caja/ }))

    await waitFor(() => {
      const alta = llamadas.find((l) => l.metodo === 'POST' && l.ruta.endsWith('/api/caja/turnos'))
      expect(alta).toBeTruthy()
      expect((alta!.cuerpo as { caja_id: number }).caja_id).toBe(6)
    })
  })

  it('🔴 sin mostradores lo dice, y no deja abrir', async () => {
    // El mostrador no puede resolverlo —crear una caja es de admin—, así que un
    // formulario que no funciona sin decir por qué manda a adivinar.
    estado.mostradores = []
    render(<Caja />)
    expect(await screen.findByText(/no tiene ninguna caja cargada/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Abrir caja/ })).toBeDisabled()
  })
})

describe('el turno abierto', () => {
  it('🔑 dice sobre qué mostrador está', async () => {
    render(<Caja />)
    expect(await screen.findByText('Mostrador')).toBeInTheDocument()
  })

  it('🔴 muestra los movimientos, que antes llegaban y se tiraban', async () => {
    render(<Caja />)
    expect(await screen.findByText('Turno cancha 1')).toBeInTheDocument()
    expect(screen.getByText('Retiro a banco')).toBeInTheDocument()
  })

  it('🔑 el egreso se muestra en negativo', async () => {
    // Es lo que hace que la lista se pueda sumar de arriba abajo y dé el
    // esperado: sin el signo, un retiro se lee como un cobro.
    render(<Caja />)
    const fila = (await screen.findByText('Retiro a banco')).closest('div')!.parentElement!
    expect(fila.textContent).toMatch(/−/)
  })

  it('🔴 anular pega en el endpoint de ESE movimiento', async () => {
    const user = userEvent.setup()
    render(<Caja />)
    await screen.findByText('Turno cancha 1')

    // 🔑 Se anula el **segundo** de la lista, no el primero. Con el primero, un
    // `anular(11)` hardcodeado pasaría igual — es lo que delató la mutación.
    await user.click(screen.getByRole('button', { name: 'Anular Retiro a banco' }))

    await waitFor(() => {
      expect(llamadas.some(
        (l) => l.metodo === 'DELETE' && l.ruta.endsWith('/api/caja/movimientos/12'),
      )).toBe(true)
    })
    // El control: no anuló el otro.
    expect(llamadas.some((l) => l.ruta.endsWith('/api/caja/movimientos/11'))).toBe(false)
  })
})

describe('el egreso', () => {
  it('🔴 manda motivo, monto y medio', async () => {
    const user = userEvent.setup()
    render(<Caja />)
    await user.click(await screen.findByRole('button', { name: /Registrar un egreso/ }))

    await user.selectOptions(await screen.findByLabelText('Motivo'), 'Retiro a banco')
    await user.type(screen.getByLabelText('Monto', { selector: '#monto-egreso' }), '3000')
    await user.click(screen.getByRole('button', { name: /^Registrar egreso$/ }))

    await waitFor(() => {
      const post = llamadas.find((l) => l.ruta.endsWith('/api/caja/egresos'))
      expect(post).toBeTruthy()
      expect(post!.cuerpo).toMatchObject({
        monto: '3000', motivo: 'Retiro a banco', medio_pago: 'efectivo',
      })
    })
  })

  it('🔑 los motivos salen del backend, no de constantes de la pantalla', async () => {
    // Si divergieran, la pantalla ofrecería un motivo que el POST rechaza con
    // 422 — y el operador no tendría forma de saber cuál sí vale.
    const user = userEvent.setup()
    render(<Caja />)
    await user.click(await screen.findByRole('button', { name: /Registrar un egreso/ }))

    const motivos = await screen.findByLabelText('Motivo')
    expect(within(motivos).getAllByRole('option').map((o) => o.textContent))
      .toEqual(['Pago a proveedor', 'Retiro a banco'])
    expect(llamadas.some((l) => l.ruta.endsWith('/api/caja/motivos-de-egreso'))).toBe(true)
  })
})
