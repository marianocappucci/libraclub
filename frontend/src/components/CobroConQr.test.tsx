/**
 * El cobro con QR del mostrador, desde el detalle de un turno.
 *
 * Lo que se prueba acá es el **cableado de la pantalla**: cuándo se ofrece el
 * botón, qué se llama al apretarlo, y qué pasa mientras se espera. Las reglas
 * del cobro —el monto que va al QR, la caja, la factura— tienen sus tests del
 * lado del backend (`tests/test_cobro_qr.py`).
 *
 * 🔑 **No hay ninguna imagen de QR que buscar.** Es el cartel impreso de la
 * caja: lo único que la pantalla hace es decir cuánto está cobrando.
 *
 * ⚠️ Se stubea `fetch` y no `libra-ui/api-client`: el cliente HTTP de este
 * producto es **propio** (`lib/api.ts`, sobre `fetch` pelado), no el del kit.
 * Mockear el del kit deja pasar todas las llamadas de verdad y el test falla
 * con un "no encontré el botón" que no dice nada de eso.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DetalleDeReserva } from './DetalleDeReserva'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', name: 'Ana', role: 'staff' }, loading: false }),
}))

const llamadas: { metodo: string; ruta: string }[] = []
const config = {
  disponible: true,
  autoFacturar: false,
  //: Lo que contesta `mp-status`. Los tests lo mueven a 'aprobado'.
  resultado: 'pendiente' as string,
}

function json(cuerpo: unknown) {
  return new Response(JSON.stringify(cuerpo), {
    status: 200, headers: { 'content-type': 'application/json' },
  })
}

function montarRed() {
  vi.stubGlobal('fetch', vi.fn((ruta: string, init?: RequestInit) => {
    const u = String(ruta)
    llamadas.push({ metodo: init?.method ?? 'GET', ruta: u })

    if (u.includes('/mp/estado')) {
      return Promise.resolve(json({
        disponible: config.disponible, auto_facturar: config.autoFacturar,
      }))
    }
    if (u.includes('/mp-status')) {
      return Promise.resolve(json({
        estado: config.resultado,
        payment_id: config.resultado === 'aprobado' ? '112233' : null,
        factura_id: null,
      }))
    }
    if (u.includes('/mp-qr')) {
      return Promise.resolve(json({ referencia: 'lc-5-abc123', monto: 14000 }))
    }
    if (u.includes('/consumos')) return Promise.resolve(json({ total: 0, lineas: [] }))
    if (u.includes('/productos')) return Promise.resolve(json([]))
    return Promise.resolve(json(null))
  }))
}

const CANCHA = {
  id: 1, sucursal_id: 1, nombre: 'Cancha 1', deporte: 'padel',
  duracion_turno_min: 90, techada: true, iluminacion: true, superficie: null,
  orden: 1, activa: true, observaciones: null,
}

function turno(estado: string) {
  return {
    comienza_at: '2026-08-20T18:00:00-03:00',
    termina_at: '2026-08-20T19:30:00-03:00',
    libre: false,
    precio: '14000.00',
    reserva_id: 5,
    estado,
    cliente: 'Ana Gomez',
    motivo: null,
  }
}

function montar(estado = 'confirmada', onCambiada = vi.fn()) {
  return render(
    <DetalleDeReserva
      abierto cancha={CANCHA} turno={turno(estado)}
      onCerrar={vi.fn()} onCambiada={onCambiada}
    />,
  )
}

beforeEach(() => {
  llamadas.length = 0
  config.disponible = true
  config.autoFacturar = false
  config.resultado = 'pendiente'
  montarRed()
})

describe('cuándo se ofrece el cobro con QR', () => {
  it('con la instancia configurada y el turno confirmado', async () => {
    montar('confirmada')
    expect(await screen.findByRole('button', { name: /Cobrar con QR/ })).toBeInTheDocument()
  })

  it('también sobre un turno jugado, que es cuando el grupo suele pagar', async () => {
    montar('jugada')
    expect(await screen.findByRole('button', { name: /Cobrar con QR/ })).toBeInTheDocument()
  })

  it('no sobre un turno cancelado', async () => {
    montar('cancelada')
    // Control positivo del selector: el diálogo SÍ está abierto. Sin esto, un
    // "no encontré nada" porque el componente no renderizó pasaría igual.
    expect(await screen.findByText(/Cancha 1/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cobrar con QR/ })).toBeNull()
  })

  it('🔴 sin MercadoPago configurado no hay botón, y SE DICE POR QUÉ', async () => {
    // 🔑 **Este test asertaba sólo la ausencia del botón, y por eso el defecto
    // le pasaba por al lado.** Hasta el 2026-08-28 el componente hacía
    // `return null` en este caso: el detalle del turno no mostraba **nada** —ni
    // el botón ni el motivo— y el test, que sólo pedía que el botón no
    // estuviera, seguía en verde. Es el cero esperado sin su positivo.
    //
    // Lo reportó el humano: *"pongo pagar con MercadoPago y no me dirige a
    // ningún lado"*. Tenía razón literal — la pantalla callaba.
    config.disponible = false
    montar('confirmada')
    expect(await screen.findByText(/Cancha 1/)).toBeInTheDocument()
    await waitFor(() =>
      expect(llamadas.some((l) => l.ruta.includes('/mp/estado'))).toBe(true),
    )
    expect(screen.queryByRole('button', { name: /Cobrar con QR/ })).toBeNull()
    // Lo que faltaba: el motivo, y dónde se arregla.
    expect(await screen.findByText(/faltan las credenciales de\s+MercadoPago/i))
      .toBeInTheDocument()
    expect(screen.getByText(/Configuración . Mercado Pago/i)).toBeInTheDocument()
  })

  it('🔑 y sobre un turno cancelado NO dice nada, ni siquiera eso', async () => {
    // El control del control. Sin esto, el arreglo de arriba se puede hacer
    // poniendo el cartel siempre — y entonces cada turno cancelado del día
    // llevaría un aviso sobre un cobro que nunca va a existir.
    config.disponible = false
    montar('cancelada')
    expect(await screen.findByText(/Cancha 1/)).toBeInTheDocument()
    expect(screen.queryByText(/faltan las credenciales/i)).toBeNull()
  })
})

describe('el cobro', () => {
  it('pone el monto en el QR y avisa que el cliente lo escanee', async () => {
    const user = userEvent.setup()
    montar()

    await user.click(await screen.findByRole('button', { name: /Cobrar con QR/ }))

    await waitFor(() => {
      expect(llamadas.some((l) => l.metodo === 'POST' && l.ruta === '/api/reservas/5/mp-qr'))
        .toBe(true)
    })
    expect(await screen.findByText(/Pedile al cliente que lo escanee/)).toBeInTheDocument()
  })

  it('al acreditarse avisa que se cobró y refresca la agenda', async () => {
    const user = userEvent.setup()
    const onCambiada = vi.fn()
    montar('confirmada', onCambiada)

    await user.click(await screen.findByRole('button', { name: /Cobrar con QR/ }))
    await screen.findByText(/Pedile al cliente que lo escanee/)

    config.resultado = 'aprobado'

    expect(await screen.findByText(/Cobrado por QR/, {}, { timeout: 8000 }))
      .toBeInTheDocument()
    expect(onCambiada).toHaveBeenCalled()
  }, 12000)

  it('cancelar baja el monto del QR', async () => {
    // 🔴 Una orden que queda puesta le cobra ese monto al próximo que escanee.
    const user = userEvent.setup()
    montar()

    await user.click(await screen.findByRole('button', { name: /Cobrar con QR/ }))
    await screen.findByText(/Pedile al cliente que lo escanee/)
    await user.click(screen.getByRole('button', { name: /Cancelar el cobro por QR/ }))

    await waitFor(() => {
      expect(llamadas.some((l) => l.metodo === 'DELETE' && l.ruta === '/api/reservas/5/mp-qr'))
        .toBe(true)
    })
  })

  it('avisa que la factura sale sola sólo si la instancia lo tiene prendido', async () => {
    config.autoFacturar = true
    const { unmount } = montar()
    expect(await screen.findByText(/factura solo al acreditarse/)).toBeInTheDocument()
    unmount()

    // Control negativo: con la automática apagada, la promesa no aparece. Sin
    // esto, un texto fijo pasaría el test de arriba.
    config.autoFacturar = false
    montar()
    await screen.findByRole('button', { name: /Cobrar con QR/ })
    expect(screen.queryByText(/factura solo al acreditarse/)).toBeNull()
  })
})
