import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Los mostradores de la sucursal, y cuál es el predeterminado.
 *
 * 🔑 **Qué significa «predeterminada», medido y no supuesto.** Dos cosas, las
 * dos reales: la Caja la ofrece elegida al abrir el turno, y el motor se niega
 * a borrarla. Antes del 2026-08-29 el flag existía, viajaba en la respuesta y
 * en el tipo, y **no había forma de cambiarlo desde ninguna pantalla**.
 */

const deLaSucursal = vi.fn()
const predeterminada = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    cajas: { ...(real.cajas as object), deLaSucursal, predeterminada },
  }
})

vi.mock('@/context/SucursalContext', () => ({
  useSucursal: () => ({ actual: 1, sucursales: [], elegir: vi.fn(), cargando: false }),
}))

const rol = { valor: 'admin' }
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', name: 'Ana', role: rol.valor }, loading: false }),
}))

vi.mock('@/lib/medios-pago', () => ({
  useMediosDePago: () => ({ etiqueta: (m: string) => m, medios: [], cargando: false }),
}))

const { Cajas } = await import('./Cajas')

function caja(extra: Record<string, unknown> = {}) {
  return {
    id: 5, nombre: 'Barra', descripcion: '', medios_pago: [],
    activo: true, es_default: false, sucursal_id: 1, ...extra,
  }
}

/** La fila de la tabla cuyo nombre de caja es `nombre`. */
function fila(nombre: string) {
  return within(screen.getByText(nombre).closest('tr')!)
}

beforeEach(() => {
  rol.valor = 'admin'
  deLaSucursal.mockReset()
  predeterminada.mockReset()
  predeterminada.mockResolvedValue(caja({ es_default: true }))
  deLaSucursal.mockResolvedValue([
    caja({ id: 5, nombre: 'Barra', es_default: true }),
    caja({ id: 6, nombre: 'Quincho' }),
  ])
})

describe('la caja predeterminada', () => {
  it('se ve cuál lo es, y sólo esa', async () => {
    render(<Cajas />)
    await screen.findByText('Barra')
    expect(fila('Barra').getByText('Predeterminada')).toBeInTheDocument()
    expect(fila('Quincho').queryByText('Predeterminada')).toBeNull()
  })

  it('🔑 el botón se ofrece sobre las OTRAS, no sobre la que ya lo es', async () => {
    // Apretarlo sobre la que ya es predeterminada no haría nada, y un control
    // que no cambia nada enseña que la pantalla no responde.
    render(<Cajas />)
    await screen.findByText('Barra')
    expect(fila('Quincho').getByRole('button', { name: /Hacer predeterminada/ }))
      .toBeInTheDocument()
    expect(fila('Barra').queryByRole('button', { name: /Hacer predeterminada/ }))
      .toBeNull()
  })

  it('tampoco sobre una caja dada de baja', async () => {
    // Sería elegir como predeterminado un cajón sobre el que no se puede abrir
    // turno. El control positivo va al lado: la fila SÍ está en pantalla.
    deLaSucursal.mockResolvedValue([
      caja({ id: 5, nombre: 'Barra', es_default: true }),
      caja({ id: 6, nombre: 'Quincho', activo: false }),
    ])
    render(<Cajas />)
    await screen.findByText('Quincho')
    expect(fila('Quincho').getByText('Dada de baja')).toBeInTheDocument()
    expect(fila('Quincho').queryByRole('button', { name: /Hacer predeterminada/ }))
      .toBeNull()
  })

  it('🔴 al marcarla se RECARGA la lista, no se parchea la fila', async () => {
    /* Marcar una **apaga la anterior**, así que el cambio es de dos filas.
     * Parchear sólo la tocada dejaría dos pastillas de «Predeterminada» en
     * pantalla hasta el próximo refresco. */
    const user = userEvent.setup()
    render(<Cajas />)
    await screen.findByText('Barra')
    expect(deLaSucursal).toHaveBeenCalledTimes(1)

    deLaSucursal.mockResolvedValue([
      caja({ id: 5, nombre: 'Barra' }),
      caja({ id: 6, nombre: 'Quincho', es_default: true }),
    ])
    await user.click(fila('Quincho').getByRole('button', { name: /Hacer predeterminada/ }))

    await waitFor(() => expect(predeterminada).toHaveBeenCalledWith(6))
    await waitFor(() => expect(deLaSucursal).toHaveBeenCalledTimes(2))
    // Y la pastilla se movió: una sola, en la nueva.
    await waitFor(() => {
      expect(fila('Quincho').getByText('Predeterminada')).toBeInTheDocument()
    })
    expect(fila('Barra').queryByText('Predeterminada')).toBeNull()
  })

  it('si el backend la rechaza, lo dice y no miente que cambió', async () => {
    const user = userEvent.setup()
    predeterminada.mockRejectedValue(new Error('no existe esa caja'))
    render(<Cajas />)
    await screen.findByText('Barra')

    await user.click(fila('Quincho').getByRole('button', { name: /Hacer predeterminada/ }))

    expect(await screen.findByText(/no existe esa caja/)).toBeInTheDocument()
    // La pastilla sigue donde estaba.
    expect(fila('Barra').getByText('Predeterminada')).toBeInTheDocument()
  })

  it('🔑 un encargado no ve el botón: es configuración', async () => {
    // El backend ya lo gatea con `require_admin`; la pantalla no ofrece un
    // control que sólo puede terminar en 403.
    rol.valor = 'staff'
    render(<Cajas />)
    await screen.findByText('Barra')
    expect(screen.queryByRole('button', { name: /Hacer predeterminada/ })).toBeNull()
    // El control: la lista SÍ se ve, o la ausencia no probaría nada.
    expect(fila('Quincho').getByText('Activa')).toBeInTheDocument()
  })
})
