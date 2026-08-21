import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Lo propio de esta pantalla, y que un test puede hacer fallar:
 *
 * 1. que una franja que **cruza medianoche** se lea como tal y no como un error
 *    de carga. Es el caso más común en pádel y el que la UI puede arruinar.
 * 2. que una sucursal **sin horario cargado** vea el cartel del default. Sin él,
 *    un complejo que abre a las 16 ofrece ocho horas de turnos inexistentes y no
 *    tiene forma de enterarse.
 * 3. que el formulario **no** exija `cierra > abre` — la validación que sí tiene
 *    la tarifa y que acá sería el bug.
 */

const listar = vi.fn()
const crear = vi.fn()
const canchasListar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    horarios: { ...(real.horarios as object), listar, crear, editar: vi.fn(), borrar: vi.fn() },
    canchas: { ...(real.canchas as object), listar: canchasListar },
  }
})

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'u', name: 'U', role: 'admin' }, loading: false }),
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

const { Horarios } = await import('./Horarios')

const NOCTURNA = {
  id: 1, sucursal_id: 1, cancha_id: null, alcance_dia: 'todos' as const,
  dia_semana: null, abre: '16:00:00', cierra: '02:00:00', activa: true,
}

beforeEach(() => {
  listar.mockReset()
  crear.mockReset()
  canchasListar.mockReset()
  canchasListar.mockResolvedValue([])
  listar.mockResolvedValue([NOCTURNA])
})

describe('pantalla de horario de atención', () => {
  it('una franja que cierra al día siguiente se marca, no se muestra al revés', async () => {
    render(<Horarios />)
    // 🔑 El `(+1)` es lo único que separa "cierra a las 2 de la mañana" de
    // "alguien cargó las horas invertidas". Sin la marca, el operador corrige
    // un dato que estaba bien y pierde las dos horas más caras del día.
    expect(await screen.findByText('16:00 – 02:00 (+1)')).toBeInTheDocument()
  })

  it('una franja normal NO lleva la marca', async () => {
    listar.mockResolvedValue([{ ...NOCTURNA, abre: '09:00:00', cierra: '22:00:00' }])
    render(<Horarios />)
    const celda = await screen.findByText(/09:00 – 22:00/)
    expect(celda).not.toHaveTextContent('(+1)')
  })

  it('sin horario cargado avisa que rige 08:00 a 00:00', async () => {
    listar.mockResolvedValue([])
    render(<Horarios />)
    const aviso = await screen.findByText(/no tiene horario cargado/i)
    expect(aviso.parentElement).toHaveTextContent(/08:00 a 00:00/)
  })

  it('con horario cargado el aviso desaparece', async () => {
    render(<Horarios />)
    await screen.findByText('16:00 – 02:00 (+1)')
    expect(screen.queryByText(/no tiene horario cargado/i)).not.toBeInTheDocument()
  })

  it('el formulario acepta que cierre antes de abrir, y dice cuánto dura', async () => {
    crear.mockResolvedValue(NOCTURNA)
    render(<Horarios />)
    await userEvent.click(await screen.findByRole('button', { name: /Nuevo horario/ }))

    const abre = screen.getByLabelText('Abre')
    const cierra = screen.getByLabelText('Cierra')
    await userEvent.clear(abre)
    await userEvent.type(abre, '16:00')
    await userEvent.clear(cierra)
    await userEvent.type(cierra, '02:00')

    // 10 horas, no un error: es la señal de que el dato se entendió.
    expect(screen.getByText(/Abierto 10 h — cierra al día siguiente/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(crear).toHaveBeenCalled())
    expect(crear.mock.calls[0][0]).toMatchObject({ abre: '16:00', cierra: '02:00' })
  })
})
