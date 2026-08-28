/** Lo que comparten la lista de torneos y el detalle.
 *
 * Vive acá y no duplicado en las dos pantallas porque el estado de un torneo se
 * dibuja igual en los dos lados, y dos copias de la misma tabla de nombres
 * terminan diciendo cosas distintas.
 */
import type { FormatoTorneo, PartidoDeTorneo, TorneoEnLista } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

export const NOMBRE_DE_FORMATO: Record<FormatoTorneo, string> = {
  eliminacion: 'Eliminación directa',
  liga: 'Todos contra todos',
  zonas: 'Zonas y playoff',
}

/** La pastilla de estado, con la misma variante que el resto de la familia.
 *
 * 🔑 **«En curso» no es un estado guardado: se deriva.** El backend guarda
 * `sorteado` y acá se mira si ya hay algún partido jugado. Un estado más en la
 * base habría que acordarse de moverlo en cada carga de resultado, y el día que
 * alguien se olvide diría «sorteado» con media llave jugada.
 */
export function EstadoDelTorneo({
  torneo,
}: {
  torneo: Pick<TorneoEnLista, 'estado' | 'jugados'>
}) {
  if (torneo.estado === 'cancelado') {
    return <Badge variant="destructive">Cancelado</Badge>
  }
  if (torneo.estado === 'finalizado') return <Badge>Finalizado</Badge>
  if (torneo.estado === 'armado') return <Badge variant="outline">Inscribiendo</Badge>
  return (
    <Badge variant="secondary">{torneo.jugados > 0 ? 'En curso' : 'Sorteado'}</Badge>
  )
}

/** El resultado de un partido en una línea: `6-4 6-3`. Vacío si no se jugó. */
export function marcador(partido: PartidoDeTorneo): string {
  return partido.parciales.map((p) => `${p.puntos_a}-${p.puntos_b}`).join('  ')
}

/** Cómo se muestra un lugar del cuadro que todavía no tiene dueño.
 *
 * 🔑 Dice **«a definir»** y no queda en blanco: un casillero vacío se lee como
 * un error de carga, y en un cuadro con byes hay varios desde el minuto cero.
 */
export function nombreDe(nombre: string | null): string {
  return nombre ?? 'a definir'
}
