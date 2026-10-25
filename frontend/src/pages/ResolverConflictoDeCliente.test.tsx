/**
 * La pantalla para elegir cuál cambio queda en un cliente (ADR-022, tercer addendum).
 *
 * Lo que se mide: que muestre los dos valores de cada dato que choca (la web y la PC) con el anterior de referencia, que
 * los datos que no chocaban figuren como «se aplican», que no se pueda guardar sin elegir todos, que lo que se manda sea
 * la elección por campo MÁS lo que la pantalla vio de la web (el control contra pisar un cambio nuevo), y que un 409 avise
 * y recargue con lo de ahora.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ResolverConflictoDeCliente } from './ResolverConflictoDeCliente'

const EDICION = {
  operacion_id: 'club-1:2',
  cliente_id: 7,
  cliente_nombre: 'Juan Pérez',
  recibida_at: '2026-09-02T10:00:00-03:00',
  en_conflicto: 2,
  se_puede_resolver: true,
  campos: [
    { campo: 'telefono', etiqueta: 'Teléfono', estado: 'conflicto', antes: '111', web: '222', pc: '333' },
    { campo: 'email', etiqueta: 'Email', estado: 'conflicto', antes: 'a@x.com', web: null, pc: 'pc@x.com' },
    { campo: 'documento', etiqueta: 'Documento', estado: 'se_aplica', antes: null, web: null, pc: '30123456' },
    { campo: 'acepta_avisos', etiqueta: 'Acepta avisos', estado: 'igual', antes: true, web: false, pc: false },
  ],
}

function json(cuerpo: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(cuerpo), {
    status, headers: { 'content-type': 'application/json' },
  }))
}

let llamadas: { url: string; init?: RequestInit }[]

function montar(respuestas: { ver?: () => Promise<Response>; resolver?: () => Promise<Response> } = {}) {
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    llamadas.push({ url: String(url), init })
    if (init?.method === 'POST') return (respuestas.resolver ?? (() => json({ aplicados: ['telefono'] })))()
    if (String(url).startsWith('/api/clientes-en-conflicto/')) return (respuestas.ver ?? (() => json(EDICION)))()
    return json([])
  }))
  return render(
    <MemoryRouter initialEntries={['/clientes/conflictos/club-1%3A2']}>
      <Routes>
        <Route path="/clientes/conflictos" element={<p>la lista</p>} />
        <Route path="/clientes/conflictos/:operacionId" element={<ResolverConflictoDeCliente />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  llamadas = []
})

describe('elegir cuál cambio queda', () => {
  it('muestra, por cada dato que choca, lo de la web y lo de la PC lado a lado, con el valor anterior', async () => {
    montar()
    const telefono = (await screen.findByText('Teléfono')).closest('fieldset')!
    expect(within(telefono).getByText('Antes: 111')).toBeInTheDocument()
    expect(within(telefono).getByText('Lo que está en la web').parentElement).toHaveTextContent('222')
    expect(within(telefono).getByText('Lo que se cargó en la PC').parentElement).toHaveTextContent('333')

    // Un dato vacío en la web se lee «(vacío)», no un hueco.
    const email = screen.getByText('Email').closest('fieldset')!
    expect(within(email).getByText('Lo que está en la web').parentElement).toHaveTextContent('(vacío)')
    expect(within(email).getByText('Lo que se cargó en la PC').parentElement).toHaveTextContent('pc@x.com')
  })

  it('lo que no chocaba figura como «se aplican», y no pide elegir', async () => {
    montar()
    const seAplican = (await screen.findByText('Se aplican')).closest('section')!
    expect(seAplican).toHaveTextContent('Documento: (vacío) → 30123456')
    expect(screen.queryByText('Documento', { selector: 'legend' })).toBeNull()
    // El que ya estaba igual se nombra aparte.
    expect(screen.getByText(/Ya están así en la web: Acepta avisos/)).toBeInTheDocument()
  })

  it('no se puede guardar hasta elegir en todos, y dice en cuáles falta', async () => {
    const usuario = userEvent.setup()
    montar()
    const guardar = await screen.findByRole('button', { name: 'Guardar elección' })
    expect(guardar).toBeDisabled()
    expect(screen.getByText('Falta elegir en: Teléfono, Email.')).toBeInTheDocument()

    const telefono = screen.getByText('Teléfono').closest('fieldset')!
    await usuario.click(within(telefono).getByRole('radio', { name: /Lo que se cargó en la PC/ }))
    expect(guardar).toBeDisabled()
    expect(screen.getByText('Falta elegir en: Email.')).toBeInTheDocument()

    const email = screen.getByText('Email').closest('fieldset')!
    await usuario.click(within(email).getByRole('radio', { name: /Lo que está en la web/ }))
    expect(guardar).toBeEnabled()
  })

  it('guarda una elección mixta con lo que vio de la web y vuelve a la lista', async () => {
    const usuario = userEvent.setup()
    montar()
    const telefono = (await screen.findByText('Teléfono')).closest('fieldset')!
    await usuario.click(within(telefono).getByRole('radio', { name: /Lo que se cargó en la PC/ }))
    const email = screen.getByText('Email').closest('fieldset')!
    await usuario.click(within(email).getByRole('radio', { name: /Lo que está en la web/ }))
    await usuario.click(screen.getByRole('button', { name: 'Guardar elección' }))

    expect(await screen.findByText('la lista')).toBeInTheDocument()
    const envio = llamadas.find((l) => l.init?.method === 'POST')!
    expect(envio.url).toBe('/api/clientes-en-conflicto/club-1%3A2/resolver')
    expect(JSON.parse(String(envio.init!.body))).toEqual({
      elecciones: { telefono: 'pc', email: 'web' },
      // Lo que la pantalla vio de la web en TODOS los campos: es el control contra pisar un cambio nuevo.
      vistos: { telefono: '222', email: null, documento: null, acepta_avisos: false },
    })
  })

  it('si el cliente cambió otra vez en la web: avisa, recarga con lo de ahora y deja volver a elegir', async () => {
    const usuario = userEvent.setup()
    let version = 0
    montar({
      ver: () => {
        version += 1
        return json(version === 1
          ? EDICION
          : { ...EDICION, campos: EDICION.campos.map((c) => (c.campo === 'telefono' ? { ...c, web: '444' } : c)) })
      },
      resolver: () => json({ detail: { codigo: 'cambio_en_la_web', mensaje: 'Mientras tanto se cambió este cliente en la web (Teléfono).' } }, 409),
    })
    const telefono = (await screen.findByText('Teléfono')).closest('fieldset')!
    await usuario.click(within(telefono).getByRole('radio', { name: /Lo que se cargó en la PC/ }))
    await usuario.click(within(screen.getByText('Email').closest('fieldset')!).getByRole('radio', { name: /Lo que está en la web/ }))
    await usuario.click(screen.getByRole('button', { name: 'Guardar elección' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Mientras tanto se cambió este cliente en la web')
    // Recargó: muestra el 444 y las elecciones se limpiaron (no se guarda sobre lo viejo).
    await waitFor(() => {
      const t = screen.getByText('Teléfono').closest('fieldset')!
      expect(within(t).getByText('Lo que está en la web').parentElement).toHaveTextContent('444')
    })
    expect(screen.getByRole('button', { name: 'Guardar elección' })).toBeDisabled()
    expect(screen.queryByText('la lista')).toBeNull()
  })

  it('si ya la resolvió otra persona, vuelve a la lista', async () => {
    montar({ ver: () => json({ detail: { codigo: 'ya_resuelta', mensaje: 'Esta edición ya se resolvió.' } }, 409) })
    expect(await screen.findByText('la lista')).toBeInTheDocument()
  })

  it('sin datos que choquen, guardar aplica lo que falta', async () => {
    const usuario = userEvent.setup()
    montar({ ver: () => json({ ...EDICION, en_conflicto: 0, campos: [EDICION.campos[2]] }) })
    expect(await screen.findByText(/Ya no hay datos que choquen/)).toBeInTheDocument()
    const guardar = screen.getByRole('button', { name: 'Guardar elección' })
    expect(guardar).toBeEnabled()
    await usuario.click(guardar)
    expect(await screen.findByText('la lista')).toBeInTheDocument()
    expect(JSON.parse(String(llamadas.find((l) => l.init?.method === 'POST')!.init!.body)).elecciones).toEqual({})
  })
})
