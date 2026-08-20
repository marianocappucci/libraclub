import { useEffect, useState } from 'react'
import { tarifas as api, canchas as apiCanchas } from '@/lib/api'
import type { Cancha, Tarifa } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { useSucursal } from '@/context/SucursalContext'

const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

/** Cómo se lee el alcance de una tarifa, en castellano. */
function alcance(t: Tarifa): string {
  if (t.alcance_dia === 'feriado') return 'Feriados'
  if (t.alcance_dia === 'dia_semana') return DIAS[t.dia_semana ?? 0]
  return 'Todos los días'
}

export function Tarifas() {
  const { actual } = useSucursal()
  const [filas, setFilas] = useState<Tarifa[]>([])
  const [canchas, setCanchas] = useState<Cancha[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.listar(), apiCanchas.listar()])
      .then(([t, c]) => {
        setFilas(t)
        setCanchas(c)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const propias = filas.filter((t) => actual === null || t.sucursal_id === actual)
  const nombreCancha = (id: number | null) =>
    id === null ? 'Toda la sucursal' : (canchas.find((c) => c.id === id)?.nombre ?? `#${id}`)

  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">Tarifas</h1>
      <p className="text-sm text-slate-500">
        Gana la de mayor prioridad; con la misma prioridad, la más específica:
        feriado antes que día de semana, y una cancha antes que toda la sucursal.
      </p>
      {error && <p className="text-sm text-red-700">{error}</p>}
      <table className="w-full overflow-hidden rounded-lg border border-slate-200 bg-white text-sm">
        <thead className="bg-slate-100 text-left text-slate-600">
          <tr>
            <th className="px-3 py-2">Nombre</th>
            <th className="px-3 py-2">Aplica</th>
            <th className="px-3 py-2">Cancha</th>
            <th className="px-3 py-2">Franja</th>
            <th className="px-3 py-2">Precio</th>
            <th className="px-3 py-2">Seña</th>
            <th className="px-3 py-2">Prioridad</th>
          </tr>
        </thead>
        <tbody>
          {propias.map((t) => (
            <tr key={t.id} className="border-t border-slate-100">
              <td className="px-3 py-2 font-medium">{t.nombre}</td>
              <td className="px-3 py-2">{alcance(t)}</td>
              <td className="px-3 py-2">{nombreCancha(t.cancha_id)}</td>
              <td className="px-3 py-2">
                {t.hora_desde.slice(0, 5)} – {t.hora_hasta.slice(0, 5)}
              </td>
              <td className="px-3 py-2">{pesos(t.precio)}</td>
              <td className="px-3 py-2">
                {t.sena_porcentaje > 0 ? `${t.sena_porcentaje}%` : '—'}
              </td>
              <td className="px-3 py-2">{t.prioridad}</td>
            </tr>
          ))}
          {propias.length === 0 && (
            <tr>
              <td colSpan={7} className="px-3 py-4 text-slate-500">
                Sin tarifas cargadas. Una franja sin tarifa no se puede reservar.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
