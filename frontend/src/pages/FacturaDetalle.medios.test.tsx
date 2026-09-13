/**
 * Los medios de cobro que este shim le pasa a `libra-ui/FacturaDetalle`.
 *
 * Prueba de costura, no del kit: la forma exacta de `mediosDeCobro`
 * (`{id, label}[]`) tiene que salir de `GET /api/caja/medios-pago`
 * (`{valor, etiqueta}[]`), que es lo que ofrece este producto. Se mockea el
 * componente del kit para capturar la prop tal cual llega — abrir el selector
 * de Radix en jsdom no está armado en esta suite (ver `test/setup.ts`), así que
 * inspeccionar la prop directamente es más fiel que simular un click que
 * ningún otro test de este repo ejercita todavía.
 */
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', name: 'Ana', role: 'admin' }, loading: false }),
}))

let propsRecibidas: Record<string, unknown> | null = null

vi.mock('libra-ui/FacturaDetalle', () => ({
  FacturaDetalle: (props: Record<string, unknown>) => {
    propsRecibidas = props
    return null
  },
}))

const { FacturaDetalle } = await import('./FacturaDetalle')

function json(cuerpo: unknown) {
  return new Response(JSON.stringify(cuerpo), {
    status: 200, headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  propsRecibidas = null
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (String(url).includes('/api/caja/medios-pago')) {
      return Promise.resolve(json([
        { valor: 'efectivo', etiqueta: 'Efectivo' },
        { valor: 'transferencia', etiqueta: 'Transferencia' },
      ]))
    }
    return Promise.resolve(json({}))
  }))
})

function montar() {
  render(
    <MemoryRouter initialEntries={['/facturas/7']}>
      <Routes><Route path="/facturas/:id" element={<FacturaDetalle />} /></Routes>
    </MemoryRouter>,
  )
}

describe('los medios de cobro que arma el shim', () => {
  // 🔑 Este control va PRIMERO a propósito. `useMediosDePago` cachea la lista a
  // nivel de módulo (`lib/medios-pago.ts`): si el test del mapeo corriera antes,
  // dejaría la caché cargada y este control encontraría la lista ya resuelta
  // desde el primer render, sin medir nada.
  it('control: antes de que resuelva el fetch, la prop arranca vacía y no undefined', () => {
    montar()
    expect(propsRecibidas?.mediosDeCobro).toEqual([])
  })

  it('mapea {valor, etiqueta} de /api/caja/medios-pago a {id, label}', async () => {
    montar()
    await waitFor(() => {
      expect(propsRecibidas?.mediosDeCobro).toEqual([
        { id: 'efectivo', label: 'Efectivo' },
        { id: 'transferencia', label: 'Transferencia' },
      ])
    })
  })
})
