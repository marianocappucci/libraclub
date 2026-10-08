import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El selector, probado **directo** y no a través del Layout.
 *
 * 🔴 Por qué directo: el Layout lo recibe por `userMenu`, y `libra-ui` mete ese
 * slot adentro del `DropdownMenuContent` de Radix, que **no se monta hasta que
 * el menú se abre**. Un test que lo busque con el menú cerrado no encuentra
 * nada — ni cuando el selector está bien ni cuando está mal. Se midió: con la
 * regla de "menos de dos sucursales" invertida a propósito, un assert de
 * ausencia hecho sobre el Layout seguía pasando en verde. Acá el componente se
 * monta solo, así que la ausencia significa lo que dice.
 */

const listar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return { ...real, sucursales: { ...(real.sucursales as object), listar } }
})

const { SucursalProvider } = await import('@/context/SucursalContext')
const { SelectorDeSucursal } = await import('./SelectorDeSucursal')
const { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } = await import('@/components/ui/dropdown-menu')

const base = {
  direccion: null, localidad: null, telefono: null, email: null,
  punto_venta_arca: null, activa: true, observaciones: null,
}
const CENTRO = { id: 1, nombre: 'Complejo Centro', ...base }
const NORTE = { id: 2, nombre: 'Complejo Norte', ...base }

function montar() {
  return render(
    <SucursalProvider>
      <SelectorDeSucursal />
    </SucursalProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  listar.mockReset()
})

describe('selector de sucursal', () => {
  it('con dos sucursales ofrece elegir, y muestra la activa', async () => {
    listar.mockResolvedValue([CENTRO, NORTE])
    montar()
    expect(await screen.findByLabelText('Sucursal')).toBeInTheDocument()
    // El contexto elige la primera activa cuando no hay nada guardado.
    expect(await screen.findByLabelText('Sucursal')).toHaveValue('Complejo Centro')
  })

  it('🔴 adentro del menú del usuario, escribir busca y NO le roba el foco a los ítems del menú', async () => {
    // El selector vive en un `DropdownMenuContent` de Radix, que busca por letras entre sus ítems: la primera «C» de «Complejo Norte» mandaba
    // el foco a «Cambiar contraseña» y el campo perdía lo escrito. Se prueba con el menú REAL de Radix, no con el Layout (que no lo monta cerrado).
    listar.mockResolvedValue([CENTRO, NORTE])
    const user = userEvent.setup()
    render(
      <SucursalProvider>
        <DropdownMenu>
          <DropdownMenuTrigger>Cuenta</DropdownMenuTrigger>
          <DropdownMenuContent>
            <SelectorDeSucursal />
            <DropdownMenuItem>Cambiar contraseña</DropdownMenuItem>
            <DropdownMenuItem>Cerrar sesión</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SucursalProvider>,
    )
    await user.click(screen.getByText('Cuenta'))
    const campo = await screen.findByRole('combobox', { name: 'Sucursal' })
    await user.click(campo)
    await user.keyboard('Complejo N')

    expect(campo).toHaveFocus()
    expect(campo).toHaveValue('Complejo N')
    await user.click(await screen.findByRole('option', { name: 'Complejo Norte' }))
    expect(campo).toHaveValue('Complejo Norte')
  })

  it('🔑 con una sola sucursal no se dibuja: no hay nada que decidir', async () => {
    listar.mockResolvedValue([CENTRO])
    montar()
    // Se espera a que la lista haya CARGADO antes de afirmar la ausencia. Sin
    // esta espera el assert pasaría por llegar antes que los datos, que es un
    // verde que no depende de la regla que se quiere probar.
    await waitFor(() => expect(listar).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByLabelText('Sucursal')).not.toBeInTheDocument())
  })

  it('sin ninguna sucursal tampoco se dibuja', async () => {
    listar.mockResolvedValue([])
    montar()
    await waitFor(() => expect(listar).toHaveBeenCalled())
    expect(screen.queryByLabelText('Sucursal')).not.toBeInTheDocument()
  })
})
