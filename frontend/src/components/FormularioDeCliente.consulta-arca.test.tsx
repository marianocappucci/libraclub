/** El alta de un cliente trae «Consultar en ARCA» junto al CUIT y completa el nombre. */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FormularioDeCliente } from './FormularioDeCliente'

const fetchMock = vi.fn()
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock) })
afterEach(() => vi.unstubAllGlobals())

describe('formulario de cliente · Consultar en ARCA', () => {
  it('con el CUIT cargado, completa el nombre y el botón mide 44 px bajo lg', async () => {
    fetchMock.mockResolvedValue({
      ok: true, status: 200,
      json: () => Promise.resolve({ nombre: 'ACME SA', domicilio: 'Ruta 8', iva_condition: 'Monotributista', estado: 'ACTIVO' }),
    })
    render(<FormularioDeCliente abierto cliente={null} onCerrar={vi.fn()} onGuardado={vi.fn()} />)
    await userEvent.type(screen.getByRole('textbox', { name: /^cuit/i }), '30-71111111-4')
    const boton = screen.getByRole('button', { name: /Consultar en ARCA/ })
    expect(boton).toHaveClass('max-lg:h-11')
    await userEvent.click(boton)

    await waitFor(() => expect(screen.getByRole('textbox', { name: /^nombre/i })).toHaveValue('ACME SA'))
    expect(fetchMock).toHaveBeenCalledWith('/api/consultar-cuit/30711111114', { credentials: 'include' })
  })
})
