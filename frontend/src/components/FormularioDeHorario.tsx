import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { horarios as api } from '@/lib/api'
import type { Cancha, Franja, FranjaEntrada } from '@/lib/api'
import { Input } from '@/components/ui/input'
import { buttonVariants } from '@/components/ui/button'
import { AvisoDeError } from '@/components/listado'

const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

const ALCANCES = [
  { valor: 'todos', texto: 'Todos los días' },
  { valor: 'dia_semana', texto: 'Un día de la semana' },
  { valor: 'feriado', texto: 'Feriados' },
] as const

function vacia(sucursalId: number): FranjaEntrada {
  return {
    sucursal_id: sucursalId,
    cancha_id: null,
    alcance_dia: 'todos',
    dia_semana: null,
    abre: '08:00',
    cierra: '00:00',
    activa: true,
  }
}

/** Cuánto dura la franja, para mostrarlo mientras se carga.
 *
 * 🔑 **Es la única señal de que `cierra` menor que `abre` no es un error.** Un
 * operador que pone 16:00 → 02:00 necesita ver "10 horas" y no un cartel rojo:
 * sin esto va a asumir que el formulario está mal y va a cargar 16:00 → 23:59,
 * perdiendo las dos horas más caras del día.
 */
function duracion(abre: string, cierra: string): string | null {
  if (!abre || !cierra) return null
  const [ha, ma] = abre.split(':').map(Number)
  const [hc, mc] = cierra.split(':').map(Number)
  let minutos = hc * 60 + mc - (ha * 60 + ma)
  if (minutos <= 0) minutos += 24 * 60
  const horas = Math.floor(minutos / 60)
  const resto = minutos % 60
  const cruza = hc * 60 + mc <= ha * 60 + ma
  const texto = resto === 0 ? `${horas} h` : `${horas} h ${resto} min`
  return cruza ? `${texto} — cierra al día siguiente` : texto
}

export function FormularioDeHorario({
  abierto,
  franja,
  canchas,
  sucursalId,
  onCerrar,
  onGuardada,
}: {
  abierto: boolean
  /** `null` = alta. */
  franja: Franja | null
  canchas: Cancha[]
  sucursalId: number
  onCerrar: () => void
  onGuardada: () => void
}) {
  const [datos, setDatos] = useState<FranjaEntrada>(() => vacia(sucursalId))
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    setDatos(
      franja
        ? {
            sucursal_id: franja.sucursal_id,
            cancha_id: franja.cancha_id,
            alcance_dia: franja.alcance_dia,
            dia_semana: franja.dia_semana,
            // El backend devuelve `HH:MM:SS` y un `<input type="time">` sólo
            // acepta `HH:MM`: sin recortar, el campo aparece vacío y el
            // operador cree que la franja no tenía horario.
            abre: franja.abre.slice(0, 5),
            cierra: franja.cierra.slice(0, 5),
            activa: franja.activa,
          }
        : vacia(sucursalId),
    )
  }, [abierto, franja, sucursalId])

  function set<K extends keyof FranjaEntrada>(campo: K, valor: FranjaEntrada[K]) {
    setDatos((d) => ({ ...d, [campo]: valor }))
  }

  /** Mismo par que en el formulario de tarifa: cambiar el alcance limpia o
   *  completa `dia_semana` en el mismo paso, porque el CHECK de la base
   *  rechaza `feriado` con día y `dia_semana` sin él. */
  function cambiarAlcance(alcance: FranjaEntrada['alcance_dia']) {
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
      // 🔑 **No se valida `cierra > abre`.** Es lo que sí valida la tarifa, y
      // acá sería el bug: prohibiría el complejo que cierra a las 02:00.
      if (!datos.abre || !datos.cierra) throw new Error('Poné los dos horarios.')
      if (franja) await api.editar(franja.id, datos)
      else await api.crear(datos)
      onGuardada()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  const cuanto = duracion(datos.abre, datos.cierra)

  return (
    <Dialog open={abierto} onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{franja ? 'Editar horario' : 'Nuevo horario'}</DialogTitle>
        </DialogHeader>
        <form onSubmit={enviar} className="space-y-3">
          <label className="block space-y-1">
            <span className="text-sm font-medium">Cancha</span>
            <select
              className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
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
              <span className="text-sm font-medium">Aplica</span>
              <select
                className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
                value={datos.alcance_dia}
                onChange={(e) =>
                  cambiarAlcance(e.target.value as FranjaEntrada['alcance_dia'])
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
                <span className="text-sm font-medium">Día</span>
                <select
                  className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
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
              <span className="text-sm font-medium">Abre</span>
              <Input
                type="time"
                value={datos.abre}
                onChange={(e) => set('abre', e.target.value)}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm font-medium">Cierra</span>
              <Input
                type="time"
                value={datos.cierra}
                onChange={(e) => set('cierra', e.target.value)}
              />
            </label>
          </div>
          {cuanto && <p className="text-sm text-muted-foreground">Abierto {cuanto}.</p>}

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={datos.activa}
              onChange={(e) => set('activa', e.target.checked)}
            />
            Activa
          </label>

          <AvisoDeError mensaje={error} />

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onCerrar}
              className={buttonVariants({ variant: 'outline' })}
            >
              Cancelar
            </button>
            <button type="submit" disabled={enviando} className={buttonVariants()}>
              {enviando ? 'Guardando…' : 'Guardar'}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
