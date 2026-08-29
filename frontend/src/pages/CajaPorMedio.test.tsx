import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El reporte de caja por medio de pago.
 *
 * 🔑 **Los números vienen pivoteados del backend y acá sólo se dibujan.** Por
 * eso lo que se prueba es el cableado: que el período se mande, que la tabla lea
 * lo que llegó, y que el CSV apunte al mismo período que se está mirando —un
 * export que descarga otro rango es peor que no tenerlo—.
 */

const porMedio = vi.fn()
const deLaSucursal = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    caja: { ...(real.caja as object), porMedio },
    cajas: { ...(real.cajas as object), deLaSucursal },
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

const { CajaPorMedio } = await import('./CajaPorMedio')

function reporte(extra: Record<string, unknown> = {}) {
  return {
    desde: '2026-08-01',
    hasta: '2026-08-29',
    cajas: [{
      id: 5, nombre: 'Barra',
      medios: {
        efectivo: { ingresos: 5500, ingresos_ops: 2, egresos: 500, egresos_ops: 1 },
        transferencia: { ingresos: 9000, ingresos_ops: 1, egresos: 0, egresos_ops: 0 },
      },
      total_ingresos: 14500, total_egresos: 500, saldo: 14000,
    }],
    totales: {
      efectivo: { ingresos: 5500, ingresos_ops: 2, egresos: 500, egresos_ops: 1 },
      transferencia: { ingresos: 9000, ingresos_ops: 1, egresos: 0, egresos_ops: 0 },
    },
    total_ingresos: 14500,
    total_egresos: 500,
    ...extra,
  }
}

function montar() {
  return render(<MemoryRouter><CajaPorMedio /></MemoryRouter>)
}

beforeEach(() => {
  porMedio.mockReset()
  deLaSucursal.mockReset()
  porMedio.mockResolvedValue(reporte())
  deLaSucursal.mockResolvedValue([])
})

describe('lo que muestra', () => {
  it('los totales que mandó el backend, no una suma propia', async () => {
    /* 🔑 El mock devuelve un `total_ingresos` que **no** es la suma de las
     * filas —99.999 contra 5.500 + 9.000—, a propósito. Es la única forma de
     * distinguir «dibuja lo que le mandaron» de «suma las filas por su
     * cuenta»: con un total coherente, las dos implementaciones pasan igual. */
    porMedio.mockResolvedValue(reporte({ total_ingresos: 99999 }))
    montar()
    // Se dibuja el que vino, no el sumado.
    expect(await screen.findByText(/99\.999/)).toBeInTheDocument()
  })

  it('una fila por medio, con sus operaciones', async () => {
    montar()
    await screen.findByText('Efectivo')
    const fila = within(screen.getByText('Efectivo').closest('tr')!)
    expect(fila.getByText('2')).toBeInTheDocument()
  })

  it('los medios se ordenan por lo que más entró', async () => {
    // Transferencia (9000) va antes que Efectivo (5500): el que abre esto quiere
    // ver arriba por dónde entra la plata.
    montar()
    await screen.findByText('Efectivo')
    const filas = screen.getAllByRole('row').slice(1)  // sin el encabezado
    expect(filas[0].textContent).toContain('Transferencia')
  })

  it('un período sin movimientos lo DICE, no queda en blanco', async () => {
    // Un período vacío y una consulta rota se ven igual si la pantalla no dice
    // nada. El control positivo: los filtros SÍ se dibujaron.
    porMedio.mockResolvedValue(reporte({ totales: {}, cajas: [], total_ingresos: 0, total_egresos: 0 }))
    montar()
    expect(await screen.findByText(/No hubo movimientos de caja/)).toBeInTheDocument()
    expect(screen.getByLabelText('Desde')).toBeInTheDocument()
  })

  it('si el backend falla, lo dice', async () => {
    porMedio.mockRejectedValue(new Error('la caja no está configurada'))
    montar()
    expect(await screen.findByText(/la caja no está configurada/)).toBeInTheDocument()
  })
})

describe('los filtros', () => {
  it('cambiar el período vuelve a pedir el reporte', async () => {
    const user = userEvent.setup()
    montar()
    await screen.findByText('Efectivo')
    expect(porMedio).toHaveBeenCalledTimes(1)

    await user.clear(screen.getByLabelText('Desde'))
    await user.type(screen.getByLabelText('Desde'), '2026-07-01')

    await waitFor(() => {
      expect(porMedio).toHaveBeenLastCalledWith(
        expect.objectContaining({ desde: '2026-07-01' }),
      )
    })
  })

  it('🔴 el CSV apunta al MISMO período que se está mirando', async () => {
    /* Un export que descarga otro rango es peor que no tenerlo: el que lo abre
     * no tiene forma de notar que no es lo que veía en pantalla. */
    const user = userEvent.setup()
    montar()
    await screen.findByText('Efectivo')

    await user.clear(screen.getByLabelText('Hasta'))
    await user.type(screen.getByLabelText('Hasta'), '2026-08-15')

    await waitFor(() => {
      const enlace = screen.getByRole('link', { name: /Exportar CSV/ })
      expect(enlace.getAttribute('href')).toContain('hasta=2026-08-15')
    })
  })

  it('con un solo mostrador no se ofrece el selector', async () => {
    // La única opción además de «todos» sería ése mismo.
    deLaSucursal.mockResolvedValue([
      { id: 5, nombre: 'Barra', descripcion: '', medios_pago: [], activo: true, es_default: true, sucursal_id: 1 },
    ])
    montar()
    await screen.findByText('Efectivo')
    expect(screen.queryByLabelText('Mostrador')).toBeNull()
  })

  it('con dos, sí — y elegir uno vuelve a pedir', async () => {
    const user = userEvent.setup()
    deLaSucursal.mockResolvedValue([
      { id: 5, nombre: 'Barra', descripcion: '', medios_pago: [], activo: true, es_default: true, sucursal_id: 1 },
      { id: 6, nombre: 'Quincho', descripcion: '', medios_pago: [], activo: true, es_default: false, sucursal_id: 1 },
    ])
    montar()
    const selector = await screen.findByLabelText('Mostrador')
    await user.selectOptions(selector, '6')

    await waitFor(() => {
      expect(porMedio).toHaveBeenLastCalledWith(expect.objectContaining({ cajaId: 6 }))
    })
  })
})

describe('por mostrador', () => {
  it('con uno solo no se repite la tabla de arriba', async () => {
    montar()
    await screen.findByText('Efectivo')
    expect(screen.queryByText('Por mostrador')).toBeNull()
  })

  it('con dos, aparece', async () => {
    porMedio.mockResolvedValue(reporte({
      cajas: [
        { id: 5, nombre: 'Barra', medios: {}, total_ingresos: 5500, total_egresos: 0, saldo: 5500 },
        { id: 6, nombre: 'Quincho', medios: {}, total_ingresos: 9000, total_egresos: 500, saldo: 8500 },
      ],
    }))
    montar()
    expect(await screen.findByText('Por mostrador')).toBeInTheDocument()
    expect(screen.getByText('Quincho')).toBeInTheDocument()
  })
})
