import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { tarifas as api } from '@/lib/api'
import type { Cancha, Tarifa, TarifaEntrada } from '@/lib/api'
import { pesos } from '@/lib/fechas'

const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

const ALCANCES = [
  { valor: 'todos', texto: 'Todos los días' },
  { valor: 'dia_semana', texto: 'Un día de la semana' },
  { valor: 'feriado', texto: 'Feriados' },
] as const

function vacia(sucursalId: number): TarifaEntrada {
  return {
    sucursal_id: sucursalId,
    cancha_id: null,
    nombre: '',
    alcance_dia: 'todos',
    dia_semana: null,
    hora_desde: '08:00',
    hora_hasta: '18:00',
    precio: '',
    sena_porcentaje: 0,
    vigente_desde: null,
    vigente_hasta: null,
    prioridad: 0,
    activa: true,
  }
}

export function FormularioDeTarifa({
  abierto,
  tarifa,
  canchas,
  sucursalId,
  onCerrar,
  onGuardada,
}: {
  abierto: boolean
  /** `null` = alta. */
  tarifa: Tarifa | null
  canchas: Cancha[]
  sucursalId: number
  onCerrar: () => void
  onGuardada: () => void
}) {
  const [datos, setDatos] = useState<TarifaEntrada>(() => vacia(sucursalId))
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    setDatos(
      tarifa
        ? {
            sucursal_id: tarifa.sucursal_id,
            cancha_id: tarifa.cancha_id,
            nombre: tarifa.nombre,
            alcance_dia: tarifa.alcance_dia,
            dia_semana: tarifa.dia_semana,
            // El backend devuelve `HH:MM:SS` y un `<input type="time">` sólo
            // acepta `HH:MM`: sin recortar, el campo aparece vacío y el operador
            // cree que la tarifa no tenía horario.
            hora_desde: tarifa.hora_desde.slice(0, 5),
            hora_hasta: tarifa.hora_hasta.slice(0, 5),
            precio: tarifa.precio,
            sena_porcentaje: tarifa.sena_porcentaje,
            vigente_desde: tarifa.vigente_desde,
            vigente_hasta: tarifa.vigente_hasta,
            prioridad: tarifa.prioridad,
            activa: tarifa.activa,
          }
        : vacia(sucursalId),
    )
  }, [abierto, tarifa, sucursalId])

  function set<K extends keyof TarifaEntrada>(campo: K, valor: TarifaEntrada[K]) {
    setDatos((d) => ({ ...d, [campo]: valor }))
  }

  /**
   * 🔴 Cambiar el alcance **limpia o completa** `dia_semana` en el mismo paso.
   *
   * La base tiene un CHECK y el schema un validador: `feriado` con día cargado
   * es 422, y `dia_semana` sin día también. Si el campo quedara con el valor
   * anterior al cambiar el select, el formulario mandaría un estado imposible y
   * el error hablaría de un campo que el operador no ve.
   */
  function cambiarAlcance(alcance: TarifaEntrada['alcance_dia']) {
    setDatos((d) => ({
      ...d,
      alcance_dia: alcance,
      dia_semana: alcance === 'dia_semana' ? (d.dia_semana ?? 0) : null,
    }))
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      if (!datos.nombre.trim()) throw new Error('La tarifa necesita un nombre.')
      if (datos.precio === '' || Number.isNaN(Number(datos.precio)))
        throw new Error('Poné un precio.')
      if (datos.hora_hasta <= datos.hora_desde)
        throw new Error('La franja tiene que terminar después de empezar.')

      const cuerpo: TarifaEntrada = {
        ...datos,
        nombre: datos.nombre.trim(),
        precio: Number(datos.precio).toFixed(2),
      }
      if (tarifa) await api.editar(tarifa.id, cuerpo)
      else await api.crear(cuerpo)
      onGuardada()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  const sena =
    datos.precio && !Number.isNaN(Number(datos.precio)) && datos.sena_porcentaje > 0
      ? pesos((Number(datos.precio) * datos.sena_porcentaje) / 100)
      : null

  // `onOpenChange` recibe el estado NUEVO. Se llama a `onCerrar` sólo cuando
  // llega `false`: el padre es quien tiene el estado y quien decide. Hoy nunca
  // llega `true` —ninguno de estos diálogos tiene `DialogTrigger`, los abre el
  // padre—, así que el `if` es defensivo. Ver la nota en `dialogos.test.tsx`
  // sobre por qué no se puede cubrir con un test.
  return (
    <Dialog open={abierto} onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{tarifa ? `Editar ${tarifa.nombre}` : 'Nueva tarifa'}</DialogTitle>
        </DialogHeader>
        <form onSubmit={enviar} className="space-y-3">
          <label className="block space-y-1">
            <span className="text-sm text-slate-600">Nombre</span>
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2"
              value={datos.nombre}
              onChange={(e) => set('nombre', e.target.value)}
            />
          </label>

          <label className="block space-y-1">
            <span className="text-sm text-slate-600">Cancha</span>
            <select
              className="w-full rounded-md border border-slate-300 px-2 py-2"
              value={datos.cancha_id ?? ''}
              onChange={(e) => set('cancha_id', e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Toda la sucursal</option>
              {canchas.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre}
                </option>
              ))}
            </select>
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="text-sm text-slate-600">Aplica</span>
              <select
                className="w-full rounded-md border border-slate-300 px-2 py-2"
                value={datos.alcance_dia}
                onChange={(e) =>
                  cambiarAlcance(e.target.value as TarifaEntrada['alcance_dia'])
                }
              >
                {ALCANCES.map((a) => (
                  <option key={a.valor} value={a.valor}>
                    {a.texto}
                  </option>
                ))}
              </select>
            </label>
            {datos.alcance_dia === 'dia_semana' && (
              <label className="space-y-1">
                <span className="text-sm text-slate-600">Día</span>
                <select
                  className="w-full rounded-md border border-slate-300 px-2 py-2"
                  value={datos.dia_semana ?? 0}
                  onChange={(e) => set('dia_semana', Number(e.target.value))}
                >
                  {DIAS.map((d, i) => (
                    <option key={d} value={i}>
                      {d}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="text-sm text-slate-600">Desde</span>
              <input
                type="time"
                className="w-full rounded-md border border-slate-300 px-3 py-2"
                value={datos.hora_desde}
                onChange={(e) => set('hora_desde', e.target.value)}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm text-slate-600">Hasta</span>
              <input
                type="time"
                className="w-full rounded-md border border-slate-300 px-3 py-2"
                value={datos.hora_hasta}
                onChange={(e) => set('hora_hasta', e.target.value)}
              />
            </label>
          </div>

          <div className="grid grid-cols-3 gap-2">
            <label className="space-y-1">
              <span className="text-sm text-slate-600">Precio</span>
              <input
                inputMode="decimal"
                className="w-full rounded-md border border-slate-300 px-3 py-2"
                value={datos.precio}
                onChange={(e) => set('precio', e.target.value)}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm text-slate-600">Seña %</span>
              <input
                type="number"
                min={0}
                max={100}
                className="w-full rounded-md border border-slate-300 px-3 py-2"
                value={datos.sena_porcentaje}
                onChange={(e) => set('sena_porcentaje', Number(e.target.value))}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm text-slate-600">Prioridad</span>
              <input
                type="number"
                className="w-full rounded-md border border-slate-300 px-3 py-2"
                value={datos.prioridad}
                onChange={(e) => set('prioridad', Number(e.target.value))}
              />
            </label>
          </div>

          {sena && <p className="text-sm text-slate-500">Seña: {sena}</p>}

          <p className="text-xs text-slate-500">
            Gana la de mayor prioridad. Con la misma prioridad, la más específica:
            feriado antes que día de semana, y una cancha antes que toda la sucursal.
          </p>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={datos.activa}
              onChange={(e) => set('activa', e.target.checked)}
            />
            Activa
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
      </DialogContent>
    </Dialog>
  )
}
