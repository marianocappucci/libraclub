import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FormularioDePromocion } from './FormularioDePromocion'
import { elegirEnBuscable } from '@/test/select-buscable'
import type { Cancha, Promocion } from '@/lib/api'

const CANCHAS: Cancha[] = [
  {
    id: 3, sucursal_id: 1, nombre: 'Cancha 3', deporte: 'padel', duracion_turno_min: 90,
    techada: true, iluminacion: true, superficie: null, orden: 0, activa: true, observaciones: null,
  },
]

/** Una promoción como la devuelve el backend: horas en `HH:MM:SS`. */
const EXISTENTE: Promocion = {
  id: 7, sucursal_id: 1, cancha_id: 3, nombre: 'Hora valle', descuento_porcentaje: 20,
  dias_semana: [1, 2, 3], hora_desde: '14:00:00', hora_hasta: '17:00:00',
  vigente_desde: '2026-11-01', vigente_hasta: '2026-11-30', aplica_en_feriados: false, activa: true,
}

let llamadas: { url: string; metodo: string; cuerpo: Record<string, unknown> }[]

beforeEach(() => {
  llamadas = []
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    llamadas.push({
      url,
      metodo: init?.method ?? 'GET',
      cuerpo: init?.body ? JSON.parse(String(init.body)) : {},
    })
    return { ok: true, status: 201, json: async () => ({ id: 1 }) } as Response
  })
})

afterEach(() => vi.unstubAllGlobals())

function abrir(promocion: Promocion | null) {
  const onGuardada = vi.fn()
  render(
    <FormularioDePromocion
      abierto
      promocion={promocion}
      canchas={CANCHAS}
      sucursalId={1}
      onCerrar={vi.fn()}
      onGuardada={onGuardada}
    />,
  )
  return onGuardada
}

async function nombrar(user: ReturnType<typeof userEvent.setup>, texto: string) {
  await user.type(screen.getByRole('textbox', { name: /nombre/i }), texto)
}

describe('formulario de promoción', () => {
  it('🔑 sin días marcados viaja null (todos los días), nunca una lista vacía', async () => {
    // El backend rechaza `[]` con 422 porque sería «no aplica ningún día».
    const user = userEvent.setup()
    const onGuardada = abrir(null)
    await nombrar(user, 'Hora valle')
    expect(screen.getByText('Sin elegir ninguno, aplica todos los días.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() => expect(onGuardada).toHaveBeenCalledTimes(1))
    expect(llamadas.find((l) => l.metodo === 'POST')!.cuerpo).toMatchObject({
      dias_semana: null, descuento_porcentaje: 20, hora_desde: '14:00', hora_hasta: '17:00',
      cancha_id: null, aplica_en_feriados: false, vigente_desde: null, vigente_hasta: null,
    })
  })

  it('los días marcados viajan ordenados, y desmarcar el último vuelve a null', async () => {
    const user = userEvent.setup()
    const onGuardada = abrir(null)
    await nombrar(user, 'Entre semana')
    // Se marcan fuera de orden: el cuerpo los manda ordenados.
    await user.click(screen.getByLabelText('Jue'))
    await user.click(screen.getByLabelText('Mar'))
    expect(screen.getByText('Sólo los días marcados.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardada).toHaveBeenCalledTimes(1))
    expect(llamadas.find((l) => l.metodo === 'POST')!.cuerpo).toMatchObject({ dias_semana: [1, 3] })

    await user.click(screen.getByLabelText('Jue'))
    await user.click(screen.getByLabelText('Mar'))
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardada).toHaveBeenCalledTimes(2))
    expect(llamadas.filter((l) => l.metodo === 'POST')[1].cuerpo).toMatchObject({ dias_semana: null })
  })

  it('la cancha se elige entre las de la sucursal y «Toda la sucursal» viaja como null', async () => {
    const user = userEvent.setup()
    const onGuardada = abrir(null)
    await nombrar(user, 'De una cancha')
    await elegirEnBuscable(user, screen.getByRole('combobox', { name: /cancha/i }), 'Cancha 3')

    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() => expect(onGuardada).toHaveBeenCalledTimes(1))
    expect(llamadas.find((l) => l.metodo === 'POST')!.cuerpo).toMatchObject({ cancha_id: 3 })
  })

  it('no manda nada si el descuento es 0 o 100: el tope es 99', async () => {
    const user = userEvent.setup()
    abrir(null)
    await nombrar(user, 'Regalada')
    const descuento = screen.getByRole('spinbutton', { name: /descuento/i })

    await user.clear(descuento)
    await user.type(descuento, '100')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('El descuento va de 1 a 99%.')

    await user.clear(descuento)
    await user.type(descuento, '0')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('El descuento va de 1 a 99%.')
    expect(llamadas).toEqual([])
  })

  it('exige nombre, franja bien armada y vigencia que no termine antes de empezar', async () => {
    const user = userEvent.setup()
    abrir(null)

    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('necesita un nombre')

    await nombrar(user, 'X')
    const hasta = screen.getByLabelText(/hasta la hora/i)
    await user.clear(hasta)
    await user.type(hasta, '13:00')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('terminar después de empezar')

    await user.clear(hasta)
    await user.type(hasta, '18:00')
    await user.type(screen.getByLabelText(/vigente desde/i), '2026-11-10')
    await user.type(screen.getByLabelText(/vigente hasta/i), '2026-11-01')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('vigencia tiene que terminar')
    expect(llamadas).toEqual([])
  })

  it('al editar, recorta HH:MM:SS y trae días, vigencia y cancha', async () => {
    const user = userEvent.setup()
    const onGuardada = abrir(EXISTENTE)

    expect(screen.getByLabelText(/desde la hora/i)).toHaveValue('14:00')
    expect(screen.getByLabelText(/hasta la hora/i)).toHaveValue('17:00')
    expect(screen.getByLabelText(/vigente desde/i)).toHaveValue('2026-11-01')
    expect(screen.getByLabelText('Mar')).toBeChecked()
    expect(screen.getByLabelText('Lun')).not.toBeChecked()
    expect(screen.getByRole('combobox', { name: /cancha/i })).toHaveValue('Cancha 3')

    await user.click(screen.getByLabelText(/también en feriados/i))
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() => expect(onGuardada).toHaveBeenCalledTimes(1))
    const pedido = llamadas.find((l) => l.metodo === 'PUT')!
    expect(pedido.url).toBe('/api/promociones/7')
    expect(pedido.cuerpo).toMatchObject({
      dias_semana: [1, 2, 3], aplica_en_feriados: true, vigente_hasta: '2026-11-30',
    })
  })
})
