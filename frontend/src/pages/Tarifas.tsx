import { useCallback, useEffect, useState } from 'react'
import { canchas as apiCanchas, tarifas as api } from '@/lib/api'
import type { Cancha, Tarifa } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { useSucursal } from '@/context/SucursalContext'
import { useAuth } from '@/context/AuthContext'
import { FormularioDeTarifa } from '@/components/FormularioDeTarifa'

const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

/** Cómo se lee el alcance de una tarifa, en castellano. */
function alcance(t: Tarifa): string {
  if (t.alcance_dia === 'feriado') return 'Feriados'
  if (t.alcance_dia === 'dia_semana') return DIAS[t.dia_semana ?? 0]
  return 'Todos los días'
}

export function Tarifas() {
  const { actual } = useSucursal()
  const { user } = useAuth()
  const [filas, setFilas] = useState<Tarifa[]>([])
  const [canchas, setCanchas] = useState<Cancha[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editando, setEditando] = useState<Tarifa | null>(null)
  const [abierto, setAbierto] = useState(false)

  // Igual que en Canchas: el backend gatea con `require_admin` y la UI no
  // ofrece botones que van a dar 403. El permiso lo decide el servidor.
  const puedeEscribir = user?.role === 'admin'

  const recargar = useCallback(() => {
    Promise.all([api.listar(), apiCanchas.listar()])
      .then(([t, c]) => {
        setFilas(t)
        setCanchas(c)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(recargar, [recargar])

  const propias = filas.filter((t) => actual === null || t.sucursal_id === actual)
  const deLaSucursal = canchas.filter((c) => actual === null || c.sucursal_id === actual)
  const nombreCancha = (id: number | null) =>
    id === null ? 'Toda la sucursal' : (canchas.find((c) => c.id === id)?.nombre ?? `#${id}`)

  async function borrar(tarifa: Tarifa) {
    if (!confirm(`¿Borrar la tarifa "${tarifa.nombre}"?`)) return
    setError(null)
    try {
      await api.borrar(tarifa.id)
      recargar()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Tarifas</h1>
        {puedeEscribir && actual !== null && (
          <button
            onClick={() => {
              setEditando(null)
              setAbierto(true)
            }}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white"
          >
            Nueva tarifa
          </button>
        )}
      </div>

      <p className="text-sm text-slate-500">
        Gana la de mayor prioridad; con la misma prioridad, la más específica:
        feriado antes que día de semana, y una cancha antes que toda la sucursal.
      </p>

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
            <th className="px-3 py-2">Aplica</th>
            <th className="px-3 py-2">Cancha</th>
            <th className="px-3 py-2">Franja</th>
            <th className="px-3 py-2">Precio</th>
            <th className="px-3 py-2">Seña</th>
            <th className="px-3 py-2">Prioridad</th>
            {puedeEscribir && <th className="px-3 py-2" />}
          </tr>
        </thead>
        <tbody>
          {propias.map((t) => (
            <tr key={t.id} className={`border-t border-slate-100 ${t.activa ? '' : 'text-slate-400'}`}>
              <td className="px-3 py-2 font-medium">
                {t.nombre}
                {!t.activa && <span className="ml-2 text-xs">(inactiva)</span>}
              </td>
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
              {puedeEscribir && (
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <button
                    onClick={() => {
                      setEditando(t)
                      setAbierto(true)
                    }}
                    className="rounded-md border border-slate-300 px-2 py-1 hover:bg-slate-100"
                  >
                    Editar
                  </button>
                  <button
                    onClick={() => borrar(t)}
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
              <td colSpan={8} className="px-3 py-4 text-slate-500">
                Sin tarifas cargadas. Una franja sin tarifa no se puede reservar.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {actual !== null && (
        <FormularioDeTarifa
          abierto={abierto}
          tarifa={editando}
          canchas={deLaSucursal}
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
