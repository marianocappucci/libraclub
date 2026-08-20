import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FormularioDeTarifa } from './FormularioDeTarifa'
import type { Cancha, Tarifa } from '@/lib/api'

const CANCHAS: Cancha[] = [
  {
    id: 3,
    sucursal_id: 1,
    nombre: 'Cancha 3',
    deporte: 'padel',
    duracion_turno_min: 90,
    techada: true,
    iluminacion: true,
    superficie: null,
    orden: 0,
    activa: true,
    observaciones: null,
  },
]

/** Una tarifa como la devuelve el backend: horas en `HH:MM:SS`. */
const EXISTENTE: Tarifa = {
  id: 12,
  sucursal_id: 1,
  cancha_id: null,
  nombre: 'Nocturna',
  alcance_dia: 'todos',
  dia_semana: null,
  hora_desde: '18:00:00',
  hora_hasta: '23:59:00',
  precio: '14000.00',
  sena_porcentaje: 50,
  vigente_desde: null,
  vigente_hasta: null,
  prioridad: 1,
  activa: true,
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

function abrir(tarifa: Tarifa | null) {
  const onGuardada = vi.fn()
  render(
    <FormularioDeTarifa
      abierto
      tarifa={tarifa}
      canchas={CANCHAS}
      sucursalId={1}
      onCerrar={vi.fn()}
      onGuardada={onGuardada}
    />,
  )
  return onGuardada
}

describe('formulario de tarifa', () => {
  it('el día sólo existe con alcance "un día de la semana"', async () => {
    abrir(null)
    // Con "Todos los días" no hay selector de día que llenar.
    expect(screen.queryByRole('combobox', { name: /^día$/i })).not.toBeInTheDocument()

    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /aplica/i }),
      'dia_semana',
    )
    expect(screen.getByRole('combobox', { name: /^día$/i })).toBeInTheDocument()
  })

  it('🔑 volver a "feriados" limpia el día, que es un estado que la base rechaza', async () => {
    const onGuardada = abrir(null)
    await userEvent.type(screen.getByRole('textbox', { name: /nombre/i }), 'Especial')
    await userEvent.type(screen.getByRole('textbox', { name: /precio/i }), '20000')

    // Se elige un día...
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /aplica/i }),
      'dia_semana',
    )
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /^día$/i }), '5')
    // ...y después se cambia de idea.
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /aplica/i }),
      'feriado',
    )

    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardada).toHaveBeenCalled())

    const cuerpo = llamadas.find((l) => l.metodo === 'POST')!.cuerpo
    // Si `dia_semana` quedara en 5, el CHECK de la base lo rechaza y el 422
    // habla de un campo que el operador ya no ve en pantalla.
    expect(cuerpo).toMatchObject({ alcance_dia: 'feriado', dia_semana: null })
  })

  it('al editar, recorta HH:MM:SS a HH:MM para el input de hora', async () => {
    abrir(EXISTENTE)
    // Sin recortar, un `<input type="time">` no acepta el valor y el campo
    // aparece vacío: el operador cree que la tarifa no tenía horario.
    expect(screen.getByLabelText(/desde/i)).toHaveValue('18:00')
    expect(screen.getByLabelText(/hasta/i)).toHaveValue('23:59')
  })

  it('🔑 al editar manda TODOS los campos, no sólo el que se tocó', async () => {
    const onGuardada = abrir(EXISTENTE)
    await userEvent.clear(screen.getByRole('textbox', { name: /nombre/i }))
    await userEvent.type(screen.getByRole('textbox', { name: /nombre/i }), 'Nocturna cara')
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardada).toHaveBeenCalled())

    const envio = llamadas.find((l) => l.metodo === 'PUT')!
    expect(envio.url).toBe('/api/tarifas/12')
    // El endpoint es un PUT que reemplaza la fila entera: lo que no viaje vuelve
    // al default del schema. Mandar sólo el nombre pondría la seña en 0 y la
    // prioridad en 0 sin que nadie las haya tocado.
    expect(envio.cuerpo).toMatchObject({
      nombre: 'Nocturna cara',
      sena_porcentaje: 50,
      prioridad: 1,
      precio: '14000.00',
      activa: true,
    })
  })

  it('rechaza una franja que termina antes de empezar, sin llamar a la API', async () => {
    abrir(null)
    await userEvent.type(screen.getByRole('textbox', { name: /nombre/i }), 'Al revés')
    await userEvent.type(screen.getByRole('textbox', { name: /precio/i }), '1000')
    await userEvent.clear(screen.getByLabelText(/hasta/i))
    await userEvent.type(screen.getByLabelText(/hasta/i), '06:00')

    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/terminar después de empezar/i)
    // El control: si igual hubiera llamado, el mensaje sería del backend y este
    // chequeo no estaría haciendo nada.
    expect(llamadas.filter((l) => l.metodo !== 'GET')).toHaveLength(0)
  })

  it('muestra cuánto sale la seña antes de guardar', async () => {
    abrir(EXISTENTE)
    expect(screen.getByText(/Seña:/)).toHaveTextContent('7.000')
  })
})
