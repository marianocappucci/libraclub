import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { series as api } from '@/lib/api'
import type { Cancha, Cliente, SerieCreada, SerieEntrada } from '@/lib/api'
import { Input } from '@/components/ui/input'
import { buttonVariants } from '@/components/ui/button'
import { AvisoDeError } from '@/components/listado'
import { ResultadoDeSerie } from '@/components/ResultadoDeSerie'

const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

function hoy(): string {
  return new Date().toISOString().slice(0, 10)
}

function vacia(): SerieEntrada {
  return {
    cancha_id: 0,
    cliente_id: 0,
    dia_semana: 1,
    hora: '20:00',
    duracion_min: 90,
    desde: hoy(),
    hasta: null,
  }
}

/** Alta de una cancha fija.
 *
 * 🔑 **El diálogo no se cierra al guardar.** Muestra qué se generó y qué se
 * salteó, y recién ahí el operador cierra. Cerrarlo de una haría desaparecer lo
 * único que dice si la cancha fija quedó completa — y eso se descubriría el
 * martes que falta, con el grupo en la puerta.
 */
export function FormularioDeSerie({
  abierto,
  canchas,
  clientes,
  onCerrar,
  onCreada,
}: {
  abierto: boolean
  canchas: Cancha[]
  clientes: Cliente[]
  onCerrar: () => void
  onCreada: () => void
}) {
  const [datos, setDatos] = useState<SerieEntrada>(vacia)
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [resultado, setResultado] = useState<SerieCreada | null>(null)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    setResultado(null)
    setDatos({
      ...vacia(),
      cancha_id: canchas[0]?.id ?? 0,
      cliente_id: clientes[0]?.id ?? 0,
    })
  }, [abierto, canchas, clientes])

  function set<K extends keyof SerieEntrada>(campo: K, valor: SerieEntrada[K]) {
    setDatos((d) => ({ ...d, [campo]: valor }))
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      if (!datos.cancha_id) throw new Error('Elegí una cancha.')
      if (!datos.cliente_id) throw new Error('Elegí un cliente.')
      setResultado(await api.crear(datos))
      onCreada()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Dialog open={abierto} onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {resultado ? 'Cancha fija creada' : 'Nueva cancha fija'}
          </DialogTitle>
        </DialogHeader>

        {resultado ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              {DIAS[datos.dia_semana]} a las {datos.hora}, {resultado.serie.cancha},
              para {resultado.serie.cliente}.
            </p>
            <ResultadoDeSerie
              creadas={resultado.creadas.length}
              salteadas={resultado.salteadas}
            />
            <div className="flex justify-end">
              <button type="button" onClick={onCerrar} className={buttonVariants()}>
                Listo
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={enviar} className="space-y-3">
            <label className="block space-y-1">
              <span className="text-sm font-medium">Cliente</span>
              <select
                className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
                value={datos.cliente_id}
                onChange={(e) => set('cliente_id', Number(e.target.value))}
              >
                {clientes.map((c) => (
                  <option key={c.id} value={c.id}>{c.nombre}</option>
                ))}
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-sm font-medium">Cancha</span>
              <select
                className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
                value={datos.cancha_id}
                onChange={(e) => set('cancha_id', Number(e.target.value))}
              >
                {canchas.map((c) => (
                  <option key={c.id} value={c.id}>{c.nombre}</option>
                ))}
              </select>
            </label>

            <div className="grid grid-cols-3 gap-2">
              <label className="space-y-1">
                <span className="text-sm font-medium">Día</span>
                <select
                  className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
                  value={datos.dia_semana}
                  onChange={(e) => set('dia_semana', Number(e.target.value))}
                >
                  {DIAS.map((d, i) => (
                    <option key={d} value={i}>{d}</option>
                  ))}
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">Hora</span>
                <Input
                  type="time"
                  value={datos.hora}
                  onChange={(e) => set('hora', e.target.value)}
                />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">Minutos</span>
                <Input
                  inputMode="numeric"
                  value={datos.duracion_min}
                  onChange={(e) => set('duracion_min', Number(e.target.value))}
                />
              </label>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <label className="space-y-1">
                <span className="text-sm font-medium">Desde</span>
                <Input
                  type="date"
                  value={datos.desde}
                  onChange={(e) => set('desde', e.target.value)}
                />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">
                  Hasta <span className="text-muted-foreground">(opcional)</span>
                </span>
                <Input
                  type="date"
                  value={datos.hasta ?? ''}
                  onChange={(e) => set('hasta', e.target.value || null)}
                />
              </label>
            </div>
            {/* Se explica acá y no en la documentación: "sin fin" no significa
                que se generen infinitos turnos, y el operador tiene que saber
                que va a haber que extenderla. */}
            <p className="text-xs text-muted-foreground">
              Sin fecha de fin la cancha queda fija «hasta que avisen». Se generan
              los turnos de los próximos 90 días y después se extiende desde el
              listado.
            </p>

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
                {enviando ? 'Generando…' : 'Crear y generar turnos'}
              </button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
