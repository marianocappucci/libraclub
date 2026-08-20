import { useEffect, useState } from 'react'
import { Modal } from '@/components/Modal'
import { canchas as api } from '@/lib/api'
import type { Cancha, CanchaEntrada } from '@/lib/api'

const DEPORTES = ['padel', 'futbol', 'tenis', 'basquet', 'voley', 'hockey', 'otro']

function vacia(sucursalId: number): CanchaEntrada {
  return {
    sucursal_id: sucursalId,
    nombre: '',
    deporte: 'padel',
    duracion_turno_min: 90,
    techada: false,
    iluminacion: true,
    superficie: null,
    orden: 0,
    activa: true,
    observaciones: null,
  }
}

export function FormularioDeCancha({
  abierto,
  cancha,
  sucursalId,
  onCerrar,
  onGuardada,
}: {
  abierto: boolean
  /** `null` = alta. Con una cancha, es edición. */
  cancha: Cancha | null
  sucursalId: number
  onCerrar: () => void
  onGuardada: () => void
}) {
  const [datos, setDatos] = useState<CanchaEntrada>(() => vacia(sucursalId))
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    // 🔴 En edición se copian **todos** los campos de la fila, no sólo los que
    // el formulario muestra. El endpoint es un PUT que reemplaza la fila entera:
    // lo que no viaje vuelve al default del schema, y una cancha techada dejaría
    // de serlo sin que nadie la haya tocado.
    setDatos(
      cancha
        ? {
            sucursal_id: cancha.sucursal_id,
            nombre: cancha.nombre,
            deporte: cancha.deporte,
            duracion_turno_min: cancha.duracion_turno_min,
            techada: cancha.techada,
            iluminacion: cancha.iluminacion,
            superficie: cancha.superficie,
            orden: cancha.orden,
            activa: cancha.activa,
            observaciones: cancha.observaciones,
          }
        : vacia(sucursalId),
    )
  }, [abierto, cancha, sucursalId])

  function set<K extends keyof CanchaEntrada>(campo: K, valor: CanchaEntrada[K]) {
    setDatos((d) => ({ ...d, [campo]: valor }))
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      if (!datos.nombre.trim()) throw new Error('La cancha necesita un nombre.')
      const cuerpo = {
        ...datos,
        nombre: datos.nombre.trim(),
        superficie: datos.superficie?.trim() || null,
        observaciones: datos.observaciones?.trim() || null,
      }
      if (cancha) await api.editar(cancha.id, cuerpo)
      else await api.crear(cuerpo)
      onGuardada()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Modal
      abierto={abierto}
      titulo={cancha ? `Editar ${cancha.nombre}` : 'Nueva cancha'}
      onCerrar={onCerrar}
    >
      <form onSubmit={enviar} className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm text-slate-600">Nombre</span>
          <input
            className="w-full rounded-md border border-slate-300 px-3 py-2"
            value={datos.nombre}
            onChange={(e) => set('nombre', e.target.value)}
          />
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="space-y-1">
            <span className="text-sm text-slate-600">Deporte</span>
            <select
              className="w-full rounded-md border border-slate-300 px-2 py-2"
              value={datos.deporte}
              onChange={(e) => set('deporte', e.target.value)}
            >
              {DEPORTES.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-sm text-slate-600">Minutos por turno</span>
            <input
              type="number"
              min={1}
              max={480}
              className="w-full rounded-md border border-slate-300 px-3 py-2"
              value={datos.duracion_turno_min}
              onChange={(e) => set('duracion_turno_min', Number(e.target.value))}
            />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <label className="space-y-1">
            <span className="text-sm text-slate-600">Superficie</span>
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2"
              value={datos.superficie ?? ''}
              onChange={(e) => set('superficie', e.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="text-sm text-slate-600">Orden en la grilla</span>
            <input
              type="number"
              className="w-full rounded-md border border-slate-300 px-3 py-2"
              value={datos.orden}
              onChange={(e) => set('orden', Number(e.target.value))}
            />
          </label>
        </div>

        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={datos.techada}
              onChange={(e) => set('techada', e.target.checked)}
            />
            Techada
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={datos.iluminacion}
              onChange={(e) => set('iluminacion', e.target.checked)}
            />
            Con luz
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={datos.activa}
              onChange={(e) => set('activa', e.target.checked)}
            />
            Activa
          </label>
        </div>

        <label className="block space-y-1">
          <span className="text-sm text-slate-600">Observaciones</span>
          <input
            className="w-full rounded-md border border-slate-300 px-3 py-2"
            value={datos.observaciones ?? ''}
            onChange={(e) => set('observaciones', e.target.value)}
          />
        </label>

        {error && (
          <p
            role="alert"
            className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
          >
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onCerrar}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-100"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={enviando}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {enviando ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
