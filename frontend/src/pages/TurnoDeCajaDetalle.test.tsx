import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El detalle de un turno de caja.
 *
 * Es lo que hace que el historial sirva: sin esto, la lista de turnos no se
 * puede abrir. Lo que se fija acá es qué muestra y —sobre todo— **qué NO**:
 * un arqueo cerrado no se toca, así que esta pantalla es de sólo lectura.
 */

const detalle = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return { ...real, caja: { ...(real.caja as object), detalle } }
})

// Los medios de pago se piden al backend; acá alcanza con que la etiqueta
// exista, y el hook tiene su propio test.
vi.mock('@/lib/medios-pago', () => ({
  useMediosDePago: () => ({
    etiqueta: (m: string) => (m === 'efectivo' ? 'Efectivo' : m),
    medios: [],
    cargando: false,
  }),
}))

const { TurnoDeCajaDetalle } = await import('./TurnoDeCajaDetalle')

function turno(extra: Record<string, unknown> = {}) {
  return {
    id: 12,
    usuario_id: 1,
    caja_id: 3,
    caja_nombre: 'Barra del fondo',
    usuario_nombre: 'Ana Gómez',
    apertura: '2026-08-28T09:00:00-03:00',
    cierre: '2026-08-28T18:30:00-03:00',
    monto_inicial: 1000,
    monto_declarado_cierre: 4700,
    monto_esperado_cierre: 5000,
    estado: 'cerrado',
    notas: '',
    ...extra,
  }
}

function resumen(extra: Record<string, unknown> = {}) {
  return {
    movimientos: [
      {
        id: 1, fecha: '2026-08-28T10:15:00-03:00', tipo: 'ingreso',
        concepto: 'Cancha 1', monto: 4000, medio_pago: 'efectivo', anulado: 0,
      },
    ],
    pagos_por_medio: { efectivo: 4000 },
    total_ventas: 4000,
    efectivo_ventas: 4000,
    ...extra,
  }
}

/** La tarjeta cuyo `<h2>` dice `titulo`.
 *
 * ⚠️ Sin esto las búsquedas son ambiguas y **eso es correcto**: «Mostrador» y
 * «Efectivo» aparecen a propósito en más de un lugar de esta pantalla —el medio
 * está en la recaudación y también en cada movimiento—. Buscar en toda la
 * pantalla encuentra los dos y no distingue cuál se está mirando.
 */
function tarjeta(titulo: string) {
  // ⚠️ Se busca por PREFIJO y no por nombre exacto: el `<h2>` de «Datos del
  // turno» lleva la pastilla de estado adentro, así que su nombre accesible es
  // «Datos del turno Cerrado». Un match exacto no lo encuentra.
  const encabezado = screen.getByRole('heading', {
    name: (nombre: string) => nombre.startsWith(titulo),
  })
  return within(encabezado.closest('section')!)
}

function montar() {
  return render(
    <MemoryRouter initialEntries={['/caja/turnos/12']}>
      <Routes>
        <Route path="/caja/turnos/:id" element={<TurnoDeCajaDetalle />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  detalle.mockReset()
  detalle.mockResolvedValue({ turno: turno(), resumen: resumen() })
})

describe('lo que muestra', () => {
  it('los datos del turno, con el cajero y el mostrador', async () => {
    montar()
    await screen.findByText('Ana Gómez')
    const datos = tarjeta('Datos del turno')
    expect(datos.getByText('Ana Gómez')).toBeInTheDocument()
    expect(datos.getByText('Barra del fondo')).toBeInTheDocument()
  })

  it('la recaudación por medio, con su total', async () => {
    montar()
    await screen.findByText('Recaudación por medio')
    const recaudacion = tarjeta('Recaudación por medio')
    expect(recaudacion.getByText('Efectivo')).toBeInTheDocument()
    expect(recaudacion.getByText('Total')).toBeInTheDocument()
    // El control de que el helper acota de verdad: «Cancha 1» es el concepto de
    // un movimiento y NO tiene por qué estar en esta tarjeta.
    expect(recaudacion.queryByText('Cancha 1')).toBeNull()
  })

  it('🔑 el resultado del cierre, con la diferencia', async () => {
    // Es el número por el que se abre esta pantalla.
    montar()
    expect(await screen.findByText('Resultado del cierre')).toBeInTheDocument()
    expect(screen.getByText(/faltó/)).toBeInTheDocument()
  })

  it('sobre un turno ABIERTO no promete un cierre que todavía no pasó', async () => {
    /* Una tarjeta de «resultado del cierre» con guiones invita a pensar que el
     * cierre falló. El control positivo va al lado: la pantalla SÍ renderizó,
     * o el `queryByText` de abajo pasaría por no haber nada. */
    detalle.mockResolvedValue({
      turno: turno({
        estado: 'abierto', cierre: null,
        monto_declarado_cierre: null, monto_esperado_cierre: null,
      }),
      resumen: resumen(),
    })
    montar()
    expect(await screen.findByText('Abierto')).toBeInTheDocument()
    expect(screen.queryByText('Resultado del cierre')).toBeNull()
  })

  it('un turno sin movimientos lo dice, en vez de una tabla vacía', async () => {
    detalle.mockResolvedValue({
      turno: turno(),
      resumen: resumen({ movimientos: [], pagos_por_medio: {}, total_ventas: 0 }),
    })
    montar()
    expect(await screen.findByText(/No hubo movimientos/)).toBeInTheDocument()
    expect(screen.getByText(/No entró plata/)).toBeInTheDocument()
  })
})

describe('los movimientos', () => {
  it('🔴 un anulado va tachado Y con la palabra', async () => {
    /* Las dos cosas: sólo el tachado se pierde en una impresión en blanco y
     * negro y no lo lee un lector de pantalla; sola la palabra se pierde entre
     * las filas. Misma decisión que en /caja/movimientos. */
    detalle.mockResolvedValue({
      turno: turno(),
      resumen: resumen({
        movimientos: [
          {
            id: 1, fecha: '2026-08-28T10:15:00-03:00', tipo: 'ingreso',
            concepto: 'Cobro mal cargado', monto: 4000, medio_pago: 'efectivo',
            anulado: 1,
          },
        ],
      }),
    })
    montar()
    const concepto = await screen.findByText('Cobro mal cargado')
    expect(concepto.className).toContain('line-through')
    expect(screen.getByText('anulado')).toBeInTheDocument()
  })

  it('y uno normal NO va tachado — el control del de arriba', async () => {
    montar()
    const concepto = await screen.findByText('Cancha 1')
    expect(concepto.className).not.toContain('line-through')
    expect(screen.queryByText('anulado')).toBeNull()
  })

  it('🔴 no se ofrece anular: un arqueo cerrado no se toca', async () => {
    /* El backend ya lo rechaza —`anular` exige turno abierto— y un botón que
     * sólo puede fallar es peor que no ofrecerlo. El control positivo: la
     * fila SÍ está en pantalla, o la ausencia del botón no probaría nada. */
    montar()
    expect(await screen.findByText('Cancha 1')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /anular/i })).toBeNull()
  })
})

describe('cuando no se puede mostrar', () => {
  it('el turno de otro: se muestra el motivo del backend', async () => {
    detalle.mockRejectedValue(new Error('sólo podés ver tu propia caja'))
    montar()
    expect(await screen.findByText(/sólo podés ver tu propia caja/)).toBeInTheDocument()
    // Y no queda un hueco mudo abajo, que se lee como «se colgó».
    expect(screen.getByText(/No se pudo mostrar este turno/)).toBeInTheDocument()
  })

  it('uno que no existe: lo mismo', async () => {
    detalle.mockRejectedValue(new Error('no existe ese turno'))
    montar()
    expect(await screen.findByText(/no existe ese turno/)).toBeInTheDocument()
  })
})
