/**
 * El shim del detalle de comprobante: qué le dice este producto al kit.
 *
 * 🔴 **Existe por un defecto que ningún test veía.** El kit traía las tres rutas
 * de documentos hardcodeadas sin `/api` —así las sirve el router Jinja2 viejo de
 * Contalibra y Restolibra— y este producto no tiene ese router. `/facturas/1/pdf`
 * en esta SPA **no da 404**: cae en el catch-all y devuelve el `index.html` con
 * **200**, así que «Ver PDF» abría una pestaña con la aplicación adentro. Lo
 * reportó el humano el 2026-08-28 mirando `dev`.
 *
 * Lo que se prueba acá es **la costura**, que es lo único que es de este
 * producto: a dónde apuntan los botones y cuáles no van.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { FacturaDetalle } from './FacturaDetalle'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', name: 'Ana', role: 'admin' }, loading: false }),
}))

const FACTURA = {
  id: 7, tipo: 11, punto_venta: 3, numero: 41, fecha: '2026-08-28',
  cliente_cuit: '', cliente_razon: 'Ana Perez', items: [],
  subtotal: 14000, iva_amount: 0, total: 14000, concepto: 1,
  cae: '75123456789012', cae_vto: '20260906', observaciones: '',
  condicion_venta: 'Contado', total_cobrado: 0,
}

const DETALLE = {
  factura: FACTURA, tipo_label: 'Factura C', concepto_label: 'Productos',
  iva_label: '', notas_credito: [], notas_debito: [], factura_original: null,
  cobros: [], total_cobrado: 0, pendiente: 14000, cliente_email: '',
}

function json(cuerpo: unknown, status = 200) {
  return new Response(JSON.stringify(cuerpo), {
    status, headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  // Las dos rutas del motor **no existen en este producto**: contestan el HTML
  // del catch-all, que es justamente el escenario que rompía la pantalla entera
  // antes de que el kit comprobara la forma de la respuesta.
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const u = String(url)
    if (u.includes('/api/cajas') || u.includes('/api/ventas/medios-pago')) {
      return Promise.resolve(new Response('<!doctype html>', {
        status: 200, headers: { 'content-type': 'text/html' },
      }))
    }
    return Promise.resolve(json(DETALLE))
  }))
})

function montar() {
  render(
    <MemoryRouter initialEntries={['/facturas/7']}>
      <Routes><Route path="/facturas/:id" element={<FacturaDetalle />} /></Routes>
    </MemoryRouter>,
  )
}

describe('el detalle de comprobante de este producto', () => {
  it('🔴 «Ver PDF» apunta a la API, no al router que este producto no tiene', async () => {
    montar()
    expect(await screen.findByRole('link', { name: /Ver PDF/ }))
      .toHaveAttribute('href', '/api/facturas/7/pdf')
  })

  it('🔴 no ofrece «Ticket»: este producto no imprime uno', async () => {
    montar()
    // Control positivo: la pantalla cargó y el otro botón está. Sin esto, un
    // "no encontré el ticket" porque nada renderizó pasaría igual.
    expect(await screen.findByRole('link', { name: /Ver PDF/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Ticket/ })).toBeNull()
  })

  it('🔑 la pantalla sobrevive a que las rutas del motor devuelvan HTML', async () => {
    // Es el escenario real de este producto, y el que tiraba
    // `Cannot read properties of undefined` en el render.
    montar()
    // Se apunta a un control único de la pantalla y no a un texto: el tipo y el
    // número aparecen dos veces cada uno —en el encabezado y en el cuerpo—, así
    // que buscarlos por texto encuentra dos y falla por el selector, no por el
    // render. Lo que se quiere afirmar es «la pantalla llegó a dibujarse».
    expect(await screen.findByRole('button', { name: /Enviar por email/ }))
      .toBeInTheDocument()
  })
})
