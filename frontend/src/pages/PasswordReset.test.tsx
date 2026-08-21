import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

/**
 * 🔴 **El defecto no era que faltara la pantalla: era el ruteo.**
 *
 * `App.tsx` de este producto no rutea el login — sin sesión devuelve `<Login />`
 * para cualquier URL. Con las rutas de recuperación puestas del lado
 * autenticado, el enlace "¿Olvidaste tu contraseña?" habría cambiado la URL y
 * dejado la misma pantalla, y el correo con el enlace de reset habría abierto el
 * login pidiendo la contraseña que la persona justamente no tiene.
 *
 * Por eso el test monta el ruteo **sin usuario** y verifica que esas dos URLs
 * lleguen a su pantalla y no al login.
 */

// 🔑 Se mockea `libra-ui/AuthContext` y NO `@/context/AuthContext`.
// El segundo es un re-export de una línea del primero, así que mockearlo deja
// afuera a `libra-ui/Login`, que importa `useAuth` del kit directamente — y el
// test del control negativo (la ruta que SÍ cae en el login) reventaba con
// "useAuth debe usarse dentro de AuthProvider" en vez de probar nada.
vi.mock('libra-ui/AuthContext', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    AuthProvider: ({ children }: { children: React.ReactNode }) => children,
    useAuth: () => ({ user: null, loading: false, login: vi.fn(), logout: vi.fn() }),
  }
})

vi.mock('@/context/SucursalContext', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    SucursalProvider: ({ children }: { children: React.ReactNode }) => children,
    useSucursal: () => ({
      sucursales: [], actual: 1, elegir: () => {}, recargar: () => {}, cargando: false,
    }),
  }
})

const { Ruteo } = await import('../App')

function enLaRuta(ruta: string) {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <Ruteo />
    </MemoryRouter>,
  )
}

describe('recuperación de contraseña, sin sesión', () => {
  it('/forgot-password abre la pantalla de recuperación, no el login', async () => {
    enLaRuta('/forgot-password')
    expect(await screen.findByRole('button', { name: /Enviar enlace/i })).toBeInTheDocument()
    // El control que importa: si cayera en el login habría un campo de
    // contraseña, que es justo lo que quien entra acá no puede completar.
    expect(screen.queryByLabelText(/^Contraseña$/i)).not.toBeInTheDocument()
  })

  it('/reset-password con token abre la de cambio, no el login', async () => {
    // Con token, porque es como llega desde el correo. Sin él el kit muestra
    // "Enlace incompleto", que también sería una pantalla de recuperación —
    // así que asertar sobre esa versión pasaría aunque el ruteo estuviera mal
    // de otra forma.
    enLaRuta('/reset-password?token=un-token-cualquiera')
    expect(
      await screen.findByRole('button', { name: /Guardar contraseña/i }),
    ).toBeInTheDocument()
  })

  it('/reset-password SIN token explica que el enlace está incompleto', async () => {
    enLaRuta('/reset-password')
    expect(await screen.findByText(/no trae el código de recuperación/i)).toBeInTheDocument()
  })

  it('el login ofrece el enlace de recuperación', async () => {
    // 🔴 **Lo que se reportó como faltante.** Sin `forgotPasswordPath` en la
    // config de `createLogin`, el kit simplemente no pinta el enlace: la
    // pantalla queda idéntica y no hay nada que falle. Los tres tests de
    // arriba pasaban igual —las rutas existían— y el usuario no tenía por
    // dónde llegar a ellas.
    enLaRuta('/agenda')
    const enlace = await screen.findByRole('link', { name: /¿Olvidaste tu contraseña\?/i })
    expect(enlace).toHaveAttribute('href', '/forgot-password')
  })

  it('cualquier otra ruta sí cae en el login', async () => {
    enLaRuta('/agenda')
    // Control negativo: sin él, un ruteo que mostrara la pantalla de
    // recuperación SIEMPRE pasaría los tests de arriba.
    //
    // Se busca el label **exacto** `Usuario`: `/Contraseña/i` matchea también
    // en las de recuperación —y dos veces en la misma, por el ojito— y
    // `/Usuario/i` matchea el "Usuario o correo" de ForgotPassword. Con el
    // matcher laxo, poner ForgotPassword en el catch-all pasaba este test.
    expect(await screen.findByLabelText('Usuario')).toBeInTheDocument()
    expect(screen.queryByText(/no trae el código de recuperación/i)).not.toBeInTheDocument()
  })
})
