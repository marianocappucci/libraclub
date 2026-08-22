/** Entrar o registrarse, sin salir de la pantalla de reservas.
 *
 * 🔑 **Es un diálogo y no una página aparte.** El jugador ya eligió el turno de
 * las 20:00; mandarlo a otra ruta y traerlo de vuelta pierde el contexto y la
 * mitad se va. Al entrar, la reserva sigue sola.
 */
import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

import { useJugador } from '@/portal/JugadorContext'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { buttonVariants } from '@/components/ui/button'
import { AvisoDeError } from '@/components/listado'

export function DialogoDeCuenta({
  abierto,
  onCerrar,
  onEntro,
}: {
  abierto: boolean
  onCerrar: () => void
  onEntro: () => void
}) {
  const { entrar, registrarse } = useJugador()
  const [modo, setModo] = useState<'entrar' | 'registrarse'>('registrarse')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nombre, setNombre] = useState('')
  const [telefono, setTelefono] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (abierto) setError(null)
  }, [abierto])

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setEnviando(true)
    try {
      if (modo === 'entrar') await entrar(email, password)
      else await registrarse({ email, password, nombre, telefono })
      onEntro()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Dialog open={abierto} onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {modo === 'entrar' ? 'Entrá a tu cuenta' : 'Creá tu cuenta'}
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={enviar} className="space-y-3">
          <p className="text-sm text-muted-foreground">
            {modo === 'entrar'
              ? 'Entrá para confirmar el turno que elegiste.'
              : 'Con una cuenta guardás tus reservas y podés cancelarlas vos mismo.'}
          </p>

          {modo === 'registrarse' && (
            <>
              <label className="block space-y-1">
                <span className="text-sm font-medium">Nombre</span>
                <Input value={nombre} onChange={(e) => setNombre(e.target.value)} />
              </label>
              <label className="block space-y-1">
                <span className="text-sm font-medium">
                  Teléfono <span className="text-muted-foreground">(opcional)</span>
                </span>
                <Input value={telefono} onChange={(e) => setTelefono(e.target.value)} />
              </label>
            </>
          )}

          <label className="block space-y-1">
            <span className="text-sm font-medium">Correo</span>
            <Input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm font-medium">Contraseña</span>
            <Input
              type="password"
              autoComplete={modo === 'entrar' ? 'current-password' : 'new-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {modo === 'registrarse' && (
              <span className="text-xs text-muted-foreground">Al menos 8 caracteres.</span>
            )}
          </label>

          <AvisoDeError mensaje={error} />

          <Button type="submit" disabled={enviando} className="w-full">
            {enviando
              ? 'Un momento…'
              : modo === 'entrar'
                ? 'Entrar'
                : 'Crear cuenta y seguir'}
          </Button>

          <button
            type="button"
            onClick={() => {
              setModo(modo === 'entrar' ? 'registrarse' : 'entrar')
              setError(null)
            }}
            className={`${buttonVariants({ variant: 'ghost' })} w-full`}
          >
            {modo === 'entrar' ? 'No tengo cuenta' : 'Ya tengo cuenta'}
          </button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
