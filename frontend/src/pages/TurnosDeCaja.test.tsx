import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El historial de turnos de caja.
 *
 * 🔴 **Esta pantalla existe porque el endpoint estaba y nadie lo llamaba.**
 * `GET /api/caja/turnos` y `caja.historial()` existían desde el 2026-08-21 con
 * cero call sites: el arqueo de ayer no se podía mirar.
 *
 * La tabla la dibuja `libra-ui/data-table` y la prueba el kit. Lo que se fija
 * acá es lo que **decide esta pantalla**: qué columnas se leen, cómo se lee una
 * diferencia de arqueo, y que no haya ningún filtro por rol del lado del
 * navegador.
 */

const historial = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return { ...real, caja: { ...(real.caja as object), historial } }
})

const { TurnosDeCaja } = await import('./TurnosDeCaja')

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
    monto_declarado_cierre: 5000,
    monto_esperado_cierre: 5000,
    estado: 'cerrado',
    notas: '',
    ...extra,
  }
}

function DetalleFalso() {
  const { id } = useParams()
  return <p>detalle del turno {id}</p>
}

function montar() {
  return render(
    <MemoryRouter initialEntries={['/caja/turnos']}>
      <Routes>
        <Route path="/caja/turnos" element={<TurnosDeCaja />} />
        <Route path="/caja/turnos/:id" element={<DetalleFalso />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  historial.mockReset()
  historial.mockResolvedValue([turno()])
})

describe('el historial', () => {
  it('dice quién abrió cada turno', async () => {
    // Es la columna que más importa de la pantalla de un admin: una lista de
    // cierres sin dueño no dice nada. El backend ya devolvía el nombre y el
    // tipo del frontend lo tiraba.
    montar()
    const celda = await screen.findByText('Ana Gómez')
    // Acotado a la fila: «Mostrador» es también el encabezado de esa columna, y
    // un `getByText` suelto encuentra los dos y falla por ambiguo.
    const fila = within(celda.closest('tr')!)
    expect(fila.getByText('Ana Gómez')).toBeInTheDocument()
    expect(fila.getByText('Barra del fondo')).toBeInTheDocument()
  })

  it('un turno sin mostrador lo DICE, no deja la celda en blanco', async () => {
    // Los turnos anteriores al 2026-08-28 nacieron sin caja. Una celda vacía
    // se lee como «se rompió», no como «no tenía».
    historial.mockResolvedValue([turno({ caja_nombre: '' })])
    montar()
    expect(await screen.findByText('sin mostrador')).toBeInTheDocument()
  })

  it('abrir un turno lleva a ESE turno, no a otro', async () => {
    const user = userEvent.setup()
    historial.mockResolvedValue([turno({ id: 12 }), turno({ id: 99, usuario_nombre: 'Beto Ruiz' })])
    montar()

    await user.click(await screen.findByRole('link', { name: /Ver el turno 99/ }))
    expect(await screen.findByText('detalle del turno 99')).toBeInTheDocument()
  })

  it('🔑 no filtra nada por rol: muestra lo que el backend mandó', async () => {
    /* Quién ve qué lo decide el backend, en la consulta. Si esta pantalla
     * escondiera filas por su cuenta, los datos ajenos igual habrían viajado
     * hasta el navegador — y encima habría dos criterios que mantener de
     * acuerdo. Se asierta que las DOS filas se dibujan aunque sean de cajeros
     * distintos. */
    historial.mockResolvedValue([
      turno({ id: 1, usuario_id: 1, usuario_nombre: 'Ana Gómez' }),
      turno({ id: 2, usuario_id: 2, usuario_nombre: 'Beto Ruiz' }),
    ])
    montar()
    expect(await screen.findByText('Ana Gómez')).toBeInTheDocument()
    expect(screen.getByText('Beto Ruiz')).toBeInTheDocument()
  })

  it('si el backend falla, lo dice', async () => {
    historial.mockRejectedValue(new Error('no se pudo leer la caja'))
    montar()
    expect(await screen.findByText(/no se pudo leer la caja/)).toBeInTheDocument()
  })
})

describe('la diferencia del arqueo', () => {
  /* 🔑 Es el número por el que se abre esta pantalla. Un signo al revés hace
   * que un faltante se lea como sobrante, que es peor que no mostrar nada. */

  async function filaCon(extra: Record<string, unknown>) {
    historial.mockResolvedValue([turno(extra)])
    montar()
    const celda = await screen.findByText('Ana Gómez')
    return within(celda.closest('tr')!)
  }

  it('cuando falta plata lo dice, y con la palabra', async () => {
    const fila = await filaCon({ monto_esperado_cierre: 5000, monto_declarado_cierre: 4700 })
    expect(fila.getByText(/faltó/)).toBeInTheDocument()
    expect(fila.queryByText(/sobró/)).toBeNull()
  })

  it('cuando sobra, también', async () => {
    const fila = await filaCon({ monto_esperado_cierre: 5000, monto_declarado_cierre: 5300 })
    expect(fila.getByText(/sobró/)).toBeInTheDocument()
    expect(fila.queryByText(/faltó/)).toBeNull()
  })

  it('🔴 una diferencia de UN CENTAVO cuadra: no es un faltante que buscar', async () => {
    /* ⚠️ **Este test asertaba `4999.999999` y no medía nada.** El
     * `Math.round(... * 100) / 100` devuelve `-0` para esa entrada, y `-0 < 0`
     * es `false`, así que pasaba con el umbral puesto Y sacado. Lo delató la
     * mutación, no la lectura.
     *
     * El umbral no protege de floats —de eso se ocupa el redondeo—: es la
     * decisión de que contando efectivo un centavo es cuadrar. Eso es lo que se
     * fija acá, con el valor exacto del borde. */
    const fila = await filaCon({
      monto_esperado_cierre: 5000, monto_declarado_cierre: 4999.99,
    })
    expect(fila.getByText(/cuadró/)).toBeInTheDocument()
    expect(fila.queryByText(/faltó/)).toBeNull()
  })

  it('y dos centavos ya NO cuadran — el otro lado del borde', async () => {
    /* El control del de arriba: sin esto, un `cuadró` que se devuelve siempre
     * pasaría igual, y la pantalla diría que cuadra un faltante de mil pesos. */
    const fila = await filaCon({
      monto_esperado_cierre: 5000, monto_declarado_cierre: 4999.98,
    })
    expect(fila.getByText(/faltó/)).toBeInTheDocument()
    expect(fila.queryByText(/cuadró/)).toBeNull()
  })

  it('un turno todavía abierto no tiene diferencia que mostrar', async () => {
    const fila = await filaCon({
      estado: 'abierto', cierre: null,
      monto_esperado_cierre: null, monto_declarado_cierre: null,
    })
    expect(fila.queryByText(/faltó|sobró|cuadró/)).toBeNull()
    expect(fila.getByText('Abierto')).toBeInTheDocument()
  })
})
