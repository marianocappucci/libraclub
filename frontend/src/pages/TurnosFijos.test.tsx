import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Lo que esta pantalla decide, y que un test puede hacer fallar:
 *
 * 1. el **aviso de que hay que extender** — es lo que evita que una cancha fija
 *    se apague sola al agotarse la ventana de 90 días;
 * 2. que una serie **sin ningún turno generado** se distinga de una por vencer:
 *    son dos problemas distintos y se arreglan distinto;
 * 3. que la confirmación de la baja **diga cuántos turnos se cancelan**;
 * 4. que las salteadas se muestren **agrupadas por motivo**, porque cada motivo
 *    se arregla en una pantalla distinta.
 */

const listar = vi.fn()
const extender = vi.fn()
const darDeBaja = vi.fn()
const canchasListar = vi.fn()
const clientesListar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    series: { ...(real.series as object), listar, extender, darDeBaja, crear: vi.fn() },
    canchas: { ...(real.canchas as object), listar: canchasListar },
    clientes: { ...(real.clientes as object), listar: clientesListar },
  }
})

vi.mock('@/context/SucursalContext', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    useSucursal: () => ({
      sucursales: [], actual: 1, elegir: () => {}, recargar: () => {}, cargando: false,
    }),
  }
})

const { TurnosFijos } = await import('./TurnosFijos')

function enDias(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

const BASE = {
  id: 1, cancha_id: 1, cliente_id: 1, dia_semana: 1, hora: '20:00:00',
  duracion_min: 90, desde: '2026-01-01', hasta: null, activa: true,
  cliente: 'Los Martes', cancha: 'Cancha 1',
  materializada_hasta: enDias(80), proximas: 11,
}

beforeEach(() => {
  listar.mockReset(); extender.mockReset(); darDeBaja.mockReset()
  canchasListar.mockReset(); clientesListar.mockReset()
  canchasListar.mockResolvedValue([{ id: 1, nombre: 'Cancha 1', sucursal_id: 1 }])
  clientesListar.mockResolvedValue([{ id: 1, nombre: 'Los Martes' }])
  listar.mockResolvedValue([BASE])
  vi.stubGlobal('confirm', vi.fn(() => true))
})

describe('pantalla de turnos fijos', () => {
  it('con la ventana lejos no avisa nada', async () => {
    render(<TurnosFijos />)
    await screen.findByText('Los Martes')
    // Control negativo: sin él, un aviso que se mostrara SIEMPRE pasaría el
    // test de abajo.
    expect(screen.queryByText(/Hay que extender/)).not.toBeInTheDocument()
  })

  it('avisa cuando la ventana está por agotarse', async () => {
    // 🔴 El aviso llega con tres semanas, no el día que se acaba: extender es
    // un click, pero hay que estar mirando la pantalla — si avisara al vencer,
    // el primer martes sin turno ya pasó.
    listar.mockResolvedValue([{ ...BASE, materializada_hasta: enDias(10) }])
    render(<TurnosFijos />)
    const aviso = await screen.findByText(/Hay que extender/)
    expect(aviso.parentElement).toHaveTextContent('Los Martes (Martes)')
  })

  it('una serie SIN turnos generados se distingue de una por vencer', async () => {
    // Son dos problemas distintos: "por vencer" se arregla extendiendo, "sin
    // ninguno" significa que todas las ocurrencias se saltearon y hay que
    // mirar la tarifa o el horario.
    listar.mockResolvedValue([{ ...BASE, materializada_hasta: null, proximas: 0 }])
    render(<TurnosFijos />)
    expect(await screen.findByText('Ningún turno generado')).toBeInTheDocument()
  })

  it('la confirmación de la baja dice cuántos turnos se cancelan', async () => {
    darDeBaja.mockResolvedValue({ serie_id: 1, canceladas: 11 })
    render(<TurnosFijos />)
    await userEvent.click(
      await screen.findByRole('button', { name: /Dar de baja la cancha fija de Los Martes/ }),
    )
    // 🔴 «¿Dar de baja?» a secas esconde que se cancelan once turnos ya
    // vendidos, que es lo que el operador necesita saber ANTES de apretar.
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('11 turnos futuros'))
    await waitFor(() => expect(darDeBaja).toHaveBeenCalledWith(1, { cancelar_futuras: true }))
  })

  it('sin turnos futuros la confirmación lo dice, y no inventa un número', async () => {
    listar.mockResolvedValue([{ ...BASE, proximas: 0 }])
    darDeBaja.mockResolvedValue({ serie_id: 1, canceladas: 0 })
    render(<TurnosFijos />)
    await userEvent.click(
      await screen.findByRole('button', { name: /Dar de baja la cancha fija de Los Martes/ }),
    )
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('No tiene turnos futuros'))
  })

  it('extender muestra qué se generó y qué se salteó, agrupado por motivo', async () => {
    extender.mockResolvedValue({
      serie: BASE,
      creadas: [{ id: 1 }, { id: 2 }],
      salteadas: [
        { comienza_at: '2026-09-01T20:00:00-03:00', motivo: 'sin_tarifa', detalle: 'x' },
        { comienza_at: '2026-09-08T20:00:00-03:00', motivo: 'sin_tarifa', detalle: 'x' },
        { comienza_at: '2026-09-15T20:00:00-03:00', motivo: 'ocupada', detalle: 'y' },
      ],
    })
    render(<TurnosFijos />)
    await userEvent.click(await screen.findByRole('button', { name: 'Extender' }))
    await waitFor(() => expect(extender).toHaveBeenCalledWith(1))

    // El número va en un `<strong>`, así que el texto está partido: se busca la
    // parte que SÍ es un nodo propio y se asierta sobre el contenedor.
    // (`findByText('2')` no sirve: hay otro `<strong>` con un 2, el de los
    // salteados por tarifa.)
    const linea = await screen.findByText(/turnos generados/)
    expect(linea).toHaveTextContent('2 turnos generados')
    // Agrupadas: dos por tarifa y una por ocupada, cada una con qué hacer.
    expect(screen.getByText(/Sin tarifa cargada/)).toBeInTheDocument()
    expect(screen.getByText(/Cargá la tarifa de esa franja/)).toBeInTheDocument()
    expect(screen.getByText(/La cancha ya estaba ocupada/)).toBeInTheDocument()
    // Y las fechas concretas, no sólo el conteo.
    expect(screen.getByText(/01-09-2026/)).toBeInTheDocument()
  })

  it('una serie dada de baja no ofrece extender ni volver a darla de baja', async () => {
    listar.mockResolvedValue([{ ...BASE, activa: false, proximas: 0 }])
    render(<TurnosFijos />)
    await screen.findByText(/dada de baja/)
    expect(screen.queryByRole('button', { name: 'Extender' })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /Dar de baja la cancha fija/ }),
    ).not.toBeInTheDocument()
  })

  it('sigue en el listado aunque esté dada de baja', async () => {
    // No se borra: el historial de quién tenía la cancha fija de los martes es
    // lo que se consulta cuando el grupo vuelve a pedirla.
    listar.mockResolvedValue([{ ...BASE, activa: false, proximas: 0 }])
    render(<TurnosFijos />)
    expect(await screen.findByText('Los Martes')).toBeInTheDocument()
  })

  it('las canchas fijas de otra sucursal no se muestran', async () => {
    listar.mockResolvedValue([BASE, { ...BASE, id: 2, cancha_id: 99, cliente: 'De Norte' }])
    render(<TurnosFijos />)
    await screen.findByText('Los Martes')
    expect(screen.queryByText('De Norte')).not.toBeInTheDocument()
  })
})
