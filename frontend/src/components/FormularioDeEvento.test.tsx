import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Cancha, Evento } from '@/lib/api'
import { FormularioDeEvento } from './FormularioDeEvento'

let llamadas: { url: string; metodo: string; cuerpo: Record<string, unknown> }[]

beforeEach(() => {
  llamadas = []
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    llamadas.push({
      url,
      metodo: init?.method ?? 'GET',
      cuerpo: init?.body ? JSON.parse(String(init.body)) : {},
    })
    return { ok: true, status: 200, json: async () => ({ id: 3 }) } as Response
  })
})

afterEach(() => vi.unstubAllGlobals())

const cancha = (id: number, nombre: string): Cancha => ({
  id, sucursal_id: 1, nombre, deporte: 'padel', duracion_turno_min: 90, techada: false,
  iluminacion: true, superficie: null, orden: id, activa: true, observaciones: null,
})
const CANCHAS = [cancha(7, 'Cancha 1'), cancha(8, 'Cancha 2')]

const EXISTENTE: Evento = {
  id: 3, sucursal_id: 1, nombre: 'Americano de primavera', desde: '2026-10-10',
  hasta: '2026-10-11', observaciones: null, cancha_ids: [8],
}

describe('formulario de evento', () => {
  it('crea con la sucursal, las fechas y las canchas tildadas', async () => {
    const onGuardado = vi.fn()
    render(
      <FormularioDeEvento
        abierto sucursalId={1} canchas={CANCHAS} onCerrar={vi.fn()} onGuardado={onGuardado}
      />,
    )
    await userEvent.type(screen.getByLabelText('Nombre'), 'Americano de otoño')
    await userEvent.click(screen.getByLabelText('Cancha 1'))
    await userEvent.click(screen.getByRole('button', { name: 'Crear evento' }))
    await waitFor(() => expect(onGuardado).toHaveBeenCalled())

    const { url, metodo, cuerpo } = llamadas.find((l) => l.metodo === 'POST')!
    expect(url).toBe('/api/eventos')
    expect(metodo).toBe('POST')
    expect(cuerpo.sucursal_id).toBe(1)
    expect(cuerpo.nombre).toBe('Americano de otoño')
    expect(cuerpo.cancha_ids).toEqual([7])
    expect(cuerpo.hasta).toBeNull()
  })

  it('sin canchas tildadas manda la lista vacía: vale cualquiera', async () => {
    const onGuardado = vi.fn()
    render(
      <FormularioDeEvento
        abierto sucursalId={1} canchas={CANCHAS} onCerrar={vi.fn()} onGuardado={onGuardado}
      />,
    )
    await userEvent.type(screen.getByLabelText('Nombre'), 'Libre')
    await userEvent.click(screen.getByRole('button', { name: 'Crear evento' }))
    await waitFor(() => expect(onGuardado).toHaveBeenCalled())
    expect(llamadas.find((l) => l.metodo === 'POST')!.cuerpo.cancha_ids).toEqual([])
  })

  it('edita con PUT, sin mandar la sucursal, y destilda una cancha', async () => {
    const onGuardado = vi.fn()
    render(
      <FormularioDeEvento
        abierto sucursalId={1} canchas={CANCHAS} evento={EXISTENTE}
        onCerrar={vi.fn()} onGuardado={onGuardado}
      />,
    )
    expect(screen.getByLabelText('Cancha 2')).toBeChecked()
    await userEvent.click(screen.getByLabelText('Cancha 2'))
    await userEvent.click(screen.getByLabelText('Cancha 1'))
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onGuardado).toHaveBeenCalled())

    const { url, cuerpo } = llamadas.find((l) => l.metodo === 'PUT')!
    expect(url).toBe('/api/eventos/3')
    expect(cuerpo.cancha_ids).toEqual([7])
    expect(cuerpo).not.toHaveProperty('sucursal_id')
    expect(cuerpo.hasta).toBe('2026-10-11')
  })

  it('muestra el error del servidor y no se cierra', async () => {
    vi.stubGlobal('fetch', async () => ({
      ok: false, status: 409, json: async () => ({ detail: 'Ya hay un evento con ese nombre en la sucursal.' }),
    }) as Response)
    const onGuardado = vi.fn()
    render(
      <FormularioDeEvento
        abierto sucursalId={1} canchas={CANCHAS} onCerrar={vi.fn()} onGuardado={onGuardado}
      />,
    )
    await userEvent.type(screen.getByLabelText('Nombre'), 'Repetido')
    await userEvent.click(screen.getByRole('button', { name: 'Crear evento' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Ya hay un evento/)
    expect(onGuardado).not.toHaveBeenCalled()
  })
})
