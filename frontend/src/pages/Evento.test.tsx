import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El evento junta varias categorías —cada una un torneo— con las mismas fechas y
 * canchas. Lo que esta pantalla decide:
 *
 * 1. que muestre **cada categoría** con su estado, sus parejas y su campeón, y
 *    lleve al torneo;
 * 2. que diga las canchas del evento (o que vale cualquiera);
 * 3. que sumar una categoría y editar el evento sean cosa del admin.
 */

const ver = vi.fn()
const canchasListar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    eventos: { ...(real.eventos as object), ver },
    canchas: { ...(real.canchas as object), listar: canchasListar },
  }
})

let ROL = 'admin'
vi.mock('@/context/AuthContext', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    useAuth: () => ({ user: { role: ROL, name: 'Quien sea' }, loading: false }),
  }
})

const { Evento } = await import('./Evento')

const CATEGORIA = {
  id: 11, sucursal_id: 1, nombre: 'Americano de primavera — Damas', deporte: 'padel',
  formato: 'zonas' as const, estado: 'sorteado' as const, desde: '2026-10-10',
  hasta: '2026-10-11', sets_para_ganar: 1, games_por_set: 6, cantidad_zonas: 2,
  clasifican_por_zona: null, termina_en_zonas: true, categoria: 'Damas', evento_id: 3,
  semilla: 5, observaciones: null, competidores: 6, partidos: 6, jugados: 3,
  sin_programar: 3, campeon: 'Zona A: Aguirre / Bustos', evento: 'Americano de primavera',
}

const EVENTO = {
  id: 3, sucursal_id: 1, nombre: 'Americano de primavera', desde: '2026-10-10',
  hasta: '2026-10-11', observaciones: null, cancha_ids: [8],
  categorias: [
    CATEGORIA,
    { ...CATEGORIA, id: 12, categoria: 'Mixto', competidores: 1, partidos: 0, jugados: 0,
      estado: 'armado' as const, campeon: null, termina_en_zonas: false,
      clasifican_por_zona: 2 },
  ],
}

function montar() {
  return render(
    <MemoryRouter initialEntries={['/torneos/eventos/3']}>
      <Routes>
        <Route path="/torneos/eventos/:id" element={<Evento />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  ROL = 'admin'
  ver.mockReset()
  canchasListar.mockReset()
  ver.mockResolvedValue(EVENTO)
  canchasListar.mockResolvedValue([
    { id: 7, sucursal_id: 1, nombre: 'Cancha 1', deporte: 'padel', duracion_turno_min: 90,
      techada: false, iluminacion: true, superficie: null, orden: 0, activa: true,
      observaciones: null },
    { id: 8, sucursal_id: 1, nombre: 'Cancha 2', deporte: 'padel', duracion_turno_min: 90,
      techada: false, iluminacion: true, superficie: null, orden: 1, activa: true,
      observaciones: null },
  ])
})

describe('el evento', () => {
  it('muestra el nombre, las fechas y las canchas del evento', async () => {
    montar()
    expect(
      await screen.findByRole('heading', { name: /Americano de primavera/ }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Cancha 2/)).toBeInTheDocument()
    expect(screen.queryByText(/Cancha 1/)).not.toBeInTheDocument()
  })

  it('sin canchas cargadas, dice que vale cualquiera', async () => {
    ver.mockResolvedValue({ ...EVENTO, cancha_ids: [] })
    montar()
    expect(await screen.findByText(/Cualquier cancha de la sucursal/)).toBeInTheDocument()
  })

  it('muestra cada categoría con sus parejas, sus jugados y su campeón, y lleva al torneo', async () => {
    montar()
    const damas = await screen.findByRole('link', { name: /Damas/ })
    expect(damas).toHaveAttribute('href', '/torneos/11')
    expect(within(damas).getByText(/6 parejas/)).toBeInTheDocument()
    expect(within(damas).getByText(/3 de 6 jugados/)).toBeInTheDocument()
    expect(within(damas).getByText('Zona A: Aguirre / Bustos')).toBeInTheDocument()
    expect(within(damas).getByText(/Por zonas, sin llaves/)).toBeInTheDocument()
    expect(within(damas).getByText('En curso')).toBeInTheDocument()

    const mixto = screen.getByRole('link', { name: /Mixto/ })
    expect(mixto).toHaveAttribute('href', '/torneos/12')
    expect(within(mixto).getByText(/1 pareja\b/)).toBeInTheDocument()
    expect(within(mixto).getByText('Inscribiendo')).toBeInTheDocument()
    expect(within(mixto).getByText(/Por zonas y llaves/)).toBeInTheDocument()
  })

  it('el admin puede sumar una categoría, que hereda las fechas', async () => {
    montar()
    await userEvent.click(await screen.findByRole('button', { name: /Nueva categoría/ }))
    const dialogo = await screen.findByRole('dialog')
    expect(
      within(dialogo).getByRole('heading', { name: 'Nueva categoría de Americano de primavera' }),
    ).toBeInTheDocument()
    expect(within(dialogo).queryByLabelText('Desde')).toBeNull()
  })

  it('y editar el evento, con las canchas tildadas', async () => {
    montar()
    await userEvent.click(await screen.findByRole('button', { name: /Editar/ }))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Cancha 2')).toBeChecked()
    expect(within(dialogo).getByLabelText('Cancha 1')).not.toBeChecked()
    expect(within(dialogo).getByText(/cambian en todas las categorías/)).toBeInTheDocument()
  })

  it('el mostrador mira el evento pero no lo toca', async () => {
    ROL = 'staff'
    montar()
    await screen.findByRole('link', { name: /Damas/ })
    expect(screen.queryByRole('button', { name: /Nueva categoría/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Editar/ })).not.toBeInTheDocument()
  })

  it('un evento sin categorías lo dice', async () => {
    ver.mockResolvedValue({ ...EVENTO, categorias: [] })
    montar()
    expect(await screen.findByText(/todavía no tiene categorías/)).toBeInTheDocument()
  })

  it('un evento que no existe avisa y vuelve', async () => {
    ver.mockRejectedValue(new Error('No existe ese evento.'))
    montar()
    await waitFor(() => expect(screen.getByText('No existe ese evento.')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Volver a torneos' })).toBeInTheDocument()
  })
})
