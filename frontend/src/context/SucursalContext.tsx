import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { sucursales as apiSucursales } from '@/lib/api'
import type { Sucursal } from '@/lib/api'

interface Contexto {
  sucursales: Sucursal[]
  actual: number | null
  elegir: (id: number) => void
  /** Vuelve a pedir la lista. Lo llama el ABM después de guardar o borrar.
   *
   *  🔴 Sin esto, el selector del encabezado sigue mostrando la lista vieja:
   *  una sucursal recién creada no aparece hasta recargar la página entera, y
   *  una dada de baja se sigue pudiendo elegir. Es la clase de desincronización
   *  que se lee como "no se guardó". */
  recargar: () => void
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

  const recargar = useCallback(() => {
    apiSucursales
      .listar()
      .then((filas) => {
        const activas = filas.filter((s) => s.activa)
        setSucursales(activas)
        // 🔴 La elegida sólo vale si **todavía existe y está activa**. Vale para
        // la guardada en `localStorage` al arrancar y, desde que hay ABM,
        // también para la que está elegida ahora mismo: darla de baja o borrarla
        // dejaría la app pidiendo la agenda de algo que no está, y la pantalla
        // se vería vacía sin decir por qué.
        setActual((elegida) => {
          const candidata = elegida ?? Number(localStorage.getItem(CLAVE))
          const valida = activas.some((s) => s.id === candidata)
          return valida ? candidata : (activas[0]?.id ?? null)
        })
      })
      .catch(() => setSucursales([]))
      .finally(() => setCargando(false))
  }, [])

  useEffect(recargar, [recargar])

  const elegir = (id: number) => {
    setActual(id)
    localStorage.setItem(CLAVE, String(id))
  }

  return (
    <SucursalContext.Provider
      value={{ sucursales, actual, elegir, recargar, cargando }}
    >
      {children}
    </SucursalContext.Provider>
  )
}

export function useSucursal(): Contexto {
  const contexto = useContext(SucursalContext)
  if (!contexto) throw new Error('useSucursal fuera de SucursalProvider')
  return contexto
}
