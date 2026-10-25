import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { elegirEnBuscable } from '@/test/select-buscable'

/**
 * El panel del dueño (F5, ADR-027).
 *
 * 🔑 **Los números vienen del backend y acá sólo se dibujan.** Lo que se prueba es el cableado: que cada sucursal tenga
 * su fila (el gate de la fase: cinco sucursales, cinco filas), que el filtro viaje al pedido, que lo cerrado no se
 * dibuje como cero y que los estados vacíos digan qué pasa.
 */

const obtener = vi.fn()
const listarCanchas = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    panelDelDueno: { obtener },
    canchas: { ...(real.canchas as object), listar: listarCanchas },
  }
})

const SUCURSALES = [
  { id: 1, nombre: 'Centro', activa: true },
  { id: 2, nombre: 'Norte', activa: true },
]

vi.mock('@/context/SucursalContext', () => ({
  useSucursal: () => ({ actual: 1, sucursales: SUCURSALES, elegir: vi.fn(), cargando: false }),
}))

const { PanelDelDueno } = await import('./PanelDelDueno')

const ORIGEN_VACIO = { mostrador: 0, telefono: 0, whatsapp: 0, portal: 0, serie: 0 }

function sucursal(id: number, nombre: string, extra: Record<string, unknown> = {}) {
  return {
    sucursal_id: id, sucursal: nombre, ocupacion_pct: 50, franjas: [{ dia: 0, hora: 18, ocupacion_pct: 50 }],
    horas_abiertas: 40, horas_reservadas: 20,
    ingresos: { reservas: 80000, senas: 10000, buffet: 10000, total: 100000, total_periodo_anterior: 80000 },
    canceladas: 3, ausentes: 2, reservas: 20,
    origen: { ...ORIGEN_VACIO, mostrador: 12, portal: 8 },
    ...extra,
  }
}

function panel(extra: Record<string, unknown> = {}) {
  return {
    desde: '2026-09-01', hasta: '2026-09-30',
    por_sucursal: [sucursal(1, 'Centro'), sucursal(2, 'Norte', {
      ocupacion_pct: 25, ausentes: 4, canceladas: 1, reservas: 10,
      ingresos: { reservas: 40000, senas: 0, buffet: 10000, total: 50000, total_periodo_anterior: 60000 },
    })],
    top_ausentes: [
      { cliente_id: 7, nombre: 'Marta Gómez', ausentes: 3 },
      { cliente_id: 9, nombre: 'Pablo Ruiz', ausentes: 1 },
    ],
    total: { ocupacion_pct: 41.7, franjas: [{ dia: 0, hora: 18, ocupacion_pct: 41.7 }, { dia: 4, hora: 21, ocupacion_pct: 80 }] },
    ...extra,
  }
}

function montar() {
  return render(<MemoryRouter><PanelDelDueno /></MemoryRouter>)
}

/** La sección con ese título, para no leer las cifras de otra. */
function seccion(titulo: string) {
  const h = screen.getByRole('heading', { name: titulo })
  return within(h.closest('section') as HTMLElement)
}

beforeEach(() => {
  obtener.mockReset()
  listarCanchas.mockReset()
  obtener.mockResolvedValue(panel())
  listarCanchas.mockResolvedValue([
    { id: 11, sucursal_id: 1, nombre: 'Cancha 1', activa: true },
    { id: 21, sucursal_id: 2, nombre: 'Cancha 1', activa: true },
  ])
})

describe('lo que muestra', () => {
  it('pide los últimos 30 días y dibuja una fila por sucursal en cada sección', async () => {
    montar()
    await screen.findByText(/Del 01-09-2026 al 30-09-2026/)

    const [pedido] = obtener.mock.calls[0]
    expect(pedido.hasta >= pedido.desde).toBe(true)
    expect(pedido.sucursalId).toBeUndefined()
    for (const titulo of ['Ingresos', 'Cancelaciones y ausentes', 'Origen de las reservas', 'Ocupación por franja']) {
      const filas = seccion(titulo).getAllByRole('row').map((r) => r.textContent ?? '')
      expect(filas.some((f) => f.startsWith('Centro')), titulo).toBe(true)
      expect(filas.some((f) => f.startsWith('Norte')), titulo).toBe(true)
    }
  })

  it('los indicadores son la suma de las sucursales y la ocupación la del backend', async () => {
    montar()
    await screen.findByText(/Del 01-09-2026/)

    const tarjetas = Object.fromEntries(
      Array.from(document.querySelectorAll('[data-slot="tarjeta-indicador"]')).map((t) => [
        t.getAttribute('data-concepto'), t.textContent ?? '',
      ]),
    )
    expect(tarjetas.reportes).toContain('41,7 %')
    expect(tarjetas.cobros).toMatch(/150\.000/)
    expect(tarjetas.agenda).toContain('30')
    expect(tarjetas.mermas).toContain('10')
    expect(tarjetas.mermas).toContain('4 canceladas · 6 ausentes')
  })

  it('los ingresos se abren por sucursal y se comparan con el período anterior', async () => {
    montar()
    await screen.findByText(/Del 01-09-2026/)

    const filas = seccion('Ingresos').getAllByRole('row')
    const centro = filas.find((r) => r.textContent?.startsWith('Centro'))!
    const norte = filas.find((r) => r.textContent?.startsWith('Norte'))!
    expect(centro).toHaveTextContent('+25 %')
    expect(norte).toHaveTextContent('-16,7 %')
    expect(within(centro).getByText('+25 %')).toHaveClass('text-exito')
    expect(within(norte).getByText('-16,7 %')).toHaveClass('text-destructive')
  })

  it('🔴 sin período anterior no inventa una variación', async () => {
    obtener.mockResolvedValue(panel({
      por_sucursal: [sucursal(1, 'Centro', {
        ingresos: { reservas: 5, senas: 0, buffet: 0, total: 5, total_periodo_anterior: 0 },
      })],
    }))
    montar()
    await screen.findByText(/Del 01-09-2026/)

    expect(seccion('Ingresos').getAllByText('Sin período anterior').length).toBeGreaterThan(0)
  })

  it('el origen trae todas las claves del enum, con su porcentaje sobre las reservas de la sucursal', async () => {
    montar()
    await screen.findByText(/Del 01-09-2026/)

    const origen = seccion('Origen de las reservas')
    expect(origen.getAllByRole('columnheader').map((c) => c.textContent)).toEqual(
      ['Sucursal', 'Mostrador', 'Teléfono', 'WhatsApp', 'Portal', 'Turno fijo'],
    )
    expect(origen.getAllByRole('row').find((r) => r.textContent?.startsWith('Centro'))).toHaveTextContent('12(60 %)')
  })

  it('el top de ausentes muestra a los clientes que más faltaron', async () => {
    montar()
    await screen.findByText(/Del 01-09-2026/)

    const top = seccion('Cancelaciones y ausentes').getAllByRole('listitem').map((l) => l.textContent)
    expect(top).toEqual(['Marta Gómez3 ausentes', 'Pablo Ruiz1 ausente'])
  })

  it('el mapa de calor es el de las sucursales que se miran', async () => {
    montar()
    await screen.findByText(/Del 01-09-2026/)

    expect(screen.getByLabelText('Lunes 18:00 – 19:00: 41,7 % de ocupación')).toBeInTheDocument()
    expect(screen.getByLabelText('Viernes 21:00 – 22:00: 80 % de ocupación')).toBeInTheDocument()
  })
})

describe('los filtros', () => {
  it('elegir una sucursal vuelve a pedir el panel de esa sucursal', async () => {
    const user = userEvent.setup()
    montar()
    await screen.findByText(/Del 01-09-2026/)

    await elegirEnBuscable(user, screen.getByRole('combobox', { name: /Sucursal/ }), 'Norte')

    await waitFor(() => expect(obtener).toHaveBeenLastCalledWith(expect.objectContaining({ sucursalId: 2 })))
  })

  it('la cancha se ofrece de la sucursal elegida y viaja al pedido', async () => {
    const user = userEvent.setup()
    montar()
    await screen.findByText(/Del 01-09-2026/)

    await elegirEnBuscable(user, screen.getByRole('combobox', { name: /Sucursal/ }), 'Norte')
    await elegirEnBuscable(user, screen.getByRole('combobox', { name: /Cancha/ }), 'Cancha 1')

    await waitFor(() => expect(obtener).toHaveBeenLastCalledWith(
      expect.objectContaining({ sucursalId: 2, canchaId: 21 }),
    ))
  })

  it('un atajo de período cambia el rango que se pide', async () => {
    const user = userEvent.setup()
    montar()
    await screen.findByText(/Del 01-09-2026/)
    const antes = obtener.mock.calls.length

    await user.click(screen.getByRole('button', { name: '7 días' }))

    await waitFor(() => expect(obtener.mock.calls.length).toBeGreaterThan(antes))
    const { desde, hasta } = obtener.mock.calls.at(-1)![0]
    expect((new Date(hasta).getTime() - new Date(desde).getTime()) / 86400000).toBe(6)
  })

  it('un rango al revés no se pide y se avisa', async () => {
    const user = userEvent.setup()
    montar()
    await screen.findByText(/Del 01-09-2026/)
    const antes = obtener.mock.calls.length

    const desde = screen.getByLabelText('Desde')
    await user.clear(desde)
    await user.type(desde, '2099-12-31')

    expect(await screen.findByRole('alert')).toHaveTextContent(/no puede ser posterior/)
    expect(obtener.mock.calls.length).toBe(antes)
  })
})

describe('los estados vacíos y el error', () => {
  it('un período sin reservas lo dice, y el origen y el top no inventan datos', async () => {
    obtener.mockResolvedValue(panel({
      por_sucursal: [sucursal(1, 'Centro', {
        reservas: 0, canceladas: 0, ausentes: 0, franjas: [], ocupacion_pct: null,
        ingresos: { reservas: 0, senas: 0, buffet: 0, total: 0, total_periodo_anterior: 0 },
        origen: ORIGEN_VACIO,
      })],
      top_ausentes: [],
      total: { ocupacion_pct: null, franjas: [] },
    }))
    montar()
    await screen.findByText(/No hubo reservas en este período/)

    expect(screen.getByText('Nadie faltó en este período.')).toBeInTheDocument()
    expect(screen.getByText('Sin reservas en este período.')).toBeInTheDocument()
    expect(screen.getByText(/No hay horas abiertas en este período/)).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'Ocupación por día y hora' })).toBeNull()
  })

  it('🔴 la ocupación sin horas abiertas es «—» y no 0 %', async () => {
    obtener.mockResolvedValue(panel({ total: { ocupacion_pct: null, franjas: [] } }))
    montar()
    await screen.findByText(/Del 01-09-2026/)

    const ocupacion = document.querySelector('[data-concepto="reportes"]')!
    expect(ocupacion).toHaveTextContent('—')
    expect(ocupacion).not.toHaveTextContent('0 %')
  })

  it('una instancia sin caja no informa ingresos en cero: lo dice', async () => {
    obtener.mockResolvedValue(panel({
      por_sucursal: [sucursal(1, 'Centro', { ingresos: null })],
    }))
    montar()
    await screen.findByText(/Del 01-09-2026/)

    expect(screen.getByText(/no tiene la caja configurada/)).toBeInTheDocument()
    expect(document.querySelector('[data-concepto="cobros"]')).toHaveTextContent('Sin caja configurada')
  })

  it('el error del servidor se muestra y no deja la pantalla en blanco', async () => {
    obtener.mockRejectedValue(new Error('Error 403'))
    montar()

    expect(await screen.findByRole('alert')).toHaveTextContent('Error 403')
  })

  it('una respuesta lenta de un filtro anterior no pisa a la última', async () => {
    const user = userEvent.setup()
    let resolverLenta!: (v: unknown) => void
    obtener.mockReset()
    // El primer pedido (sin filtro) queda colgado; el segundo (Norte) vuelve enseguida.
    obtener.mockImplementationOnce(() => new Promise((r) => { resolverLenta = r }))
    obtener.mockResolvedValue(panel({
      por_sucursal: [sucursal(2, 'Norte')], total: { ocupacion_pct: 25, franjas: [] },
    }))
    montar()
    await elegirEnBuscable(user, await screen.findByRole('combobox', { name: /Sucursal/ }), 'Norte')
    await screen.findByText(/Del 01-09-2026/)

    await act(async () => { resolverLenta(panel()) })   // llega tarde la respuesta del pedido sin filtro

    const filas = seccion('Ingresos').getAllByRole('row').map((r) => r.textContent ?? '')
    expect(filas.some((f) => f.startsWith('Norte'))).toBe(true)
    expect(filas.some((f) => f.startsWith('Centro'))).toBe(false)
  })
})
