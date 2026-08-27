import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * La pantalla de comprobantes.
 *
 * La tabla la dibuja `libra-ui` y la prueba el kit. Lo que se fija acá es lo que
 * decide este producto:
 *
 * - que la consulta salga al **buscar** y no en cada tecla;
 * - que el link del PDF apunte al comprobante de esa fila;
 * - que una factura **sin CAE** no se muestre como un error;
 * - que el listado vacío diga dónde se factura, que no es acá.
 */

const facturasListar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    // `facturacion` queda REAL a propósito: `urlDelPdf` es justo lo que el test
    // del link tiene que medir. Mockearlo probaría el mock.
    facturas: { listar: facturasListar },
  }
})

const { Facturas } = await import('./Facturas')

const AUTORIZADA = {
  id: 42, tipo: 11, punto_venta: 3, numero: 7, fecha: '2026-08-27',
  cliente_razon: 'Ana Perez', cliente_cuit: '', total: 14000,
  cae: '75123456789012', cae_vto: '2026-09-06',
}
const SIN_CAE = {
  ...AUTORIZADA, id: 43, numero: 8, cliente_razon: '', cae: '', cae_vto: '',
}

function pagina(items: object[]) {
  return { items, total: items.length, total_pages: 1, page: 1 }
}

beforeEach(() => {
  facturasListar.mockReset()
  facturasListar.mockResolvedValue(pagina([AUTORIZADA, SIN_CAE]))
})

describe('el listado de comprobantes', () => {
  it('no consulta en cada tecla: la búsqueda sale al apretar Buscar', async () => {
    render(<Facturas />)
    await waitFor(() => expect(facturasListar).toHaveBeenCalledTimes(1))

    await userEvent.type(screen.getByLabelText('Buscar comprobantes'), 'Perez')
    // Cinco teclas y ninguna consulta nueva: con `q` disparando el efecto, esto
    // serían cinco requests y la lista saltando abajo del dedo.
    expect(facturasListar).toHaveBeenCalledTimes(1)

    await userEvent.click(screen.getByLabelText('Buscar'))
    await waitFor(() => expect(facturasListar).toHaveBeenCalledTimes(2))
    expect(facturasListar).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: 'Perez', page: 1 }),
    )
  })

  it('el link del PDF apunta al comprobante de esa fila', async () => {
    render(<Facturas />)
    const link = await screen.findByLabelText('Ver el PDF del comprobante 0003-00000007')
    // La URL real del cliente API, no una armada en el test: si el prefijo del
    // router cambiara, esto tiene que romperse.
    expect(link).toHaveAttribute('href', '/api/facturas/42/pdf')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('una factura sin CAE está pendiente, no fallada', async () => {
    render(<Facturas />)
    // 🔑 La factura existe y tiene número; lo que falta es que ARCA la
    // autorice, y sin certificado cargado eso pasa siempre. Mostrarlo en rojo
    // mandaría a buscar un problema que no está.
    const pendiente = await screen.findByText('Pendiente de CAE')
    expect(pendiente.dataset.tono).toBe('atencion')
    expect(screen.getByText('Autorizada').dataset.tono).toBe('ok')
  })

  it('sin comprobantes dice dónde se factura', async () => {
    facturasListar.mockResolvedValue(pagina([]))
    render(<Facturas />)
    // No alcanza con "no hay nada": el alta no está en esta pantalla, así que
    // el vacío tiene que decir adónde ir.
    expect(await screen.findByText(/se facturan desde el turno/i)).toBeInTheDocument()
  })

  it('un comprobante sin cliente se muestra como Consumidor Final', async () => {
    render(<Facturas />)
    // Un complejo factura a mostrador todo el tiempo: la fila sin nombre es el
    // caso normal, no un dato faltante.
    expect(await screen.findByText('Consumidor Final')).toBeInTheDocument()
  })
})
