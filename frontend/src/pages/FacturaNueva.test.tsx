import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El alta manual de una factura.
 *
 * 🔴 **Lo que más importa acá es lo que NO se manda.** El motor resuelve
 * `client_id` contra la tabla `clients` de la base de **LibraCore**, y los
 * clientes de este producto viven en la base del dominio: son dos tablas con
 * ids que se pisan, y este producto además crea filas en la de LibraCore por
 * cuenta corriente. Mandar el id emitiría un comprobante fiscal correcto **a
 * nombre de otra persona**, y no fallaría.
 *
 * Por eso el selector copia nombre y CUIT, y el resto de este archivo verifica
 * que el cuerpo del pedido no lleve el id.
 */

const crear = vi.fn()
const tipos = vi.fn()
const listarClientes = vi.fn()
const navegar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    facturas: { tipos, crear },
    clientes: { listar: listarClientes },
  }
})

vi.mock('react-router-dom', async (original) => {
  const real = await original<Record<string, unknown>>()
  return { ...real, useNavigate: () => navegar }
})

const { FacturaNueva } = await import('./FacturaNueva')

const CLIENTE = {
  id: 7, nombre: 'Marcela Gutierrez', telefono: null, email: null,
  documento: '30111222', cuit: '27301112223', activo: true, observaciones: null,
}

beforeEach(() => {
  crear.mockReset().mockResolvedValue({ id: 42 })
  tipos.mockReset().mockResolvedValue({
    tipos: [{ value: 11, label: 'Factura C' }],
    conceptos: [{ value: 1, label: 'Productos' }],
    condiciones_venta: ['Contado', 'Cuenta Corriente'],
    punto_venta: 3,
    es_monotributista: true,
  })
  listarClientes.mockReset().mockResolvedValue([CLIENTE])
  navegar.mockReset()
})

function montar() {
  return render(<MemoryRouter><FacturaNueva /></MemoryRouter>)
}

async function completarUnItem() {
  await userEvent.type(screen.getByLabelText('Descripción del ítem 1'), 'Clase particular')
  await userEvent.clear(screen.getByLabelText('Precio unitario del ítem 1'))
  await userEvent.type(screen.getByLabelText('Precio unitario del ítem 1'), '9000')
}

describe('el cliente', () => {
  it('🔴 elegirlo copia sus datos y NO manda su id', async () => {
    montar()
    await waitFor(() => expect(listarClientes).toHaveBeenCalled())

    await userEvent.selectOptions(
      screen.getByLabelText('Elegir un cliente del complejo'),
      String(CLIENTE.id),
    )

    // Los datos se copiaron al formulario…
    expect(screen.getByLabelText('Se emite a nombre de')).toHaveValue('Marcela Gutierrez')
    expect(screen.getByLabelText('CUIT / DNI')).toHaveValue('27301112223')

    await completarUnItem()
    await userEvent.click(screen.getByRole('button', { name: 'Emitir' }))

    await waitFor(() => expect(crear).toHaveBeenCalled())
    const cuerpo = crear.mock.calls[0][0]
    // …y el id NO viaja. Éste es el assert que sostiene toda la pantalla.
    expect(cuerpo).not.toHaveProperty('client_id')
    expect(cuerpo.client_name).toBe('Marcela Gutierrez')
    expect(cuerpo.client_cuit).toBe('27301112223')
  })

  it('sin cliente elegido tampoco lo manda', async () => {
    // El control: si `client_id` no apareciera nunca por otro motivo, el test de
    // arriba pasaría sin probar la decisión.
    montar()
    await waitFor(() => expect(tipos).toHaveBeenCalled())

    await userEvent.type(screen.getByLabelText('Se emite a nombre de'), 'Quien sea')
    await completarUnItem()
    await userEvent.click(screen.getByRole('button', { name: 'Emitir' }))

    await waitFor(() => expect(crear).toHaveBeenCalled())
    expect(crear.mock.calls[0][0]).not.toHaveProperty('client_id')
  })
})

describe('lo que exige antes de emitir', () => {
  it('sin nombre no emite', async () => {
    montar()
    await waitFor(() => expect(tipos).toHaveBeenCalled())
    await completarUnItem()

    await userEvent.click(screen.getByRole('button', { name: 'Emitir' }))
    expect(await screen.findByText(/a nombre de quién/i)).toBeInTheDocument()
    expect(crear).not.toHaveBeenCalled()
  })

  it('sin ítems tampoco', async () => {
    montar()
    await waitFor(() => expect(tipos).toHaveBeenCalled())
    await userEvent.type(screen.getByLabelText('Se emite a nombre de'), 'Quien sea')

    await userEvent.click(screen.getByRole('button', { name: 'Emitir' }))
    expect(await screen.findByText(/al menos un ítem/i)).toBeInTheDocument()
    expect(crear).not.toHaveBeenCalled()
  })
})

describe('el tipo de comprobante', () => {
  it('sale del emisor, no de una constante', async () => {
    // Un monotributista emite C y nada más. Si la pantalla hardcodeara el tipo,
    // un complejo Responsable Inscripto emitiría el comprobante equivocado, que
    // es un problema fiscal y no de pantalla.
    tipos.mockResolvedValue({
      tipos: [{ value: 1, label: 'Factura A' }, { value: 6, label: 'Factura B' }],
      conceptos: [], condiciones_venta: ['Contado'], punto_venta: 9,
      es_monotributista: false,
    })
    montar()
    await waitFor(() => expect(tipos).toHaveBeenCalled())

    await userEvent.type(screen.getByLabelText('Se emite a nombre de'), 'Quien sea')
    await completarUnItem()
    await userEvent.click(screen.getByRole('button', { name: 'Emitir' }))

    await waitFor(() => expect(crear).toHaveBeenCalled())
    const cuerpo = crear.mock.calls[0][0]
    expect(cuerpo.tipo).toBe(1)
    // Y el punto de venta también sale de ahí, no de un 1 fijo.
    expect(cuerpo.punto_venta).toBe(9)
  })
})

describe('al emitir', () => {
  it('lleva al detalle del comprobante que salió', async () => {
    montar()
    await waitFor(() => expect(tipos).toHaveBeenCalled())
    await userEvent.type(screen.getByLabelText('Se emite a nombre de'), 'Quien sea')
    await completarUnItem()

    await userEvent.click(screen.getByRole('button', { name: 'Emitir' }))
    await waitFor(() => expect(navegar).toHaveBeenCalledWith('/facturas/42'))
  })
})
