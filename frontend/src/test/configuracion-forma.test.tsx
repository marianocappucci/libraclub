// La FORMA de la pantalla de Configuración de este producto.
//
// La pantalla la rinde `libra-ui/Configuracion`, que tiene sus propios tests:
// lo que se prueba acá es **lo que declara LibraClub**, que es lo único que
// vive en este repo y lo único que puede divergir del resto de la familia sin
// que nadie lo note.
//
// Tres declaraciones que si se escriben mal no rompen nada y arruinan la
// pantalla igual:
//
//  1. 🔴 **`rutaWebhook`.** El webhook de este producto vive en
//     `/api/portal/webhook`, no en `/webhooks/mercadopago`. Con la URL de la
//     familia, el complejo registraría en MercadoPago una ruta que no existe y
//     **ninguna reserva pagada desde el portal se confirmaría**.
//  2. 🔴 **El slug de la empresa de ARCA.** `servicios/facturacion.py` lee la
//     configuración con `EMPRESA = "complejo"`.
//  3. **El texto del interruptor de facturación automática.** Acá lo que se
//     cobra con el QR es un *turno* —cancha y buffet—, no una venta.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Configuracion } from '../pages/Configuracion'

let pedidos: { url: string; metodo: string; cuerpo: unknown }[] = []

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200, headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  pedidos = []
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const u = String(url)
    const metodo = init?.method ?? 'GET'
    pedidos.push({ url: u, metodo, cuerpo: init?.body ?? null })

    if (u.includes('/logo')) return Promise.resolve(new Response('', { status: 404 }))
    if (u.includes('/admin/smtp')) {
      return Promise.resolve(json({
        origen: 'entorno', host: '', port: 587, user: '', from_email: '', from_name: '',
        password_definida: false, password_indescifrable: false, configurado: false,
      }))
    }
    if (u.includes('/api/config/mercadopago')) {
      return Promise.resolve(json({
        mp_access_token: '', mp_access_token_cargado: false,
        mp_webhook_secret: '', mp_webhook_secret_cargado: false,
        mp_concepto_descripcion: '', mp_iva_rate: '0',
        mp_user_id: '', mp_pos_id: '', mp_auto_facturar_ventas: false,
      }))
    }
    if (u.includes('/config/arca/estado')) return Promise.resolve(json({ configurado: false }))
    if (u.includes('/config/arca')) return Promise.resolve(json(null))
    if (u.includes('/api/config/empresa')) {
      return Promise.resolve(json({
        empresa_nombre: '', empresa_direccion: '', empresa_cuit: '', empresa_telefono: '',
        empresa_email: '', empresa_iibb: '', empresa_iva_condition: 'Monotributista',
        empresa_inicio_actividades: '',
      }))
    }
    return Promise.resolve(json([]))
  }))
})

const montar = (ruta = '/configuracion') =>
  render(<MemoryRouter initialEntries={[ruta]}><Configuracion /></MemoryRouter>)

describe('la Configuración de LibraClub', () => {
  it('tiene las pestañas de la familia', async () => {
    montar()

    const pestanias = (await screen.findAllByRole('tab')).map((t) => t.textContent)
    expect(pestanias).toEqual(['Empresa', 'Integraciones', 'Datos / Backup'])
  })

  it('las tres integraciones están, en la sub-navegación', async () => {
    montar('/configuracion?seccion=integraciones')

    await screen.findAllByRole('tab')
    const navegacion = screen.getAllByRole('button', {
      name: /^(MercadoPago|ARCA \/ AFIP|Email \/ SMTP)$/,
    })
    expect(navegacion.map((b) => b.textContent)).toEqual([
      'MercadoPago', 'ARCA / AFIP', 'Email / SMTP',
    ])
  })

  it('🔴 la URL del webhook es la de ESTE producto, no la de la familia', async () => {
    // Con `/webhooks/mercadopago` el complejo registraría en MercadoPago una
    // ruta que acá no existe: el portal no confirmaría ninguna reserva pagada,
    // y desde la pantalla todo se vería configurado.
    montar('/configuracion?seccion=integraciones&integracion=mercadopago')

    expect(await screen.findByLabelText(/URL del webhook/))
      .toHaveValue(`${window.location.origin}/api/portal/webhook`)
  })

  it('el webhook secret está: sin él el portal no confirma ninguna reserva', async () => {
    montar('/configuracion?seccion=integraciones&integracion=mercadopago')

    expect(await screen.findByLabelText(/Webhook Secret/)).toBeInTheDocument()
  })

  it('el interruptor habla de turnos, no de ventas', async () => {
    montar('/configuracion?seccion=integraciones&integracion=mercadopago')

    expect(await screen.findByText(/los turnos cobrados por QR/)).toBeInTheDocument()
    expect(screen.queryByText(/las ventas cobradas por QR/)).toBeNull()
  })

  it('🔴 la fila de ARCA se crea con el slug que lee `servicios/facturacion.py`', async () => {
    montar('/configuracion?seccion=integraciones&integracion=arca')
    const usuario = userEvent.setup()

    await usuario.click(await screen.findByRole('button', { name: /Guardar ARCA/ }))

    const put = pedidos.find((p) => p.url.includes('/config/arca') && p.metodo === 'PUT')
    expect(put, 'no llegó ningún PUT a /config/arca').toBeTruthy()
    expect(JSON.parse(String(put!.cuerpo)).empresa).toBe('complejo')
  })

  it('ARCA sube el certificado: ya no hay dónde tipear una ruta del servidor', async () => {
    montar('/configuracion?seccion=integraciones&integracion=arca')

    expect(await screen.findByLabelText(/Certificado/)).toHaveAttribute('type', 'file')
    expect(screen.queryByLabelText(/Path del certificado/)).toBeNull()
  })

  it('los tutoriales nombran a LibraClub, no al producto del que salió la pantalla', async () => {
    montar('/configuracion?seccion=integraciones&integracion=email')

    expect(await screen.findAllByText(/contraseña de aplicación/)).not.toHaveLength(0)
    expect(screen.getByText('LibraClub')).toBeInTheDocument()
    expect(screen.queryByText('Contalibra')).toBeNull()
  })

  it('el botón de backup rápido está desde la primera pestaña', async () => {
    montar()

    expect(await screen.findByRole('link', { name: /Backup rápido/ }))
      .toHaveAttribute('href', '/api/config/backup-ahora')
  })
})
