/** Qué pasó al generar una cancha fija: cuántas entraron y cuáles no.
 *
 * 🔴 **Es la mitad que hace que la pantalla sirva.** Una serie de los martes
 * puede crear once ocurrencias y saltear tres, y si sólo se dijera "listo" el
 * operador se entera el martes que falta — cuando el grupo llega y el turno no
 * existe. El backend devuelve las salteadas **con el motivo** justamente para
 * esto.
 */
import { AlertTriangle, CheckCircle2 } from 'lucide-react'

import type { Salteada } from '@/lib/api'
import { fecha, hora } from '@/lib/fechas'

/** Qué hacer con cada motivo. El texto manda a la pantalla que lo arregla:
 *  "no se pudo" a secas deja al operador adivinando cuál de las tres es. */
const MOTIVOS: Record<string, { titulo: string; queHacer: string }> = {
  sin_tarifa: {
    titulo: 'Sin tarifa cargada',
    queHacer: 'Cargá la tarifa de esa franja en Tarifas y volvé a extender.',
  },
  fuera_de_horario: {
    titulo: 'Fuera del horario de atención',
    queHacer: 'Revisá Horario de atención, o movelas a mano desde la agenda.',
  },
  ocupada: {
    titulo: 'La cancha ya estaba ocupada',
    queHacer: 'Miralas en la agenda: puede ser un torneo, un bloqueo o el turno ya vendido.',
  },
}

export function ResultadoDeSerie({
  creadas,
  salteadas,
}: {
  creadas: number
  salteadas: Salteada[]
}) {
  // Agrupadas por motivo: doce fechas sueltas no se leen, y las tres causas se
  // arreglan en pantallas distintas.
  const porMotivo = new Map<string, Salteada[]>()
  for (const s of salteadas) {
    porMotivo.set(s.motivo, [...(porMotivo.get(s.motivo) ?? []), s])
  }

  return (
    <div className="space-y-2 text-sm">
      <div className="flex items-center gap-2">
        <CheckCircle2 className="size-4 text-emerald-600 dark:text-emerald-500" />
        <span>
          <strong>{creadas}</strong> {creadas === 1 ? 'turno generado' : 'turnos generados'}
        </span>
      </div>

      {[...porMotivo].map(([motivo, fechas]) => {
        const info = MOTIVOS[motivo] ?? { titulo: motivo, queHacer: '' }
        return (
          <div
            key={motivo}
            className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <div className="space-y-1">
              <div>
                <strong>{fechas.length}</strong>{' '}
                {fechas.length === 1 ? 'salteado' : 'salteados'} — {info.titulo}
              </div>
              {/* Las fechas concretas, no sólo el conteo: "3 salteados" obliga a
                  buscarlos uno por uno en la agenda. */}
              <div className="text-muted-foreground">
                {fechas
                  .map((f) => `${fecha(f.comienza_at)} ${hora(f.comienza_at)}`)
                  .join(' · ')}
              </div>
              {info.queHacer && <div className="text-muted-foreground">{info.queHacer}</div>}
            </div>
          </div>
        )
      })}

      {creadas === 0 && salteadas.length === 0 && (
        <p className="text-muted-foreground">
          No había ninguna fecha para generar en ese período.
        </p>
      )}
    </div>
  )
}
