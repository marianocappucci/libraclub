import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El cierre diario: la vista previa, el botón de cerrar y el listado de
 * cierres de la sucursal activa.
 *
 * 🔑 **Los números y el estado vienen del backend.** Lo que se prueba acá es
 * el cableado: que los turnos abiertos bloqueen el botón, que cerrar pida
 * confirmación y mande la sucursal activa, y que el listado ofrezca imprimir.
 */

const preview = vi.fn()
const cerrar = vi.fn()
const listar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    cierreDiario: {
      ...(real.cierreDiario as object),
      preview, cerrar, listar,
      urlDelTicket: (id: number) => `/api/cierre-diario/${id}/ticket`,
    },
  }
})

vi.mock('@/context/SucursalContext', () => ({
  useSucursal: () => ({ actual: 1, sucursales: [], elegir: vi.fn(), cargando: false }),
}))

vi.mock('@/lib/medios-pago', () => ({
  useMediosDePago: () => ({
    etiqueta: (m: string) => (m === 'efectivo' ? 'Efectivo' : 'Transferencia'),
    medios: [], cargando: false,
  }),
}))

const { CierreDiario } = await import('./CierreDiario')

function previewDe(extra: Record<string, unknown> = {}) {
  return {
    fecha: '2026-09-13',
    sucursal_id: 1,
    turnos_abiertos: [],
    turnos: [
      {
        id: 10, usuario_id: 1, usuario_nombre: 'Ana', caja_id: 5,
        caja_nombre: 'Mostrador', apertura: '2026-09-13T09:00:00-03:00',
        cierre: '2026-09-13T18:00:00-03:00', monto_inicial: 1000,
        monto_esperado_cierre: 6000, monto_declarado_cierre: 6000,
        estado: 'cerrado', notas: '', diferencia: 0, medios: [],
      },
    ],
    medios: [{ medio_pago: 'efectivo', ingresos: 5000, egresos: 0, neto: 5000 }],
    monto_esperado_total: 6000,
    monto_declarado_total: 6000,
    diferencia_total: 0,
    puede_cerrar: true,
    ya_cerrado: false,
    ...extra,
  }
}

function cierreDe(extra: Record<string, unknown> = {}) {
  return {
    id: 1, sucursal_id: 1, numero: 1, fecha: '2026-09-12', usuario_id: 1,
    cerrado_por_nombre: 'Admin', monto_esperado_total: 6000,
    monto_declarado_total: 6000, diferencia_total: 0, notas: '',
    created_at: '2026-09-12T20:00:00-03:00',
    ...extra,
  }
}

function montar() {
  return render(<MemoryRouter><CierreDiario /></MemoryRouter>)
}

beforeEach(() => {
  preview.mockReset()
  cerrar.mockReset()
  listar.mockReset()
  preview.mockResolvedValue(previewDe())
  listar.mockResolvedValue([cierreDe()])
})

describe('la vista previa', () => {
  it('con turnos abiertos, los muestra y deshabilita «Cerrar el día»', async () => {
    preview.mockResolvedValue(previewDe({
      puede_cerrar: false,
      turnos_abiertos: [{
        id: 20, usuario_id: 2, usuario_nombre: 'Bruno', caja_id: 6,
        caja_nombre: 'Buffet', apertura: '2026-09-13T10:00:00-03:00',
        cierre: null, monto_inicial: 0, monto_esperado_cierre: null,
        monto_declarado_cierre: null, estado: 'abierto', notas: '',
      }],
    }))
    montar()
    expect(await screen.findByText(/Bruno/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cerrar el día' })).toBeDisabled()
  })

  it('sin turnos abiertos, el botón queda habilitado — el control del de arriba', async () => {
    montar()
    await screen.findByText('Ana')
    expect(screen.getByRole('button', { name: 'Cerrar el día' })).toBeEnabled()
  })

  it('el día ya cerrado también deshabilita el botón', async () => {
    preview.mockResolvedValue(previewDe({ ya_cerrado: true }))
    montar()
    expect(await screen.findByText(/ya está cerrado/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cerrar el día' })).toBeDisabled()
  })
})

describe('cerrar el día', () => {
  it('🔴 pide confirmación antes de mandar el POST', async () => {
    const user = userEvent.setup()
    montar()
    await screen.findByText('Ana')
    await user.click(screen.getByRole('button', { name: 'Cerrar el día' }))
    // Todavía no se mandó nada: el diálogo está pidiendo confirmar.
    expect(cerrar).not.toHaveBeenCalled()
    expect(screen.getByText(/no se puede deshacer/i)).toBeInTheDocument()
  })

  it('🔑 confirmando, manda la sucursal activa', async () => {
    cerrar.mockResolvedValue(cierreDe())
    const user = userEvent.setup()
    montar()
    await screen.findByText('Ana')
    await user.click(screen.getByRole('button', { name: 'Cerrar el día' }))
    await user.click(
      within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Cerrar el día' }),
    )

    await waitFor(() => {
      expect(cerrar).toHaveBeenCalledWith(1, expect.any(String))
    })
  })

  it('el error del servidor (422, turnos abiertos) se muestra', async () => {
    cerrar.mockRejectedValue(new Error('Hay 1 turno abierto en esta sucursal'))
    const user = userEvent.setup()
    montar()
    await screen.findByText('Ana')
    await user.click(screen.getByRole('button', { name: 'Cerrar el día' }))
    await user.click(
      within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Cerrar el día' }),
    )

    expect(await screen.findByText(/Hay 1 turno abierto/)).toBeInTheDocument()
  })
})

describe('el listado', () => {
  it('muestra número, fecha, quién cerró y diferencia', async () => {
    montar()
    await screen.findByText('Admin')
    expect(screen.getByText('12-09-2026')).toBeInTheDocument()
  })

  it('🔑 ofrece imprimir y abre la ruta del ticket de ESE cierre', async () => {
    const abrir = vi.fn()
    vi.stubGlobal('open', abrir)
    const user = userEvent.setup()
    montar()
    await screen.findByText('Admin')
    await user.click(screen.getByRole('button', { name: /Imprimir ticket/ }))
    expect(abrir).toHaveBeenCalledWith('/api/cierre-diario/1/ticket', '_blank', 'noopener')
  })

  it('sin cierres previos lo dice, en vez de una tabla vacía', async () => {
    listar.mockResolvedValue([])
    montar()
    expect(await screen.findByText(/Todavía no se cerró ningún día/)).toBeInTheDocument()
  })
})
