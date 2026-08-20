import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { sesion } from '@/lib/api'

interface Usuario {
  username: string
  role?: string
}

interface Contexto {
  usuario: Usuario | null
  cargando: boolean
  entrar: (username: string, password: string) => Promise<void>
  salir: () => Promise<void>
}

const AuthContext = createContext<Contexto | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<Usuario | null>(null)
  // 🔴 Arranca en `true`, no en `false`. Con `false`, la primera pintada ocurre
  // antes de saber si hay sesión y manda al login a alguien que ya estaba
  // logueado — un parpadeo al login en cada recarga.
  const [cargando, setCargando] = useState(true)

  useEffect(() => {
    sesion
      .yo()
      .then(setUsuario)
      .catch(() => setUsuario(null))
      .finally(() => setCargando(false))
  }, [])

  const entrar = useCallback(async (username: string, password: string) => {
    await sesion.login(username, password)
    setUsuario(await sesion.yo())
  }, [])

  const salir = useCallback(async () => {
    await sesion.logout()
    setUsuario(null)
  }, [])

  return (
    <AuthContext.Provider value={{ usuario, cargando, entrar, salir }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): Contexto {
  const contexto = useContext(AuthContext)
  if (!contexto) throw new Error('useAuth fuera de AuthProvider')
  return contexto
}
