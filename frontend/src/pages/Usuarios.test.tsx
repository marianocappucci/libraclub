import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Lo único propio de esta pantalla es el `basePath`, así que es lo único que
 * este test fija. La pantalla en sí es la de `libra-ui` y la prueba el kit.
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

const { Usuarios } = await import('./Usuarios')

beforeEach(() => {
  get.mockReset()
  get.mockResolvedValue([
    { id: '1', username: 'admin', name: 'Administrador', role: 'admin', active: true, email: '' },
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
})
