import { useEffect, useState } from 'react'
import { canchas as api } from '@/lib/api'
import type { Cancha } from '@/lib/api'
import { useSucursal } from '@/context/SucursalContext'

export function Canchas() {
  const { actual } = useSucursal()
  const [filas, setFilas] = useState<Cancha[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.listar().then(setFilas).catch((e: Error) => setError(e.message))
  }, [])

  const propias = filas.filter((c) => actual === null || c.sucursal_id === actual)

  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">Canchas</h1>
      {error && <p className="text-sm text-red-700">{error}</p>}
      <table className="w-full overflow-hidden rounded-lg border border-slate-200 bg-white text-sm">
        <thead className="bg-slate-100 text-left text-slate-600">
          <tr>
            <th className="px-3 py-2">Nombre</th>
            <th className="px-3 py-2">Deporte</th>
            <th className="px-3 py-2">Turno</th>
            <th className="px-3 py-2">Techada</th>
            <th className="px-3 py-2">Estado</th>
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
            </tr>
          ))}
          {propias.length === 0 && (
            <tr>
              <td colSpan={5} className="px-3 py-4 text-slate-500">
                Esta sucursal todavía no tiene canchas.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
