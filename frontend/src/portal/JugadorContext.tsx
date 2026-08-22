/** La sesión del jugador en el portal.
 *
 * 🔴 **Separada del `AuthContext` del backoffice, igual que la cookie.** Son
 * dos poblaciones que no se mezclan: un encargado logueado en el mostrador y un
 * jugador entrando desde su teléfono. Compartir el contexto haría que entrar al
 * portal en la computadora del complejo pareciera cerrar la sesión del
 * encargado — o peor, que el portal creyera tener permisos de staff.
 */
import { createContext, useCallback, useContext, useEffect, useState } from 'react'

import { portal } from '@/lib/api'
import type { Jugador } from '@/lib/api'

interface Contexto {
  jugador: Jugador | null
  cargando: boolean
  entrar: (email: string, password: string) => Promise<void>
  registrarse: (datos: {
    email: string; password: string; nombre: string; telefono?: string
  }) => Promise<void>
  salir: () => Promise<void>
}

const JugadorContext = createContext<Contexto | null>(null)

export function JugadorProvider({ children }: { children: React.ReactNode }) {
  const [jugador, setJugador] = useState<Jugador | null>(null)
  const [cargando, setCargando] = useState(true)

  useEffect(() => {
    portal
      .yo()
      .then(setJugador)
      // Un 401 acá es lo normal: la mayoría de los visitantes no tiene sesión.
      // No es un error que mostrar.
      .catch(() => setJugador(null))
      .finally(() => setCargando(false))
  }, [])

  const entrar = useCallback(async (email: string, password: string) => {
    setJugador(await portal.login({ email, password }))
  }, [])

  const registrarse = useCallback(
    async (datos: { email: string; password: string; nombre: string; telefono?: string }) => {
      setJugador(await portal.registro(datos))
    },
    [],
  )

  const salir = useCallback(async () => {
    await portal.logout()
    setJugador(null)
  }, [])

  return (
    <JugadorContext.Provider value={{ jugador, cargando, entrar, registrarse, salir }}>
      {children}
    </JugadorContext.Provider>
  )
}

export function useJugador(): Contexto {
  const ctx = useContext(JugadorContext)
  if (!ctx) throw new Error('useJugador fuera de JugadorProvider')
  return ctx
}
