/**
 * La pantalla para elegir cuál cambio queda en un cliente (ADR-022, tercer addendum).
 *
 * Lo que se mide: que muestre los dos valores de cada dato que choca (la web y la PC) con el anterior de referencia, que
 * los datos que no chocaban figuren como «se aplican», que no se pueda guardar sin elegir todos, que lo que se manda sea
 * la elección por campo MÁS lo que la pantalla vio de la web (el control contra pisar un cambio nuevo), y que un 409 avise
 * y recargue con lo de ahora.
 *
 * Cuarto addendum: si el dato de la web volvió al valor anterior y ya no choca, el detalle muestra lo que se aplica y lo que
 * ya está igual, y ofrece «Aplicar cambios de la PC» y «Descartar» (con confirmación); si entre tanto volvió a chocar, el
 * servidor contesta 409 y la pantalla recarga mostrando la elección por campo.
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
  ya_no_choca: false,
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

// La web volvió el teléfono al valor anterior (111): ya no choca, los dos datos se aplican y uno ya estaba igual.
const YA_NO_CHOCA = {
  ...EDICION,
  en_conflicto: 0,
  ya_no_choca: true,
  campos: [
    { campo: 'telefono', etiqueta: 'Teléfono', estado: 'se_aplica', antes: '111', web: '111', pc: '333' },
    { campo: 'documento', etiqueta: 'Documento', estado: 'se_aplica', antes: null, web: null, pc: '30123456' },
    { campo: 'acepta_avisos', etiqueta: 'Acepta avisos', estado: 'igual', antes: true, web: false, pc: false },
  ],
}

function montar(
  respuestas: { ver?: () => Promise<Response>; resolver?: () => Promise<Response>; descartar?: () => Promise<Response> } = {},
) {
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    llamadas.push({ url: String(url), init })
    if (init?.method === 'POST' && String(url).endsWith('/descartar')) {
      return (respuestas.descartar ?? (() => json({ descartada: true })))()
    }
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
})

describe('un cambio que ya no choca (ADR-022, cuarto addendum)', () => {
  it('muestra lo que se va a aplicar y lo que ya está igual, sin pedir que se elija nada', async () => {
    montar({ ver: () => json(YA_NO_CHOCA) })

    expect(await screen.findByText(/Ya no choca\./)).toBeInTheDocument()
    const seAplican = screen.getByText('Se aplican').closest('section')!
    expect(seAplican).toHaveTextContent('Teléfono: 111 → 333')
    expect(seAplican).toHaveTextContent('Documento: (vacío) → 30123456')
    expect(screen.getByText(/Ya están así en la web: Acepta avisos/)).toBeInTheDocument()
    expect(screen.queryAllByRole('radio')).toHaveLength(0)
    expect(screen.queryByRole('button', { name: 'Guardar elección' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Aplicar cambios de la PC' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Descartar' })).toBeEnabled()
  })

  it('«Aplicar cambios de la PC» manda las elecciones vacías y lo que vio de la web, y vuelve a la lista', async () => {
    const usuario = userEvent.setup()
    montar({ ver: () => json(YA_NO_CHOCA) })
    await usuario.click(await screen.findByRole('button', { name: 'Aplicar cambios de la PC' }))

    expect(await screen.findByText('la lista')).toBeInTheDocument()
    const envio = llamadas.find((l) => l.init?.method === 'POST')!
    expect(envio.url).toBe('/api/clientes-en-conflicto/club-1%3A2/resolver')
    expect(JSON.parse(String(envio.init!.body))).toEqual({
      elecciones: {},
      vistos: { telefono: '111', documento: null, acepta_avisos: false },
    })
  })

  it('«Descartar» pide confirmación y, si se cancela, no manda nada', async () => {
    const usuario = userEvent.setup()
    montar({ ver: () => json(YA_NO_CHOCA) })
    await usuario.click(await screen.findByRole('button', { name: 'Descartar' }))

    const dialogo = await screen.findByRole('alertdialog')
    expect(dialogo).toHaveTextContent('Juan Pérez')
    expect(dialogo).toHaveTextContent('No se puede deshacer')
    await usuario.click(within(dialogo).getByRole('button', { name: 'Cancelar' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(llamadas.some((l) => l.init?.method === 'POST')).toBe(false)
    expect(screen.queryByText('la lista')).toBeNull()
  })

  it('confirmar el descarte lo manda con lo que vio de la web y vuelve a la lista', async () => {
    const usuario = userEvent.setup()
    montar({ ver: () => json(YA_NO_CHOCA) })
    await usuario.click(await screen.findByRole('button', { name: 'Descartar' }))
    await usuario.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Descartar' }))

    expect(await screen.findByText('la lista')).toBeInTheDocument()
    const envio = llamadas.find((l) => l.init?.method === 'POST')!
    expect(envio.url).toBe('/api/clientes-en-conflicto/club-1%3A2/descartar')
    expect(JSON.parse(String(envio.init!.body))).toEqual({
      vistos: { telefono: '111', documento: null, acepta_avisos: false },
    })
  })

  it.each([
    ['aplicar', async (usuario: ReturnType<typeof userEvent.setup>) => {
      await usuario.click(await screen.findByRole('button', { name: 'Aplicar cambios de la PC' }))
    }],
    ['descartar', async (usuario: ReturnType<typeof userEvent.setup>) => {
      await usuario.click(await screen.findByRole('button', { name: 'Descartar' }))
      await usuario.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Descartar' }))
    }],
  ])('si volvió a chocar mientras tanto, al %s avisa y recarga mostrando la elección por campo', async (_, accion) => {
    const usuario = userEvent.setup()
    let version = 0
    const aviso = { detail: { codigo: 'cambio_en_la_web', mensaje: 'Mientras tanto se cambió este cliente en la web (Teléfono).' } }
    montar({
      ver: () => {
        version += 1
        // Al recargar, el teléfono de la web ya es otro: ahora sí choca.
        return json(version === 1 ? YA_NO_CHOCA : {
          ...YA_NO_CHOCA,
          en_conflicto: 1,
          ya_no_choca: false,
          campos: YA_NO_CHOCA.campos.map((c) => (c.campo === 'telefono' ? { ...c, estado: 'conflicto', web: '999' } : c)),
        })
      },
      resolver: () => json(aviso, 409),
      descartar: () => json(aviso, 409),
    })
    await accion(usuario)

    expect(await screen.findByRole('alert')).toHaveTextContent('Mientras tanto se cambió este cliente en la web')
    const telefono = (await screen.findByText('Teléfono', { selector: 'legend' })).closest('fieldset')!
    expect(within(telefono).getByText('Lo que está en la web').parentElement).toHaveTextContent('999')
    expect(screen.getByRole('button', { name: 'Guardar elección' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Aplicar cambios de la PC' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Descartar' })).toBeNull()
    expect(screen.queryByText('la lista')).toBeNull()
  })

  it('si ya está todo igual en la web, lo dice y aplicar la da por resuelta', async () => {
    const usuario = userEvent.setup()
    montar({ ver: () => json({ ...YA_NO_CHOCA, campos: YA_NO_CHOCA.campos.map((c) => ({ ...c, estado: 'igual' })) }) })
    expect(await screen.findByText(/No hay nada para cambiar/)).toBeInTheDocument()
    expect(screen.queryByText('Se aplican')).toBeNull()
    await usuario.click(screen.getByRole('button', { name: 'Aplicar cambios de la PC' }))
    expect(await screen.findByText('la lista')).toBeInTheDocument()
  })

  it('una que choca no ofrece descartar', async () => {
    montar()
    await screen.findByRole('button', { name: 'Guardar elección' })
    expect(screen.queryByRole('button', { name: 'Descartar' })).toBeNull()
  })

  it('no habla en jerga', async () => {
    montar({ ver: () => json(YA_NO_CHOCA) })
    await screen.findByRole('button', { name: 'Aplicar cambios de la PC' })
    expect(document.body.textContent).not.toMatch(/nodo|outbox|central|sincroniz/i)
  })
})
