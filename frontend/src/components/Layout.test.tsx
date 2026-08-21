import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El cascarón de la familia, del lado del consumidor.
 *
 * Lo que dibuja el sidebar es `libra-ui/Layout` y lo prueba el kit; lo que este
 * test fija es **lo que LibraClub le pasa**: qué ítems tiene el menú, cuál es
 * de admin, y que la sucursal activa quede a la vista.
 *
 * 🔴 Ese último es el que importa más de lo que parece. Al adoptar el kit, el
 * selector de sucursal se fue del encabezado al menú del usuario, que está
 * cerrado; y en LibraClub la sucursal **filtra la agenda, las canchas y las
 * tarifas**. Si el subtítulo dejara de dibujarse, una pantalla filtrada se vería
 * idéntica a una completa y nada fallaría. Por eso se asierta el nombre de la
 * sucursal, y no sólo que el Layout renderice.
 *
 * Vale además como canario del kit, igual que `Usuarios.test.tsx`: si un tag
 * nuevo de `libra-ui` cambia la API de `createLayout`, se cae acá, en el repo
 * del consumidor.
 */

const get = vi.fn()

// Se mockea `libra-ui/api-client` —y no `fetch`— porque es por ahí que pide el
// `AuthProvider` del kit. Mismo criterio que en `Usuarios.test.tsx`.
vi.mock('libra-ui/api-client', async (original) => {
  const real = await original<Record<string, unknown>>()
  return { ...real, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn() } }
})

const listar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return { ...real, sucursales: { ...(real.sucursales as object), listar } }
})

const { AuthProvider } = await import('libra-ui/AuthContext')
const { SucursalProvider } = await import('@/context/SucursalContext')
const { Layout } = await import('./Layout')
const { WORDMARK } = await import('@/branding')

const SUCURSAL = {
  id: 1, nombre: 'Complejo Centro', direccion: null, localidad: null,
  telefono: null, email: null, punto_venta_arca: null, activa: true,
  observaciones: null,
}

function montar() {
  return render(
    <MemoryRouter initialEntries={['/agenda']}>
      <AuthProvider>
        <SucursalProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/agenda" element={<p>contenido de la agenda</p>} />
            </Route>
          </Routes>
        </SucursalProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  localStorage.clear()
  get.mockReset()
  listar.mockReset()
  listar.mockResolvedValue([SUCURSAL])
  get.mockImplementation((ruta: string) =>
    ruta === '/auth/me'
      ? Promise.resolve({ id: '1', username: 'admin', name: 'Administrador', role: 'admin', active: true })
      : Promise.reject(new Error(`ruta no esperada: ${ruta}`)),
  )
})

describe('cascarón de LibraClub', () => {
  it('arma el menú con las nueve pantallas del producto', async () => {
    montar()
    // El contenido llega por `Outlet`: si el envoltorio de `Cascaron` se
    // rompiera, el sidebar se dibujaría igual y la pantalla quedaría vacía.
    expect(await screen.findByText('contenido de la agenda')).toBeInTheDocument()
    for (const seccion of ['Agenda', 'Caja', 'Clientes', 'Canchas', 'Tarifas',
                           'Sucursales', 'Usuarios', 'Log de actividad', 'Configuración']) {
      expect(await screen.findByRole('link', { name: seccion })).toBeInTheDocument()
    }
  })

  it('🔑 muestra la sucursal activa, que el selector ya no tiene a la vista', async () => {
    montar()
    expect(await screen.findByText('Complejo Centro')).toBeInTheDocument()
  })

  it('a un encargado no le ofrece Usuarios, que su rol no puede abrir', async () => {
    get.mockImplementation((ruta: string) =>
      ruta === '/auth/me'
        ? Promise.resolve({ id: '2', username: 'encargado', name: 'Encargada', role: 'staff', active: true })
        : Promise.reject(new Error(`ruta no esperada: ${ruta}`)),
    )
    montar()
    // Se espera a que la sesión cargue ANTES de afirmar la ausencia: sin esto
    // el test pasaría por no haber renderizado todavía, que es la forma de
    // verde falso que este assert tiene que evitar.
    expect(await screen.findByText('Encargada')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'Sucursales' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Usuarios' })).not.toBeInTheDocument()
    // Configuración también: el router de empresa lleva `require_admin` y el de
    // SMTP lo exige por dentro, así que a un encargado el link le daría 403.
    expect(screen.queryByRole('link', { name: 'Configuración' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Log de actividad' })).not.toBeInTheDocument()
  })

  it('🔴 el logo y el nombre de la sidebar llevan las clases de marca', async () => {
    // El logo es el mismo archivo que en el login, pero las dos superficies lo
    // dibujan a tamaños distintos y NUNCA se ven juntas: si una queda con el
    // default de `libra-ui`, no falla nada y no lo reporta nadie.
    montar()
    const logo = await screen.findByRole('img', { name: 'LibraClub' })
    expect(logo.className).toContain('h-9')
    // Sin el override, el logo de 36 px se sale de la barra de iconos, donde el
    // ancho útil son 32. No se puede medir renderizando —el estado colapsado lo
    // pone un atributo del provider y jsdom no aplica Tailwind—, así que se
    // afirma que la regla condicional esté declarada.
    expect(logo.className).toContain('group-data-[collapsible=icon]:h-8')
    expect(logo.className).toContain('group-data-[collapsible=icon]:w-8')

    const nombre = screen.getByText('LibraClub')
    for (const clase of WORDMARK.split(' ')) expect(nombre.className).toContain(clase)
    expect(nombre.className).toContain('text-[15px]')
  })

  // ⚠️ **Acá NO se prueba el selector de sucursal**, aunque el Layout se lo pase
  // por `userMenu`. Ese slot lo mete `libra-ui` adentro del
  // `DropdownMenuContent` de Radix, que no se monta hasta que el menú se abre:
  // con el menú cerrado, buscarlo no encuentra nada ni cuando está bien ni
  // cuando está mal. Se midió invirtiendo su regla a propósito y el assert
  // seguía en verde. El componente tiene su propio test, montado solo, en
  // `SelectorDeSucursal.test.tsx`.
})
