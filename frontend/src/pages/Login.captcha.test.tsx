/**
 * El login y «olvidé mi contraseña» consultan la ruta del captcha.
 *
 * 🔴 El backend monta el router con `captcha=True`: sin la solución de un
 * desafío ALTCHA, el login contesta 400 aunque la contraseña sea buena. El
 * recuadro «No soy un robot» sólo aparece si la pantalla consulta
 * `/auth/captcha` y recibe un desafío — así que si alguien sacara `captchaPath`
 * de la config, el kit simplemente no lo dibujaría, la pantalla se vería igual,
 * y **nadie podría entrar**. Esto es lo que se pondría rojo.
 *
 * La sonda contesta 404 y no 401: el api-client de libra-ui trata un 401 como
 * sesión vencida, y eso no es lo que pasa en esa ruta.
 */
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthProvider } from '@/context/AuthContext'

import { Login } from './Login'
import { ForgotPassword } from './PasswordReset'

const RUTA_CAPTCHA = '/auth/captcha'

afterEach(() => {
  vi.unstubAllGlobals()
})

function servidor() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes(RUTA_CAPTCHA)) {
      return new Response(JSON.stringify({ detail: 'Not Found' }), {
        status: 404, headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function consulto(fetchMock: ReturnType<typeof servidor>, ruta: string) {
  return fetchMock.mock.calls.some(([u]) => String(u).includes(ruta))
}

describe('el captcha del login', () => {
  it('el login consulta /auth/captcha', async () => {
    const fetchMock = servidor()
    render(
      <MemoryRouter>
        <AuthProvider>
          <Login />
        </AuthProvider>
      </MemoryRouter>,
    )
    await waitFor(() => expect(consulto(fetchMock, RUTA_CAPTCHA)).toBe(true))
  })

  it('«olvidé mi contraseña» también', async () => {
    const fetchMock = servidor()
    render(
      <MemoryRouter>
        <AuthProvider>
          <ForgotPassword />
        </AuthProvider>
      </MemoryRouter>,
    )
    await waitFor(() => expect(consulto(fetchMock, RUTA_CAPTCHA)).toBe(true))
  })

  it('el control — la sonda de la demo sí se ve, así que el mock mira las llamadas', async () => {
    // Sin esto, un `fetch` que nunca se llamara haría fallar los dos de arriba
    // por otra razón que la que dicen; y uno que registrara todo por error los
    // haría pasar siempre. La demo es la otra sonda del login.
    const fetchMock = servidor()
    render(
      <MemoryRouter>
        <AuthProvider>
          <Login />
        </AuthProvider>
      </MemoryRouter>,
    )
    await waitFor(() => expect(consulto(fetchMock, '/auth/demo')).toBe(true))
    expect(consulto(fetchMock, '/ruta-que-nadie-pide')).toBe(false)
  })
})
