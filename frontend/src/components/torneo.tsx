/** Lo que comparten la lista de torneos y el detalle.
 *
 * Vive acá y no duplicado en las dos pantallas porque el estado de un torneo se
 * dibuja igual en los dos lados, y dos copias de la misma tabla de nombres
 * terminan diciendo cosas distintas.
 */
import type { FormatoTorneo, PartidoDeTorneo, Torneo, TorneoEnLista } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

export const NOMBRE_DE_FORMATO: Record<FormatoTorneo, string> = {
  eliminacion: 'Eliminación directa',
  liga: 'Todos contra todos',
  zonas: 'Por zonas',
}

/** El formato en una frase, con lo que pasa después de las zonas. */
export function nombreDelFormato(
  torneo: Pick<Torneo, 'formato' | 'termina_en_zonas'>,
): string {
  if (torneo.formato !== 'zonas') return NOMBRE_DE_FORMATO[torneo.formato]
  return torneo.termina_en_zonas ? 'Por zonas, sin llaves' : 'Por zonas y llaves'
}

/** Las tres formas de jugar un partido de pádel o de tenis en un americano.
 *
 * 🔑 Son una combinación de dos columnas del backend —`sets_para_ganar` y
 * `games_por_set`— que la pantalla presenta como una sola decisión: nadie
 * piensa «un set, a 9 games» como dos datos. */
export const MODALIDADES_DE_PARTIDO = [
  {
    clave: 'un-set-6',
    nombre: 'Un set a 6 games',
    ayuda: 'Se gana 6-0 a 6-4, 7-5 o 7-6 (tie-break en 6-6).',
    sets_para_ganar: 1,
    games_por_set: 6,
  },
  {
    clave: 'un-set-9',
    nombre: 'Un set a 9 games',
    ayuda: 'Se gana de 9-0 a 9-7 y, con tie-break en 8-8, 9-8.',
    sets_para_ganar: 1,
    games_por_set: 9,
  },
  {
    clave: 'mejor-de-3',
    nombre: 'Al mejor de 3 sets',
    ayuda: 'Cada set a 6 games, con tie-break en 6-6. Gana el primero que llega a 2 sets.',
    sets_para_ganar: 2,
    games_por_set: 6,
  },
] as const

/** Los deportes que se juegan por sets y games; en el resto, un parcial son goles o puntos. */
export const DEPORTES_DE_SETS = ['padel', 'tenis']

/** Cómo se juega cada partido, en una frase para la cabecera del torneo. */
export function comoSeJuega(
  torneo: Pick<Torneo, 'sets_para_ganar' | 'games_por_set'>,
): string {
  const modalidad = MODALIDADES_DE_PARTIDO.find(
    (m) =>
      m.sets_para_ganar === torneo.sets_para_ganar &&
      m.games_por_set === torneo.games_por_set,
  )
  if (modalidad) return modalidad.nombre
  if (torneo.sets_para_ganar === 1) return 'Un solo resultado'
  return `Al mejor de ${torneo.sets_para_ganar * 2 - 1} sets`
}

/** El título de la grilla y de la hoja impresa: el torneo y su categoría. */
export function tituloDelTorneo(
  torneo: Pick<Torneo, 'nombre' | 'categoria'>,
): string {
  const { nombre, categoria } = torneo
  if (!categoria || nombre.toLowerCase().includes(categoria.toLowerCase())) return nombre
  return `${nombre} · ${categoria}`
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
