/**
 * La cola de ARCA de un nodo (libra-ui ADR-094, libraclub ADR-023): la ruta `/cola`, su entrada de menú y lo que la pantalla le pone al
 * kit (quién resuelve y cómo se llama cada pedido).
 *
 * Se monta el ruteo entero (`Ruteo`, con su `Layout`) y no la pantalla sola: lo que importa es que **la ruta exista**, que el menú la
 * ofrezca **sólo en un nodo** y que el cartel «sin conexión» salga del mismo lugar.
 *
 * El cliente del kit (`libra-ui/api-client`) es el que usan el cartel, el menú y la bandeja; el de este producto (`lib/api.ts`) va por
 * `fetch`, y acá se lo deja contestar vacío.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const sesion = { id: '1', username: 'ana', name: 'Ana', role: 'admin', active: true }
let usuario = sesion

vi.mock('libra-ui/AuthContext', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    AuthProvider: ({ children }: { children: React.ReactNode }) => children,
    useAuth: () => ({ user: usuario, loading: false, login: vi.fn(), logout: vi.fn() }),
  }
})

vi.mock('@/context/SucursalContext', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    SucursalProvider: ({ children }: { children: React.ReactNode }) => children,
    useSucursal: () => ({ sucursales: [], actual: 1, elegir: () => {}, recargar: () => {}, cargando: false }),
  }
})

const get = vi.fn()
vi.mock('libra-ui/api-client', async (original) => {
  const real = await original<Record<string, unknown>>()
  return { ...real, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn() } }
})

const { Ruteo } = await import('../App')
const { _reiniciarConexionDelNodo } = await import('libra-ui/nodo-offline')

type Pedido = Record<string, unknown>

function pedido(extra: Pedido): Pedido {
  return {
    id: 1, origen_producto: 'libraclub', origen_instancia: 'nodo-1', origen_tipo: 'documento', origen_id: '41',
    estado: 'esperando', datos: {}, fecha_ref: '2026-10-24', concepto: 1, intentos: 0, ultimo_error: '', resultado: null,
    revision: 0, created_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:00:00Z', resuelto_at: '', ...extra,
  }
}

/** Lo que contesta `GET /api/nodo/cola`. */
let cola: Record<string, unknown>

beforeEach(() => {
  _reiniciarConexionDelNodo()
  usuario = sesion
  cola = { es_nodo: true, en_linea: false, node_id: 'nodo-1', cuentas: {}, a_revisar: 0, pedidos: [] }
  get.mockReset()
  get.mockImplementation((ruta: string) =>
    ruta.startsWith('/api/nodo/cola') ? Promise.resolve(cola) : Promise.reject(new Error(`ruta no esperada: ${ruta}`)))
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(
    new Response('null', { status: 200, headers: { 'content-type': 'application/json' } }))))
})

afterEach(() => _reiniciarConexionDelNodo())

function enLaRuta(ruta: string) {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <Ruteo />
    </MemoryRouter>,
  )
}

describe('la ruta /cola', () => {
  it('🔴 existe: muestra la cola con la factura pedida sin conexión, nombrada por su reserva', async () => {
    cola.pedidos = [pedido({ origen_id: '41' })]
    enLaRuta('/cola')

    expect(await screen.findByText('Factura · reserva #41')).toBeInTheDocument()
    // El título de la pantalla del kit (hay otro igual en el menú).
    expect(screen.getAllByText('Cola de comprobantes').length).toBeGreaterThanOrEqual(2)
  })

  it('🔴 una reserva dada en el nodo y todavía sin subir no muestra su id negativo como número', async () => {
    cola.pedidos = [pedido({ origen_id: '-48213' })]
    enLaRuta('/cola')

    expect(await screen.findByText('Factura · reserva sin número todavía')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/-48213/)
  })

  it('🔴 un admin puede resolver lo que quedó a revisar; el mostrador sólo lo mira', async () => {
    cola.pedidos = [pedido({ estado: 'a_revisar', ultimo_error: 'ARCA: CUIT inválido' })]
    const { unmount } = enLaRuta('/cola')
    expect(await screen.findByText(/ARCA: CUIT inválido/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Reintentar/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Descartar/ })).toBeInTheDocument()
    unmount()

    usuario = { ...sesion, role: 'staff' }
    enLaRuta('/cola')
    expect(await screen.findByText(/ARCA: CUIT inválido/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Reintentar/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Descartar/ })).toBeNull()
  })

  it('fuera de un nodo la pantalla lo dice y no rompe', async () => {
    cola = { es_nodo: false, en_linea: true, node_id: null, cuentas: {}, a_revisar: 0, pedidos: [] }
    enLaRuta('/cola')
    expect(await screen.findByText(/no es un nodo/i)).toBeInTheDocument()
  })
})

describe('el menú y el cartel', () => {
  it('🔴 en un nodo el menú ofrece la cola', async () => {
    enLaRuta('/cola')
    expect(await screen.findByRole('link', { name: 'Cola de comprobantes' })).toHaveAttribute('href', '/cola')
  })

  it('🔴 fuera de un nodo el menú queda como siempre: sin cola, sin cartel', async () => {
    cola = { es_nodo: false, en_linea: true, node_id: null, cuentas: {}, a_revisar: 0, pedidos: [] }
    enLaRuta('/cola')
    // Control positivo: el menú ya se dibujó (y la consulta ya contestó) antes de afirmar la ausencia.
    expect(await screen.findByRole('link', { name: 'Comprobantes' })).toBeInTheDocument()
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(screen.queryByRole('link', { name: 'Cola de comprobantes' })).toBeNull()
    expect(document.querySelector('[data-slot="cartel-sin-conexion"]')).toBeNull()
  })

  it('🔴 en un nodo sin conexión el cartel habla de la cola y de que no hay CPE para viajar', async () => {
    enLaRuta('/cola')
    const cartel = await waitFor(() => {
      const c = document.querySelector<HTMLElement>('[data-slot="cartel-sin-conexion"]')
      expect(c).not.toBeNull()
      return c as HTMLElement
    })
    expect(within(cartel).getByText(/quedan en cola y se emiten solas al volver/)).toBeInTheDocument()
    // No la frase de los productos que venden: ahí no se cobra con ticket.
    expect(within(cartel).queryByText(/ticket/)).toBeNull()
  })

  it('en un nodo con conexión no hay cartel, pero el menú sí ofrece la cola', async () => {
    cola.en_linea = true
    enLaRuta('/cola')
    expect(await screen.findByRole('link', { name: 'Cola de comprobantes' })).toBeInTheDocument()
    expect(document.querySelector('[data-slot="cartel-sin-conexion"]')).toBeNull()
  })

  it('el cartel consulta la cola de LibraClub y no la `/api/nodo/conexion`, que este producto no monta', async () => {
    enLaRuta('/cola')
    await waitFor(() => expect(get).toHaveBeenCalled())
    const rutas = get.mock.calls.map((c) => String(c[0]))
    expect(rutas.some((r) => r.startsWith('/api/nodo/cola'))).toBe(true)
    expect(rutas).not.toContain('/api/nodo/conexion')
  })
})
