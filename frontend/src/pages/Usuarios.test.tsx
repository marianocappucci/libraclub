import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Lo único propio de esta pantalla es el `basePath` -- y, desde la adopción
 * del router de usuarios de `libraauth` (ADR-018), `permitirEliminar` y
 * `usuarioActualId`. La pantalla en sí es la de `libra-ui` y la prueba el kit.
 *
 * Vale además como el **canario del kit**: si `libra-ui` deja de renderizar
 * acá —por el runtime de JSX de los `.tsx` que viven en `node_modules`, por una
 * peer dependency que falta, por un tag que cambió la API— este test se cae, y
 * se cae **en el repo del consumidor**, que es donde el problema se nota.
 *
 * 🔴 Se mockea `libra-ui/api-client` y no `fetch`: el componente pide por el
 * cliente del kit, no por `fetch` pelado. Un doble puesto una capa más abajo
 * hace que la llamada salga —el test del `basePath` pasa igual— pero los datos
 * no lleguen, y el síntoma es una tabla vacía que no dice por qué.
 */

const get = vi.fn()

vi.mock('libra-ui/api-client', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn() },
  }
})

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { id: '1', username: 'admin', name: 'Admin', role: 'admin' }, loading: false }),
}))

const { Usuarios } = await import('./Usuarios')

beforeEach(() => {
  get.mockReset()
  get.mockResolvedValue([
    { id: '1', username: 'admin', name: 'Administrador', role: 'admin', active: true, email: '' },
    { id: '2', username: 'ana', name: 'Ana Encargada', role: 'staff', active: true, email: '' },
  ])
})

describe('pantalla de usuarios', () => {
  it('apunta al router de este producto, que va en castellano', async () => {
    render(<Usuarios />)
    await waitFor(() => expect(get).toHaveBeenCalled())
    // `/api/usuarios`, no el `/users` que el componente trae por default. Es un
    // valor que el consumidor hardcodea: si el backend moviera el prefijo, acá
    // no se rompe nada y la pantalla queda vacía sin decir por qué.
    expect(get).toHaveBeenCalledWith('/api/usuarios')
  })

  it('renderiza el componente compartido con lo que devuelve la API', async () => {
    render(<Usuarios />)
    expect(await screen.findByText('Administrador')).toBeInTheDocument()
  })

  it('el botón «Eliminar» aparece en otro usuario, pero no en la fila propia', async () => {
    render(<Usuarios />)
    await screen.findByText('Ana Encargada')

    // El backend ya trae el router de `libraauth` con las guardas del único
    // admin (`DELETE` con `204`), así que `permitirEliminar` va en `true` --
    // sin eso el botón no aparece en ninguna fila.
    expect(screen.getByLabelText('Eliminar Ana Encargada')).toBeInTheDocument()
    // Y no en la propia: `usuarioActualId` es el `id` del usuario logueado
    // (mockeado como '1' arriba), y ese usuario es «Administrador».
    expect(screen.queryByLabelText('Eliminar Administrador')).not.toBeInTheDocument()
  })
})
