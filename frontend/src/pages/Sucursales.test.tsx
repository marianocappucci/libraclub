/**
 * La pantalla de sucursales, que se nombra por lo que hay.
 *
 * Decidido con el humano el 2026-08-28. La pregunta que lo abrió fue suya:
 * *"desde esta instancia (cuando sea una instancia comercial) cada instancia va
 * a ser una sucursal (¿o no?)"*. La respuesta es **casi**: con una instancia por
 * complejo la tabla tiene **una fila**, y esa fila sigue haciendo falta —ahí
 * viven el nombre, la dirección y **el punto de venta de ARCA**—. Lo que sobra
 * no es la entidad: es ofrecer «Nueva sucursal» sin decir qué implica.
 *
 * 🔴 **Lo que se protege es el accidente.** Dos sucursales en una instancia
 * **no** están aisladas: comparten clientes, usuarios y stock. Crear la segunda
 * creyendo que se separan dos negocios es el error caro, y es silencioso hasta
 * que alguien mira la cuenta corriente de un cliente que no es suyo.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Sucursales } from './Sucursales'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', name: 'Ana', role: 'admin' }, loading: false }),
}))
vi.mock('@/context/SucursalContext', () => ({
  useSucursal: () => ({ actual: 1, sucursales: [], elegir: vi.fn(), recargar: vi.fn(), cargando: false }),
}))

function sucursal(id: number, nombre: string) {
  return {
    id, nombre, direccion: null, localidad: 'Suipacha', telefono: null,
    email: null, punto_venta_arca: id, activa: true, observaciones: null,
  }
}

const estado = { filas: [sucursal(1, 'Complejo Centro')] }

beforeEach(() => {
  estado.filas = [sucursal(1, 'Complejo Centro')]
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(
    JSON.stringify(estado.filas),
    { status: 200, headers: { 'content-type': 'application/json' } },
  ))))
})

describe('cómo se llama la pantalla', () => {
  it('🔑 con una sola dice «Mi complejo»', async () => {
    render(<Sucursales />)
    expect(await screen.findByText('Mi complejo')).toBeInTheDocument()
    expect(screen.queryByText('Sucursales')).not.toBeInTheDocument()
  })

  it('🔑 con dos vuelve a «Sucursales», sola', async () => {
    // El control del de arriba: sin esto, un título hardcodeado en «Mi
    // complejo» pasaría igual.
    estado.filas = [sucursal(1, 'Complejo Centro'), sucursal(2, 'Complejo Norte')]
    render(<Sucursales />)
    expect(await screen.findByText('Sucursales')).toBeInTheDocument()
    expect(screen.queryByText('Mi complejo')).not.toBeInTheDocument()
  })
})

describe('agregar la segunda sucursal', () => {
  it('🔴 con una sola, el botón AVISA antes de abrir el formulario', async () => {
    const user = userEvent.setup()
    render(<Sucursales />)
    await user.click(await screen.findByRole('button', { name: /Agregar otra sucursal/ }))

    // El aviso, no el formulario.
    expect(await screen.findByText(/Agregar una segunda sucursal/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/Nombre/)).not.toBeInTheDocument()
  })

  it('🔴 y dice las DOS listas: qué separa y qué comparte', async () => {
    // Un aviso que sólo enumera riesgos se lee como «no lo hagas» y se saltea.
    // Lo que hace falta es que se entienda el modelo — porque compartir
    // personal y stock entre dos complejos del mismo dueño es a propósito.
    const user = userEvent.setup()
    render(<Sucursales />)
    await user.click(await screen.findByRole('button', { name: /Agregar otra sucursal/ }))

    expect(await screen.findByText(/su punto de venta de ARCA/i)).toBeInTheDocument()
    expect(screen.getByText(/los clientes y su cuenta corriente/i)).toBeInTheDocument()
    expect(screen.getByText(/No hay aislamiento entre las dos/i)).toBeInTheDocument()
  })

  it('🔴 confirmando SÍ se abre el formulario', async () => {
    const user = userEvent.setup()
    render(<Sucursales />)
    await user.click(await screen.findByRole('button', { name: /Agregar otra sucursal/ }))
    await user.click(await screen.findByRole('button', { name: /Entendido, agregarla/ }))
    await waitFor(() => expect(screen.getByLabelText(/Nombre/)).toBeInTheDocument())
  })

  it('🔑 cancelando no se abre nada', async () => {
    const user = userEvent.setup()
    render(<Sucursales />)
    await user.click(await screen.findByRole('button', { name: /Agregar otra sucursal/ }))
    await user.click(await screen.findByRole('button', { name: /^Cancelar$/ }))
    await waitFor(() =>
      expect(screen.queryByText(/Agregar una segunda sucursal/)).not.toBeInTheDocument(),
    )
    expect(screen.queryByLabelText(/Nombre/)).not.toBeInTheDocument()
  })

  it('🔴 con DOS o más el aviso no molesta: va directo al formulario', async () => {
    // El aviso es sobre pasar de una a dos, que es donde cambia el modelo
    // mental. Repetirlo en cada alta posterior lo convierte en un click que
    // nadie lee — y entonces deja de proteger la vez que importa.
    estado.filas = [sucursal(1, 'Complejo Centro'), sucursal(2, 'Complejo Norte')]
    const user = userEvent.setup()
    render(<Sucursales />)
    await user.click(await screen.findByRole('button', { name: /Nueva sucursal/ }))
    await waitFor(() => expect(screen.getByLabelText(/Nombre/)).toBeInTheDocument())
    expect(screen.queryByText(/Agregar una segunda sucursal/)).not.toBeInTheDocument()
  })

  it('🔴 y sin ninguna tampoco: ahí crear es obligatorio', async () => {
    // Sin una sucursal la agenda no tiene dónde vivir. Frenar la primera con un
    // cartel sería estorbar en el único momento en que no hay alternativa.
    estado.filas = []
    const user = userEvent.setup()
    render(<Sucursales />)
    await user.click(await screen.findByRole('button', { name: /Agregar otra sucursal/ }))
    await waitFor(() => expect(screen.getByLabelText(/Nombre/)).toBeInTheDocument())
    expect(screen.queryByText(/Agregar una segunda sucursal/)).not.toBeInTheDocument()
  })
})
