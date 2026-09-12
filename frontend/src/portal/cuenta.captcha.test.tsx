import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El captcha del diálogo de cuenta del portal.
 *
 * 🔴 El backend exige la solución del desafío en `/api/portal/login` y en
 * `/api/portal/registro`: sin ella contesta 400 aunque la clave sea buena. Si
 * el diálogo dejara de mandarla, **ningún jugador podría entrar ni
 * registrarse**, y la pantalla se vería exactamente igual. Esto es lo que se
 * pondría rojo.
 *
 * El widget en sí (`CampoCaptcha`) y la sonda (`useCaptcha`) los prueba
 * libra-ui; acá se reemplazan por dobles y se fija el cableado: qué ruta se
 * pide, qué viaja en el cuerpo, y que un intento fallido pida otro desafío.
 */

const login = vi.fn()
const registro = vi.fn()
const yo = vi.fn()
const reiniciar = vi.fn()

const estado = {
  activo: true,
  path: '/auth/captcha',
  payload: 'solucion-123',
  setPayload: vi.fn(),
  reiniciar,
  intento: 0,
}
const useCaptcha = vi.fn(() => estado)

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    portal: { ...(real.portal as object), login, registro, yo, logout: vi.fn() },
  }
})
vi.mock('libra-ui/captcha', () => ({ useCaptcha }))
vi.mock('libra-ui/CampoCaptcha', () => ({ CampoCaptcha: () => null }))

const { JugadorProvider } = await import('./JugadorContext')
const { DialogoDeCuenta } = await import('./DialogoDeCuenta')

function montar() {
  return render(
    <JugadorProvider>
      <DialogoDeCuenta abierto onCerrar={() => {}} onEntro={() => {}} />
    </JugadorProvider>,
  )
}

async function completarEntrar() {
  await userEvent.click(screen.getByRole('button', { name: 'Ya tengo cuenta' }))
  await userEvent.type(screen.getByLabelText('Correo'), 'j@x.com')
  await userEvent.type(screen.getByLabelText(/Contraseña/), 'una-clave-larga')
}

beforeEach(() => {
  vi.clearAllMocks()
  estado.activo = true
  estado.payload = 'solucion-123'
  yo.mockResolvedValue(null)
  login.mockResolvedValue({ id: 1, nombre: 'Juan', email: 'j@x.com' })
  registro.mockResolvedValue({ id: 1, nombre: 'Juan', email: 'j@x.com' })
})

describe('portal: el captcha de la cuenta', () => {
  it('pide el desafío a /auth/captcha, el mismo del login de staff', () => {
    montar()
    expect(useCaptcha).toHaveBeenCalledWith('/auth/captcha')
  })

  it('entrar manda la solución del captcha', async () => {
    montar()
    await completarEntrar()
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))
    await waitFor(() =>
      expect(login).toHaveBeenCalledWith({
        email: 'j@x.com', password: 'una-clave-larga', captcha: 'solucion-123',
      }),
    )
  })

  it('registrarse también', async () => {
    montar()
    await userEvent.type(screen.getByLabelText('Nombre'), 'Juan')
    await userEvent.type(screen.getByLabelText('Correo'), 'j@x.com')
    await userEvent.type(screen.getByLabelText(/Contraseña/), 'una-clave-larga')
    await userEvent.click(screen.getByRole('button', { name: 'Crear cuenta y seguir' }))
    await waitFor(() =>
      expect(registro).toHaveBeenCalledWith(expect.objectContaining({ captcha: 'solucion-123' })),
    )
  })

  it('sin tildar la casilla no deja enviar', () => {
    estado.payload = ''
    montar()
    expect(screen.getByRole('button', { name: 'Crear cuenta y seguir' })).toBeDisabled()
  })

  it('el control — sin captcha activo el botón no se traba', () => {
    // Un backend que no emite desafíos (la sonda no confirma) no puede dejar el
    // formulario sin salida: es el mismo criterio que `createLogin`.
    estado.activo = false
    estado.payload = ''
    montar()
    expect(screen.getByRole('button', { name: 'Crear cuenta y seguir' })).toBeEnabled()
  })

  it('un intento fallido pide un desafío nuevo', async () => {
    // El servidor ya gastó el desafío (sirve una sola vez): sin esto el
    // segundo intento viaja con una solución usada y rebota con 400.
    login.mockRejectedValue(new Error('El correo o la contraseña no son correctos.'))
    montar()
    await completarEntrar()
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))
    expect(await screen.findByText(/no son correctos/)).toBeInTheDocument()
    expect(reiniciar).toHaveBeenCalled()
  })
})
