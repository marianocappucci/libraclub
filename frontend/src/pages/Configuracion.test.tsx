/**
 * Las secciones de la Configuración de LibraClub.
 *
 * El armado y las secciones comunes viven en `libra-ui/Configuracion` y tienen
 * sus tests ahí. Lo que se prueba acá es **la declaración de este producto**:
 * que estén las cinco que le corresponden.
 *
 * ⚠️ **Una sección que falta no rompe nada**: simplemente no aparece, y nadie
 * lo nota hasta que alguien va a buscarla. Por eso hay un test que las cuenta.
 * Y la lista crece con ellas — un guard que cubre "las N de entonces" deja a la
 * siguiente naciendo sin cobertura.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Configuracion } from './Configuracion'

function json(cuerpo: unknown) {
  return new Response(JSON.stringify(cuerpo), {
    status: 200, headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((ruta: string) => {
    const u = String(ruta)
    if (u.includes('/config/empresa/logo')) {
      return Promise.resolve(new Response('', { status: 404 }))
    }
    if (u.includes('/config/empresa')) {
      return Promise.resolve(json({
        empresa_nombre: '', empresa_direccion: '', empresa_cuit: '',
        empresa_telefono: '', empresa_email: '', empresa_iibb: '',
        empresa_iva_condition: 'Monotributista', empresa_inicio_actividades: '',
      }))
    }
    if (u.includes('/config/backups')) return Promise.resolve(json([]))
    if (u.includes('/config/mercadopago')) {
      return Promise.resolve(json({
        access_token: '', user_id: '', pos_id: '', webhook_secret: '',
        auto_facturar: false, configurado: false,
      }))
    }
    return Promise.resolve(json(null))
  }))
})

const montar = () =>
  render(
    <MemoryRouter initialEntries={['/configuracion']}>
      <Routes>
        <Route path="/configuracion" element={<Configuracion />} />
      </Routes>
    </MemoryRouter>,
  )

describe('las secciones de LibraClub', () => {
  it('están las cinco que le corresponden', async () => {
    montar()

    for (const seccion of [
      'Empresa', 'Correo', 'Datos / Backup', 'ARCA', 'Mercado Pago',
    ]) {
      expect(await screen.findByRole('tab', { name: new RegExp(seccion) }))
        .toBeInTheDocument()
    }
  })
})
