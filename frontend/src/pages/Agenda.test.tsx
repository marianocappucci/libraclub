/**
 * La agenda muestra **una cancha por vez**, elegida con pestañas.
 *
 * Antes se apilaban todas: con cuatro canchas la pantalla eran cuatro grillas de
 * siete días y para ver la última había que scrollear más allá de las otras
 * tres. Lo pidió el humano el 2026-08-28.
 *
 * 🔑 Lo que se prueba acá es **que sólo se dibuje una**, y que la elección
 * cambie cuál. Los turnos, los precios y el alta tienen sus tests en otro lado;
 * esto es la costura nueva.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Agenda } from './Agenda'
import IconoGenerico from '~icons/mdi/dumbbell'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', name: 'Ana', role: 'staff' }, loading: false }),
}))

vi.mock('@/context/SucursalContext', () => ({
  useSucursal: () => ({ actual: 1, sucursales: [], elegir: vi.fn(), cargando: false }),
}))

const CANCHAS = [
  {
    id: 1, sucursal_id: 1, nombre: 'Cancha 1', deporte: 'padel',
    duracion_turno_min: 90, techada: true, iluminacion: true, superficie: null,
    orden: 1, activa: true, observaciones: null,
  },
  {
    id: 2, sucursal_id: 1, nombre: 'Cancha 2', deporte: 'futbol',
    duracion_turno_min: 60, techada: false, iluminacion: true, superficie: null,
    orden: 2, activa: true, observaciones: null,
  },
]

/** Un turno libre por cancha, con precios distintos: es lo que distingue una
 *  grilla de la otra sin depender del encabezado. */
const SEMANA = {
  desde: '2026-08-31',
  canchas: {
    '1': { '2026-08-31': [{ comienza_at: '2026-08-31T20:00:00-03:00', termina_at: '2026-08-31T21:30:00-03:00', libre: true, precio: '11111.00', reserva_id: null, estado: null, cliente: null, motivo: null }] },
    '2': { '2026-08-31': [{ comienza_at: '2026-08-31T20:00:00-03:00', termina_at: '2026-08-31T21:00:00-03:00', libre: true, precio: '22222.00', reserva_id: null, estado: null, cliente: null, motivo: null }] },
  },
}

function json(cuerpo: unknown) {
  return new Response(JSON.stringify(cuerpo), {
    status: 200, headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const u = String(url)
    if (u.includes('/api/canchas')) return Promise.resolve(json(CANCHAS))
    if (u.includes('/api/disponibilidad/semana')) return Promise.resolve(json(SEMANA))
    return Promise.resolve(json(null))
  }))
})

describe('la agenda, una cancha por vez', () => {
  it('🔴 arranca en la primera y NO dibuja la grilla de la otra', async () => {
    render(<Agenda />)

    // El precio es lo que identifica cada grilla: el encabezado y la pestaña
    // dicen el mismo nombre, así que buscar por nombre no distingue una de otra.
    expect(await screen.findByText(/11\.111/)).toBeInTheDocument()
    expect(screen.queryByText(/22\.222/)).toBeNull()
  })

  it('🔴 al elegir la otra pestaña aparece la suya, y se va la primera', async () => {
    const user = userEvent.setup()
    render(<Agenda />)
    await screen.findByText(/11\.111/)

    await user.click(screen.getByRole('tab', { name: 'Cancha 2' }))

    expect(await screen.findByText(/22\.222/)).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText(/11\.111/)).toBeNull())
  })

  it('están las dos pestañas, una por cancha', async () => {
    render(<Agenda />)
    await screen.findByText(/11\.111/)
    expect(screen.getAllByRole('tab')).toHaveLength(2)
  })

  it('🔴 cada pestaña lleva el icono de SU deporte, y no el mismo para todas', async () => {
    // Lo pidió el humano el 2026-08-28: saber de qué es cada cancha sin leer.
    //
    // 🔑 Se compara el dibujo de los dos, no que "haya un svg": un mapa que
    // devolviera siempre el icono genérico pasaría esa versión floja del test, y
    // sería exactamente el defecto —seis pestañas con la misma pesa al lado—.
    render(<Agenda />)
    await screen.findByText(/11\.111/)

    const [padel, futbol] = screen.getAllByRole('tab')
    const dibujoDe = (t: HTMLElement) => t.querySelector('svg')?.innerHTML ?? ''

    expect(dibujoDe(padel)).not.toBe('')
    expect(dibujoDe(futbol)).not.toBe('')
    expect(dibujoDe(padel)).not.toBe(dibujoDe(futbol))

    // 🔴 **Y que no sea el genérico**, que es lo que "distintos entre sí" no
    // alcanza a decir: con pádel mapeado a la pesa y fútbol a la pelota, los dos
    // siguen siendo distintos y el de pádel está mal igual. Lo delató la
    // mutación; la primera versión de este test se quedaba en la línea de
    // arriba.
    const generico = render(<IconoGenerico />).container.querySelector('svg')?.innerHTML
    expect(generico).toBeTruthy()
    expect(dibujoDe(padel)).not.toBe(generico)
    expect(dibujoDe(futbol)).not.toBe(generico)
  })

  it('🔑 un deporte que el mapa no conoce igual muestra un icono', async () => {
    // El guard cruzado del backend impide que el enum crezca sin etiqueta ni
    // icono, pero el fallback es el cinturón: una pestaña sin icono al lado de
    // seis que lo tienen se lee como un error de carga, no como "no sé cuál es".
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      const u = String(url)
      if (u.includes('/api/canchas')) {
        return Promise.resolve(json([CANCHAS[0], { ...CANCHAS[1], deporte: 'curling' }]))
      }
      if (u.includes('/api/disponibilidad/semana')) return Promise.resolve(json(SEMANA))
      return Promise.resolve(json(null))
    }))
    render(<Agenda />)
    await screen.findByText(/11\.111/)

    const desconocida = screen.getAllByRole('tab')[1]
    expect(desconocida.querySelector('svg')).not.toBeNull()
  })

  it('🔑 con una sola cancha no se dibuja la tira de pestañas', async () => {
    // Una pestaña sola no ofrece elegir nada: es ruido arriba de la grilla.
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      const u = String(url)
      if (u.includes('/api/canchas')) return Promise.resolve(json([CANCHAS[0]]))
      if (u.includes('/api/disponibilidad/semana')) return Promise.resolve(json(SEMANA))
      return Promise.resolve(json(null))
    }))
    render(<Agenda />)

    expect(await screen.findByText(/11\.111/)).toBeInTheDocument()
    expect(screen.queryAllByRole('tab')).toEqual([])
  })
})


describe('el turno ya cobrado', () => {
  /* Pedido del humano el 2026-08-28: "diferenciar con un color diferente o con
   * un punto el turno de la cancha que ya se cerró y se cobró — ponerlo de otro
   * color, ponerle 'cobrado' y un fondo traslúcido". El operador quiere ver de
   * un vistazo qué le queda por cobrar sin abrir turno por turno.
   *
   * Quién está cobrado lo decide el backend contra la caja (`reservas_saldadas`,
   * con sus tests en `tests/test_cobro_del_turno.py`). Acá se prueba lo que la
   * grilla hace con ese dato. */

  /** Dos turnos ocupados en la misma cancha: uno cobrado y otro no. Van juntos
   *  a propósito — un test con un solo casillero pasaría igual si la marca se
   *  pusiera en TODOS. */
  const OCUPADOS = {
    desde: '2026-08-31',
    canchas: {
      '1': {
        '2026-08-31': [
          {
            comienza_at: '2026-08-31T20:00:00-03:00',
            termina_at: '2026-08-31T21:30:00-03:00',
            libre: false, precio: null, reserva_id: 7, estado: 'jugada',
            cliente: 'Ana Gómez', motivo: null, cobrado: true,
          },
          {
            comienza_at: '2026-08-31T21:30:00-03:00',
            termina_at: '2026-08-31T23:00:00-03:00',
            libre: false, precio: null, reserva_id: 8, estado: 'confirmada',
            cliente: 'Beto Ruiz', motivo: null, cobrado: false,
          },
        ],
      },
      '2': { '2026-08-31': [] },
    },
  }

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      const u = String(url)
      if (u.includes('/api/canchas')) return Promise.resolve(json(CANCHAS))
      if (u.includes('/api/disponibilidad/semana')) return Promise.resolve(json(OCUPADOS))
      return Promise.resolve(json(null))
    }))
  })

  it('lo dice con la palabra, y sólo sobre el que está cobrado', async () => {
    render(<Agenda />)

    // Control positivo del selector: los dos turnos SÍ están en pantalla. Sin
    // esto, un "encontré una sola marca" porque la grilla no renderizó pasaría.
    expect(await screen.findByText('Ana Gómez')).toBeInTheDocument()
    expect(screen.getByText('Beto Ruiz')).toBeInTheDocument()

    expect(screen.getAllByText('cobrado')).toHaveLength(1)
    // Y es el de Ana: el botón que la contiene es el mismo que dice «cobrado».
    const deAna = screen.getByRole('button', { name: /Ana Gómez|20:00/ })
      ?? screen.getByText('Ana Gómez').closest('button')!
    expect(deAna).toHaveTextContent('cobrado')
  })

  it('🔑 y también en el nombre accesible, que es lo que lee un lector', async () => {
    // El color y el punto no los lee un lector de pantalla. Es la misma
    // decisión que los movimientos anulados: las dos cosas, no una.
    render(<Agenda />)

    expect(await screen.findByRole('button', { name: /Ver la reserva de 20:00, cobrado/ }))
      .toBeInTheDocument()
    // El control: el que no está cobrado NO lo dice.
    const otro = screen.getByRole('button', { name: /Ver la reserva de 21:30/ })
    expect(otro.getAttribute('aria-label')).not.toMatch(/cobrado/)
  })

  it('🔴 el color del cobrado PISA al del estado, no se suma', async () => {
    /* El `className` del casillero es un template string sin `cn()`: dos `bg-*`
     * en la misma lista no los resuelve el orden en que se escribieron sino el
     * orden en que Tailwind los emitió en la hoja. Con dos clases presentes el
     * resultado depende de la hoja generada, que este test no puede ver.
     *
     * Por eso se asierta la ausencia de la del estado. `jugada` es
     * `bg-slate-200`: si apareciera junto a `bg-emerald-500/25`, cuál gana sería
     * una lotería distinta en cada build. */
    render(<Agenda />)

    const deAna = (await screen.findByText('Ana Gómez')).closest('button')!
    expect(deAna.className).toContain('bg-exito/10')
    expect(deAna.className).not.toContain('bg-slate-200')

    // El control: el que NO está cobrado (y viene de un backend que todavía no
    // manda `cobro`) sí lleva el color de su estado, o sea que la clase existe y
    // el assert de arriba mide una ausencia real.
    const deBeto = screen.getByText('Beto Ruiz').closest('button')!
    expect(deBeto.className).toContain('bg-emerald-100')
    expect(deBeto.className).not.toContain('bg-exito/10')
  })
})

describe('pagado, señado y sin cobrar', () => {
  /* Pedido del humano (lista «Caja», 2026-10): distinguir de un vistazo lo pagado, lo
   * señado y lo pendiente. El backend manda `cobro` y `saldo` en cada casillero
   * (`servicios/disponibilidad.py`); acá se prueba lo que la grilla hace con eso. */

  const turnoOcupado = (reservaId: number, hora: string, cliente: string, extra: Record<string, unknown>) => ({
    comienza_at: `2026-08-31T${hora}:00-03:00`,
    termina_at: `2026-08-31T${hora}:00-03:00`,
    libre: false, precio: null, reserva_id: reservaId, estado: 'confirmada',
    cliente, motivo: null, cobrado: false, ...extra,
  })

  const SEMANA_CON_TRES = {
    desde: '2026-08-31',
    canchas: {
      '1': {
        '2026-08-31': [
          turnoOcupado(1, '09:00', 'Pago Completo', { cobrado: true, cobro: 'cobrado', saldo: '0.00' }),
          turnoOcupado(2, '10:30', 'Con Sena', { cobro: 'senado', saldo: '6000.00' }),
          turnoOcupado(3, '12:00', 'Sin Nada', { cobro: 'pendiente', saldo: '10000.00' }),
          turnoOcupado(4, '13:30', 'Jugo Y Debe', { estado: 'jugada', cobro: 'pendiente', saldo: '8000.00' }),
          {
            comienza_at: '2026-08-31T15:00:00-03:00', termina_at: '2026-08-31T16:30:00-03:00',
            libre: false, precio: null, reserva_id: 5, estado: 'bloqueo',
            cliente: null, motivo: 'Mantenimiento', cobrado: false, cobro: null, saldo: null,
          },
        ],
      },
      '2': { '2026-08-31': [] },
    },
  }

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      const u = String(url)
      if (u.includes('/api/canchas')) return Promise.resolve(json(CANCHAS))
      if (u.includes('/api/disponibilidad/semana')) return Promise.resolve(json(SEMANA_CON_TRES))
      return Promise.resolve(json(null))
    }))
  })

  const casillero = async (cliente: string) =>
    (await screen.findByText(cliente)).closest('button')!

  it('cada punto de pago tiene su color, y los tres son distintos', async () => {
    render(<Agenda />)

    const cobrado = await casillero('Pago Completo')
    const senado = await casillero('Con Sena')
    const pendiente = await casillero('Sin Nada')

    expect(cobrado.className).toContain('bg-exito/10')
    expect(senado.className).toContain('bg-blue-700/10')
    expect(pendiente.className).toContain('bg-amber-800/10')
    // Ninguno lleva también el color del estado `confirmada`: pisa, no se suma.
    for (const c of [cobrado, senado, pendiente]) expect(c.className).not.toContain('bg-emerald-100')
  })

  it('🔑 lo dice con la palabra y con lo que falta, no sólo con el color', async () => {
    render(<Agenda />)

    expect(await casillero('Pago Completo')).toHaveTextContent('cobrado')
    const senado = await casillero('Con Sena')
    expect(senado).toHaveTextContent('señado')
    expect(senado).toHaveTextContent(/falta \$\s?6\.000/)
    const pendiente = await casillero('Sin Nada')
    expect(pendiente).toHaveTextContent('sin cobrar')
    // Sin nada cobrado no «falta»: se debe todo, y se dice el total.
    expect(pendiente).toHaveTextContent(/\$\s?10\.000/)
    expect(pendiente).not.toHaveTextContent('falta')
    // Y en el nombre accesible, que es lo que lee un lector de pantalla.
    expect(screen.getByRole('button', { name: /Ver la reserva de 10:30, señado · falta/ })).toBeInTheDocument()
  })

  it('una jugada que no se cobró lleva las dos cosas: que se jugó y que falta la plata', async () => {
    render(<Agenda />)

    const jugada = await casillero('Jugo Y Debe')
    expect(jugada.className).toContain('bg-amber-800/10')
    expect(jugada).toHaveTextContent('sin cobrar')
    expect(jugada).toHaveTextContent('jugada')
    // Una confirmada normal no repite el estado.
    expect(await casillero('Sin Nada')).not.toHaveTextContent('confirmada')
  })

  it('un bloqueo no tiene punto de pago: conserva el color de su estado', async () => {
    render(<Agenda />)

    const bloqueo = await casillero('Mantenimiento')
    expect(bloqueo.className).toContain('bg-slate-300')
    expect(bloqueo.className).not.toMatch(/bg-(exito|blue-700|amber-800)\/10/)
    expect(bloqueo).not.toHaveTextContent(/cobrado|señado|sin cobrar/)
  })

  it('trae una leyenda con los tres puntos de pago', async () => {
    render(<Agenda />)
    await casillero('Pago Completo')

    const leyenda = screen.getByRole('list', { name: 'Leyenda de la agenda' })
    expect(within(leyenda).getByText('Cobrado')).toBeInTheDocument()
    expect(within(leyenda).getByText('Señado, falta el resto')).toBeInTheDocument()
    expect(within(leyenda).getByText('Sin cobrar')).toBeInTheDocument()
    expect(within(leyenda).getByText('Libre')).toBeInTheDocument()
  })
})
