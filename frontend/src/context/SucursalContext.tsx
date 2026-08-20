import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { sucursales as apiSucursales } from '@/lib/api'
import type { Sucursal } from '@/lib/api'

interface Contexto {
  sucursales: Sucursal[]
  actual: number | null
  elegir: (id: number) => void
  cargando: boolean
}

const SucursalContext = createContext<Contexto | null>(null)

//: Se recuerda la elección entre recargas. Un encargado que trabaja en una sola
//: sucursal no tiene por qué volver a elegirla cada vez que abre la pantalla.
const CLAVE = 'libraclub.sucursal'

export function SucursalProvider({ children }: { children: ReactNode }) {
  const [sucursales, setSucursales] = useState<Sucursal[]>([])
  const [actual, setActual] = useState<number | null>(null)
  const [cargando, setCargando] = useState(true)

  useEffect(() => {
    apiSucursales
      .listar()
      .then((filas) => {
        const activas = filas.filter((s) => s.activa)
        setSucursales(activas)
        // 🔴 La guardada sólo vale si **todavía existe y está activa**. Una
        // sucursal dada de baja dejaría la app pidiendo la agenda de algo que
        // no está, y la pantalla se vería vacía sin decir por qué.
        const guardada = Number(localStorage.getItem(CLAVE))
        const valida = activas.some((s) => s.id === guardada)
        setActual(valida ? guardada : (activas[0]?.id ?? null))
      })
      .catch(() => setSucursales([]))
      .finally(() => setCargando(false))
  }, [])

  const elegir = (id: number) => {
    setActual(id)
    localStorage.setItem(CLAVE, String(id))
  }

  return (
    <SucursalContext.Provider value={{ sucursales, actual, elegir, cargando }}>
      {children}
    </SucursalContext.Provider>
  )
}

export function useSucursal(): Contexto {
  const contexto = useContext(SucursalContext)
  if (!contexto) throw new Error('useSucursal fuera de SucursalProvider')
  return contexto
}
