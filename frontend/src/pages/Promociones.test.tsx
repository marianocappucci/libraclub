import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listar = vi.fn()
const borrar = vi.fn()
const canchasListar = vi.fn()
let rol = 'admin'

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    promociones: { ...(real.promociones as object), listar, borrar, crear: vi.fn(), editar: vi.fn() },
    canchas: { ...(real.canchas as object), listar: canchasListar },
  }
})

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'u', name: 'U', role: rol }, loading: false }),
}))

vi.mock('@/context/SucursalContext', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    useSucursal: () => ({
      sucursales: [], actual: 1, elegir: () => {}, recargar: () => {}, cargando: false,
    }),
  }
})

const { Promociones, textoDeDias } = await import('./Promociones')

const VALLE = {
  id: 1, sucursal_id: 1, cancha_id: null, nombre: 'Hora valle', descuento_porcentaje: 20,
  dias_semana: [1, 2, 3], hora_desde: '14:00:00', hora_hasta: '17:00:00',
  vigente_desde: null, vigente_hasta: null, aplica_en_feriados: false, activa: true,
}
const NOVIEMBRE = {
  ...VALLE, id: 2, nombre: 'Noviembre', descuento_porcentaje: 10, dias_semana: null,
  hora_desde: '08:00:00', hora_hasta: '23:00:00', cancha_id: 4,
  vigente_desde: '2026-11-01', vigente_hasta: '2026-11-15', aplica_en_feriados: true, activa: false,
}

beforeEach(() => {
  rol = 'admin'
  listar.mockReset()
  borrar.mockReset()
  canchasListar.mockReset()
  listar.mockResolvedValue([VALLE, NOVIEMBRE])
  canchasListar.mockResolvedValue([
    { id: 4, sucursal_id: 1, nombre: 'Cancha 4', deporte: 'padel', duracion_turno_min: 90 },
  ])
  vi.stubGlobal('confirm', vi.fn(() => true))
})

describe('textoDeDias', () => {
  it('lee los días como los dice el dueño', () => {
    expect(textoDeDias(null)).toBe('Todos los días')
    expect(textoDeDias([1, 2, 3])).toBe('Mar a Jue')
    expect(textoDeDias([0, 2, 4])).toBe('Lun, Mié, Vie')
    // Dos seguidos no son un rango: «Sáb, Dom» y no «Sáb a Dom».
    expect(textoDeDias([5, 6])).toBe('Sáb, Dom')
    expect(textoDeDias([3, 1, 2])).toBe('Mar a Jue')
  })
})

describe('pantalla de promociones', () => {
  it('muestra el descuento, los días, la franja, la cancha y la vigencia', async () => {
    render(<Promociones />)

    const valle = (await screen.findByText('Hora valle')).closest('tr')!
    expect(within(valle).getByText('20% menos')).toBeInTheDocument()
    expect(within(valle).getByText('Mar a Jue')).toBeInTheDocument()
    expect(within(valle).getByText('14:00 – 17:00')).toBeInTheDocument()
    expect(within(valle).getByText('Toda la sucursal')).toBeInTheDocument()
    expect(within(valle).getByText('Siempre')).toBeInTheDocument()

    const nov = screen.getByText('Noviembre').closest('tr')!
    expect(within(nov).getByText('Cancha 4')).toBeInTheDocument()
    expect(within(nov).getByText(/y feriados/)).toBeInTheDocument()
    expect(within(nov).getByText('(inactiva)')).toBeInTheDocument()
    expect(within(nov).getByText('01-11-2026')).toBeInTheDocument()
    expect(within(nov).getByText('al 15-11-2026')).toBeInTheDocument()
  })

  it('el admin crea, edita y borra', async () => {
    render(<Promociones />)
    expect(await screen.findByRole('button', { name: /nueva promoción/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Editar Hora valle' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Borrar Hora valle' }))
    await waitFor(() => expect(borrar).toHaveBeenCalledWith(1))
  })

  it('🔑 el mostrador las ve pero no tiene cómo cambiarlas', async () => {
    rol = 'staff'
    render(<Promociones />)

    expect(await screen.findByText('Hora valle')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /nueva promoción/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Editar/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Borrar/ })).not.toBeInTheDocument()
  })

  it('sin promociones dice que se cobra a la tarifa', async () => {
    listar.mockResolvedValue([])
    render(<Promociones />)
    expect(await screen.findByText(/Los turnos se cobran a la tarifa/)).toBeInTheDocument()
  })
})
