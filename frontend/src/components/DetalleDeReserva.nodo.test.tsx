/**
 * El detalle de una reserva en un nodo sin conexión (libra-ui ADR-094, libraclub ADR-022 y ADR-023).
 *
 * Dos cosas que el backend ya hace y la pantalla no mostraba:
 *
 * 1. `POST /api/reservas/{id}/facturar` contesta **202** `{ en_cola: true, … }` y no la factura. Sin cablear, la pantalla lo tomaba por
 *    una factura emitida y dibujaba «Factura undefined 0000-NaN».
 * 2. Las reservas dadas en el club sin conexión (id negativo) y las que chocaron (`en_conflicto`) llevan una etiqueta.
 *
 * 🔴 **`provisoria` NO es lo del nodo.** En LibraClub es el turno retenido esperando el pago del portal. La etiqueta del id negativo dice
 * «Sin subir al central», y una `provisoria` común no la lleva.
 *
 * Se stubea `fetch` y no `libra-ui/api-client`: el cliente HTTP de este producto es propio (`lib/api.ts`). Mismo motivo que en
 * `CobroDelTurno.test.tsx`.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DetalleDeReserva } from './DetalleDeReserva'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'admin', name: 'Admin', role: 'admin' }, loading: false }),
}))

const llamadas: { metodo: string; ruta: string }[] = []

/** Lo que contesta `POST /api/reservas/:id/facturar`; cada test pone la suya. */
let alFacturar: () => Response

function json(cuerpo: unknown, status = 200) {
  return new Response(JSON.stringify(cuerpo), { status, headers: { 'content-type': 'application/json' } })
}

beforeEach(() => {
  llamadas.length = 0
  alFacturar = () => json(null)
  vi.stubGlobal('fetch', vi.fn((ruta: string, init?: RequestInit) => {
    const u = String(ruta)
    const metodo = init?.method ?? 'GET'
    llamadas.push({ metodo, ruta: u })
    if (u.endsWith('/facturar') && metodo === 'POST') return Promise.resolve(alFacturar())
    if (u.includes('/consumos')) return Promise.resolve(json({ total: 0, lineas: [] }))
    if (u.includes('/mp/estado')) return Promise.resolve(json({ disponible: false, auto_facturar: false }))
    if (u.includes('/caja/medios-pago')) return Promise.resolve(json([]))
    // `GET .../factura` (todavía sin facturar), `.../cobros` y lo demás.
    return Promise.resolve(json(null))
  }))
})

const CANCHA = {
  id: 1, sucursal_id: 1, nombre: 'Cancha 1', deporte: 'padel',
  duracion_turno_min: 90, techada: true, iluminacion: true, superficie: null,
  orden: 1, activa: true, observaciones: null,
}

function turno(reservaId: number, estado: string) {
  return {
    comienza_at: '2026-08-20T18:00:00-03:00',
    termina_at: '2026-08-20T19:30:00-03:00',
    libre: false,
    precio: '14000.00',
    reserva_id: reservaId,
    estado,
    cliente: 'Ana Gomez',
    motivo: null, cobrado: false,
  }
}

function montar(reservaId = 5, estado = 'confirmada') {
  return render(
    <DetalleDeReserva
      abierto cancha={CANCHA} turno={turno(reservaId, estado)}
      onCerrar={vi.fn()} onCambiada={vi.fn()}
    />,
  )
}

async function facturar() {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Facturar esta reserva' }))
}

describe('facturar en un nodo sin conexión: el 202 `en_cola`', () => {
  it('🔴 muestra «Se emite al volver la conexión» y NO una factura', async () => {
    alFacturar = () => json({
      en_cola: true, estado: 'esperando', pedido_id: 7,
      mensaje: 'Sin conexión: la factura queda en la cola y se emite sola cuando vuelva la conexión.',
    }, 202)
    montar()
    await facturar()

    expect(await screen.findByText('Se emite al volver la conexión.')).toBeInTheDocument()
    // Sin cablear, el 202 se tomaba por una factura: «Factura undefined 0000-NaN».
    expect(screen.queryByText(/Factura\s+undefined/)).toBeNull()
    expect(screen.queryByText(/NaN/)).toBeNull()
    // Y el botón no vuelve a ofrecer lo que ya está pedido.
    expect(screen.queryByRole('button', { name: 'Facturar esta reserva' })).toBeNull()
  })

  it('el aviso se cierra y el botón vuelve', async () => {
    alFacturar = () => json({ en_cola: true, estado: 'esperando', pedido_id: 7, mensaje: 'En cola.' }, 202)
    const user = userEvent.setup()
    montar()
    await facturar()
    await user.click(await screen.findByRole('button', { name: 'Cerrar aviso' }))
    expect(screen.queryByText('Se emite al volver la conexión.')).toBeNull()
    expect(screen.getByRole('button', { name: 'Facturar esta reserva' })).toBeInTheDocument()
  })

  it('control: con conexión (201) muestra la factura, sin ningún aviso de cola', async () => {
    alFacturar = () => json({
      id: 9, tipo: 6, punto_venta: 4, numero: 31, fecha: '2026-08-20', total: 14000, cae: '70123456789012', cae_vto: '2026-08-30',
    }, 201)
    montar()
    await facturar()

    expect(await screen.findByText('Factura B 0004-00000031')).toBeInTheDocument()
    expect(screen.queryByText('Se emite al volver la conexión.')).toBeNull()
  })

  it('el 409 `solo_en_el_central` muestra su mensaje, no «Error 409»', async () => {
    alFacturar = () => json({ detail: { codigo: 'solo_en_el_central', mensaje: 'Esto se hace desde el central.' } }, 409)
    montar()
    await facturar()
    expect(await screen.findByText('Esto se hace desde el central.')).toBeInTheDocument()
    expect(screen.queryByText('Error 409')).toBeNull()
    expect(screen.queryByText('Se emite al volver la conexión.')).toBeNull()
  })
})

describe('las etiquetas del nodo en el detalle', () => {
  it('🔴 un id negativo lleva «Sin subir al central»', async () => {
    montar(-48213, 'confirmada')
    expect(await screen.findByText('Sin subir al central')).toBeInTheDocument()
    // Y sigue diciendo su estado de siempre.
    expect(screen.getByText(/Confirmada/)).toBeInTheDocument()
    // Esperar al pedido de la factura para no asertar la ausencia antes de que llegue nada.
    await waitFor(() => expect(llamadas.some((l) => l.ruta.endsWith('/factura'))).toBe(true))
  })

  it('🔴 `en_conflicto` lleva «En conflicto», una sola vez (el estado no se repite en texto)', async () => {
    montar(12, 'en_conflicto')
    const etiqueta = await screen.findByText('En conflicto')
    expect(etiqueta.closest('[data-slot="etiqueta-reserva-en-conflicto"]')).not.toBeNull()
    expect(screen.getAllByText('En conflicto')).toHaveLength(1)
    expect(screen.queryByText('Sin subir al central')).toBeNull()
  })

  it('una reserva dada en el nodo que además quedó en conflicto lleva las dos', async () => {
    montar(-3, 'en_conflicto')
    expect(await screen.findByText('Sin subir al central')).toBeInTheDocument()
    expect(screen.getByText('En conflicto')).toBeInTheDocument()
  })

  it('🔴 una reserva normal no lleva ninguna', async () => {
    montar(5, 'confirmada')
    expect(await screen.findByText(/Cancha 1/)).toBeInTheDocument()
    await waitFor(() => expect(llamadas.some((l) => l.ruta.endsWith('/factura'))).toBe(true))
    expect(screen.queryByText('Sin subir al central')).toBeNull()
    expect(screen.queryByText('En conflicto')).toBeNull()
  })

  it('🔴 una `provisoria` del portal (el turno retenido esperando el pago) NO es «Sin subir al central»', async () => {
    montar(5, 'provisoria')
    // Sigue llamándose «Provisoria»: es su estado de siempre.
    expect(await screen.findByText(/Provisoria/)).toBeInTheDocument()
    await waitFor(() => expect(llamadas.some((l) => l.ruta.endsWith('/factura'))).toBe(true))
    expect(screen.queryByText('Sin subir al central')).toBeNull()
    expect(screen.queryByText('En conflicto')).toBeNull()
  })
})
