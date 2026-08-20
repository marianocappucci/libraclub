import { useCallback, useEffect, useState } from 'react'
import { canchas as api } from '@/lib/api'
import type { Cancha } from '@/lib/api'
import { useSucursal } from '@/context/SucursalContext'
import { useAuth } from '@/context/AuthContext'
import { FormularioDeCancha } from '@/components/FormularioDeCancha'

export function Canchas() {
  const { actual } = useSucursal()
  const { usuario } = useAuth()
  const [filas, setFilas] = useState<Cancha[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editando, setEditando] = useState<Cancha | null>(null)
  const [abierto, setAbierto] = useState(false)

  // 🔴 El alta, la edición y la baja de canchas son de **admin**: el backend las
  // gatea con `require_admin`. La UI esconde los botones en vez de mostrarlos y
  // dejar que fallen con 403 — un botón que siempre da error es peor que no
  // tenerlo. Lo que la UI **no** hace es decidir el permiso: si esta condición
  // se equivocara, el servidor sigue rechazando igual.
  const puedeEscribir = usuario?.role === 'admin'

  const recargar = useCallback(() => {
    api.listar().then(setFilas).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(recargar, [recargar])

  const propias = filas.filter((c) => actual === null || c.sucursal_id === actual)

  async function borrar(cancha: Cancha) {
    if (!confirm(`¿Borrar ${cancha.nombre}? Si tiene reservas no se va a poder.`)) return
    setError(null)
    try {
      await api.borrar(cancha.id)
      recargar()
    } catch (e) {
      // El 409 del backend ya explica qué hacer —darla de baja en vez de
      // borrarla— porque la FK de reservas es RESTRICT y no CASCADE. Se muestra
      // tal cual viene.
      setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Canchas</h1>
        {puedeEscribir && actual !== null && (
          <button
            onClick={() => {
              setEditando(null)
              setAbierto(true)
            }}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white"
          >
            Nueva cancha
          </button>
        )}
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          {error}
        </p>
      )}

      <table className="w-full overflow-hidden rounded-lg border border-slate-200 bg-white text-sm">
        <thead className="bg-slate-100 text-left text-slate-600">
          <tr>
            <th className="px-3 py-2">Nombre</th>
            <th className="px-3 py-2">Deporte</th>
            <th className="px-3 py-2">Turno</th>
            <th className="px-3 py-2">Techada</th>
            <th className="px-3 py-2">Estado</th>
            {puedeEscribir && <th className="px-3 py-2" />}
          </tr>
        </thead>
        <tbody>
          {propias.map((c) => (
            <tr key={c.id} className="border-t border-slate-100">
              <td className="px-3 py-2 font-medium">{c.nombre}</td>
              <td className="px-3 py-2">{c.deporte}</td>
              <td className="px-3 py-2">{c.duracion_turno_min} min</td>
              <td className="px-3 py-2">{c.techada ? 'Sí' : 'No'}</td>
              <td className="px-3 py-2">{c.activa ? 'Activa' : 'De baja'}</td>
              {puedeEscribir && (
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <button
                    onClick={() => {
                      setEditando(c)
                      setAbierto(true)
                    }}
                    className="rounded-md border border-slate-300 px-2 py-1 hover:bg-slate-100"
                  >
                    Editar
                  </button>
                  <button
                    onClick={() => borrar(c)}
                    className="ml-2 rounded-md border border-red-300 px-2 py-1 text-red-800 hover:bg-red-50"
                  >
                    Borrar
                  </button>
                </td>
              )}
            </tr>
          ))}
          {propias.length === 0 && (
            <tr>
              <td colSpan={6} className="px-3 py-4 text-slate-500">
                Esta sucursal todavía no tiene canchas.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {actual !== null && (
        <FormularioDeCancha
          abierto={abierto}
          cancha={editando}
          sucursalId={actual}
          onCerrar={() => setAbierto(false)}
          onGuardada={() => {
            setAbierto(false)
            recargar()
          }}
        />
      )}
    </div>
  )
}
