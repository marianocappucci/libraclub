/**
 * El cobro del turno desde el detalle de la reserva.
 *
 * Lo que se prueba acá es el **cableado de la pantalla**: cuándo aparece la
 * sección, con qué llega el monto, qué se manda al cobrar y qué muestra
 * después. Las reglas —el vínculo con el comprobante, el buffet en el total, la
 * caja abierta— tienen sus tests del lado del backend
 * (`tests/test_cobro_del_turno.py`), donde hay una base de verdad.
 *
 * 🔑 **Esta sección es lo que la pantalla de Caja no puede dar.** Ahí el cobro
 * se carga como monto más concepto libre, sin vínculo con nada, y el
 * comprobante del turno queda viéndose «sin cobrar» sobre plata que ya entró.
 *
 * ⚠️ Se stubea `fetch` y no `libra-ui/api-client`: el cliente HTTP de este
 * producto es propio (`lib/api.ts`, sobre `fetch` pelado). Mockear el del kit
 * deja pasar las llamadas de verdad. Mismo motivo que en `CobroConQr.test.tsx`.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DetalleDeReserva } from './DetalleDeReserva'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', name: 'Ana', role: 'staff' }, loading: false }),
}))

const llamadas: { metodo: string; ruta: string; cuerpo: unknown }[] = []

const estado = {
  //: Lo que contesta `GET /api/reservas/:id/cobros`.
  cobros: {
    total: 14000,
    cobrado: 0,
    pendiente: 14000,
    cobros: [] as { id: number; fecha: string; monto: number; medio_pago: string; concepto: string; factura_id: number | null }[],
  },
  //: 503 cuando la instancia no tiene facturación configurada.
  hayBase: true,
}

function json(cuerpo: unknown, status = 200) {
  return new Response(JSON.stringify(cuerpo), {
    status, headers: { 'content-type': 'application/json' },
  })
}

function montarRed() {
  vi.stubGlobal('fetch', vi.fn((ruta: string, init?: RequestInit) => {
    const u = String(ruta)
    let cuerpo: unknown = null
    try {
      cuerpo = init?.body ? JSON.parse(String(init.body)) : null
    } catch { cuerpo = String(init?.body) }
    llamadas.push({ metodo: init?.method ?? 'GET', ruta: u, cuerpo })

    if (u.includes('/cobros')) {
      if (!estado.hayBase) {
        return Promise.resolve(json({ detail: 'falta LIBRACLUB_LIBRACORE_DATABASE_URL' }, 503))
      }
      if ((init?.method ?? 'GET') === 'POST') {
        const monto = Number((cuerpo as { monto: string }).monto)
        estado.cobros = {
          ...estado.cobros,
          cobrado: estado.cobros.cobrado + monto,
          pendiente: Math.max(0, estado.cobros.pendiente - monto),
          cobros: [
            ...estado.cobros.cobros,
            {
              id: estado.cobros.cobros.length + 1, fecha: '2026-08-28',
              monto, medio_pago: (cuerpo as { medio_pago: string }).medio_pago,
              concepto: 'Turno', factura_id: null,
            },
          ],
        }
      }
      return Promise.resolve(json(estado.cobros))
    }
    if (u.includes('/caja/medios-pago')) {
      return Promise.resolve(json([
        { valor: 'efectivo', etiqueta: 'Efectivo' },
        { valor: 'transferencia', etiqueta: 'Transferencia' },
      ]))
    }
    if (u.includes('/mp/estado')) {
      return Promise.resolve(json({ disponible: false, auto_facturar: false }))
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

function turno(est: string) {
  return {
    comienza_at: '2026-08-20T18:00:00-03:00',
    termina_at: '2026-08-20T19:30:00-03:00',
    libre: false,
    precio: '14000.00',
    reserva_id: 5,
    estado: est,
    cliente: 'Ana Gomez',
    motivo: null,
  }
}

function montar(est = 'confirmada', onCambiada = vi.fn()) {
  return render(
    <DetalleDeReserva
      abierto cancha={CANCHA} turno={turno(est)}
      onCerrar={vi.fn()} onCambiada={onCambiada}
    />,
  )
}

function cobrosPosteados() {
  return llamadas.filter((l) => l.metodo === 'POST' && l.ruta.includes('/cobros'))
}

beforeEach(() => {
  llamadas.length = 0
  estado.hayBase = true
  estado.cobros = { total: 14000, cobrado: 0, pendiente: 14000, cobros: [] }
  montarRed()
})

describe('cuándo aparece el cobro del turno', () => {
  it('sobre un turno confirmado', async () => {
    montar('confirmada')
    expect(await screen.findByText('Cobro del turno')).toBeInTheDocument()
  })

  it('también sobre uno jugado, que es cuando el grupo suele pagar', async () => {
    montar('jugada')
    expect(await screen.findByText('Cobro del turno')).toBeInTheDocument()
  })

  it('no sobre uno cancelado', async () => {
    montar('cancelada')
    // Control positivo del selector: el diálogo SÍ está abierto. Sin esto, un
    // "no encontré nada" porque el componente no renderizó pasaría igual.
    expect(await screen.findByText(/Cancha 1/)).toBeInTheDocument()

    // 🔴 **Y se espera a que el pedido vuelva antes de mirar.** La primera
    // versión asertaba la ausencia enseguida y pasaba porque los datos todavía
    // no habían llegado, no porque el estado la escondiera: con el guard de
    // estados sacado seguía en verde. Lo delató la mutación.
    await waitFor(() => {
      expect(llamadas.some((l) => l.ruta.includes('/cobros'))).toBe(true)
    })
    expect(screen.queryByText('Cobro del turno')).toBeNull()
  })

  it('🔴 no aparece si la instancia no tiene facturación configurada', async () => {
    // El endpoint contesta 503 nombrando la variable. No es un error que
    // mostrarle al mostrador: es que este complejo no lleva caja contra
    // LibraCore, y una sección rota es peor que ninguna.
    estado.hayBase = false
    montar('confirmada')
    expect(await screen.findByText(/Cancha 1/)).toBeInTheDocument()
    await waitFor(() => expect(llamadas.some((l) => l.ruta.includes('/cobros'))).toBe(true))
    expect(screen.queryByText('Cobro del turno')).toBeNull()
  })
})

describe('lo que se cobra', () => {
  it('🔑 el monto arranca en el pendiente, no en cero ni en el total', async () => {
    estado.cobros = { total: 14000, cobrado: 4000, pendiente: 10000, cobros: [] }
    montar()
    await screen.findByText('Cobro del turno')
    // Es el número que el mostrador va a apretar sin mirar: si arrancara en el
    // total, cobraría de más sobre un turno con seña.
    await waitFor(() => {
      expect((screen.getByLabelText('Monto') as HTMLInputElement).value).toBe('10000')
    })
  })

  it('🔴 manda el monto y el medio elegidos a ESA reserva', async () => {
    const user = userEvent.setup()
    montar()
    await screen.findByText('Cobro del turno')

    await user.selectOptions(screen.getByLabelText('Medio'), 'transferencia')
    await user.click(screen.getByRole('button', { name: /^Cobrar$/ }))

    await waitFor(() => expect(cobrosPosteados()).toHaveLength(1))
    const enviado = cobrosPosteados()[0]
    expect(enviado.ruta).toContain('/api/reservas/5/cobros')
    expect(enviado.cuerpo).toEqual({ monto: '14000', medio_pago: 'transferencia' })
  })

  it('una seña deja el resto pendiente y el formulario listo para el saldo', async () => {
    const user = userEvent.setup()
    montar()
    await screen.findByText('Cobro del turno')

    const monto = screen.getByLabelText('Monto')
    await user.clear(monto)
    await user.type(monto, '4000')
    await user.click(screen.getByRole('button', { name: /^Cobrar$/ }))

    // Queda el saldo, y el campo ya lo propone.
    expect(await screen.findByText(/Pendiente/)).toBeInTheDocument()
    await waitFor(() => {
      expect((screen.getByLabelText('Monto') as HTMLInputElement).value).toBe('10000')
    })
  })

  it('cobrado del todo, ya no ofrece cobrar', async () => {
    const user = userEvent.setup()
    montar()
    await screen.findByText('Cobro del turno')

    await user.click(screen.getByRole('button', { name: /^Cobrar$/ }))

    expect(await screen.findByText(/Cobrado/)).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /^Cobrar$/ })).toBeNull()
    })
  })

  it('🔴 sin caja abierta, el 409 del backend se muestra', async () => {
    // El mostrador tiene que leer por qué no se cobró. Un cobro sin turno queda
    // fuera de todo arqueo, así que el backend lo rechaza — y la pantalla no
    // puede tragarse el motivo.
    const user = userEvent.setup()
    montar()
    await screen.findByText('Cobro del turno')

    vi.stubGlobal('fetch', vi.fn((ruta: string, init?: RequestInit) => {
      if (String(ruta).includes('/cobros') && init?.method === 'POST') {
        return Promise.resolve(json(
          { detail: 'No hay una caja abierta. Abrí el turno antes de cobrar.' }, 409,
        ))
      }
      return Promise.resolve(json(estado.cobros))
    }))

    await user.click(screen.getByRole('button', { name: /^Cobrar$/ }))
    expect(await screen.findByText(/No hay una caja abierta/)).toBeInTheDocument()
  })
})
