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
import { render, screen, waitFor } from '@testing-library/react'
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
