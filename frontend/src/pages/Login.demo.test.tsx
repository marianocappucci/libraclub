/**
 * El botón "Entrar a la demo" de la pantalla de login.
 *
 * 🔴 Existe por un defecto real de la familia, no por completitud. El
 * 2026-08-06 las seis SPA tenían `POST /auth/demo` andando en el backend
 * —verificado con `curl`— y **ninguna lo llamaba nunca**: el visitante de
 * `demo.<producto>.com.ar` veía el login normal, pidiéndole credenciales que
 * no tenía. Todo lo demás estaba bien; faltaba una línea del frontend, y nada
 * la reclamaba porque la verificación había sido contra el endpoint.
 *
 * Por eso lo que se afirma acá es lo que ve el visitante, y no que `demoPath`
 * esté escrito en la config.
 *
 * Los dos casos van juntos a propósito: sin el negativo, un botón que se
 * dibujara SIEMPRE pasaría el positivo — y estaría ofreciéndole "entrar a la
 * demo" a la instancia de cada complejo.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthProvider } from '@/context/AuthContext'

import { Login } from './Login'

/**
 * Va dentro de `AuthProvider` porque el `Login` del kit usa `useAuth`, que
 * tira si no encuentra el contexto: sin el provider el test fallaría por el
 * andamiaje y no por la pantalla.
 *
 * 🔑 Y se stubea `fetch` y no `libra-ui/api-client` —al revés que
 * `Usuarios.test.tsx`— a propósito: lo que este test mide es **cómo reacciona
 * el kit a lo que contesta el servidor**, y el caso negativo es justamente un
 * `200` con `Content-Type: text/html`. Con un doble de `api.get` habría que
 * decidir a mano qué devuelve ante ese HTML, o sea codificar la suposición que
 * el test viene a verificar.
 */
function montar() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Login />
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/** Responde la sonda `GET /auth/demo` con lo que contestaría cada instancia. */
function sondaDeDemo(respuesta: Response) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes('/auth/demo')) return respuesta
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
}

describe('el botón de la demo', () => {
  it('aparece cuando la instancia se declara demo', async () => {
    sondaDeDemo(new Response(
      JSON.stringify({ enabled: true, username: 'visitante', requiere_codigo: true }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ))
    montar()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /entrar a la demo/i })).toBeInTheDocument()
    })
  })

  it('NO aparece en la instancia de un complejo, que contesta el index.html con 200', async () => {
    // El control que importa: LibraClub sirve la SPA con un catch-all, así que
    // la sonda contra una instancia normal **devuelve 200** con HTML. Un botón
    // condicionado al código de estado aparecería en todas.
    sondaDeDemo(new Response(
      '<!DOCTYPE html><html><body>la SPA</body></html>',
      { status: 200, headers: { 'Content-Type': 'text/html' } },
    ))
    const { container } = montar()
    await waitFor(() => {
      expect(container.querySelector('input[type="password"]')).not.toBeNull()
    })
    expect(screen.queryByText(/entrar a la demo/i)).toBeNull()
  })
})
