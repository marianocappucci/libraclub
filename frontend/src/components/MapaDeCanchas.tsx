/**
 * El mapa de canchas de la Caja: qué está pasando en cada cancha, ahora.
 *
 * 🔑 **Es el mapa de mesas de Restolibra, aplicado a canchas.** Lo pidió el
 * humano con esas palabras el 2026-08-28 —*"cada turno de cada cancha lo tenemos
 * que pensar como una mesa libre u ocupada en Restolibra"*—, pero esa vuelta se
 * tomó el modelo conceptual (la cuenta de la cancha es la unidad de trabajo) y
 * **no la pantalla**: quedó una lista de renglones donde Restolibra tiene una
 * grilla de tarjetas. El 2026-08-29 el humano volvió sobre eso: *"queda muy
 * vacía, no sé, es rara"*.
 *
 * 🔴 **La diferencia que importa no es el formato, es QUÉ se muestra.** La lista
 * anterior sólo dibujaba las canchas que **ya debían plata** —lo que devuelve
 * `/agenda/por-cobrar`—, así que un complejo de seis canchas con dos cuentas
 * abiertas mostraba dos renglones y el resto de la pantalla en blanco. Las
 * libres, las que están jugando y las ya cobradas no existían. El mostrador
 * necesita ver el complejo, no sólo la deuda.
 *
 * ⚠️ **Lo que NO entra acá, y es una restricción del humano, no un olvido:**
 * *"lo que la caja mueva entre todas las canchas no tiene por qué verse ahí"*
 * (2026-08-28). El mapa muestra el estado de cada cancha; el detalle de
 * movimientos sigue viviendo en `/caja/movimientos`.
 */
import { useMemo } from 'react'
import { Clock } from 'lucide-react'

import type { Cancha, Turno, TurnoPorCobrar } from '@/lib/api'
import { hora, pesos } from '@/lib/fechas'

/** En qué anda una cancha ahora mismo.
 *
 *  El orden de esta lista **es** la prioridad con la que se decide: una cancha
 *  que debe plata se muestra como «a cobrar» aunque además esté jugando el
 *  turno siguiente, porque cobrar es lo que el mostrador tiene pendiente.
 */
export type EstadoDeCancha = 'a-cobrar' | 'jugando' | 'reservada' | 'libre'

export interface CanchaDelMapa {
  cancha: Cancha
  estado: EstadoDeCancha
  /** Lo que falta cobrar en esa cancha hoy, sumando todas sus cuentas. */
  pendiente: number
  /** Las cuentas por cobrar de esa cancha. Puede haber más de una: dos turnos
   *  del día pueden quedar sin cerrar, y en la lista anterior aparecían como
   *  dos renglones con el mismo nombre de cancha. */
  cuentas: TurnoPorCobrar[]
  /** El turno que ocupa la cancha en este momento, si hay alguno. */
  enCurso: Turno | null
  /** El próximo turno ocupado de hoy, si la cancha está libre ahora. */
  proximo: Turno | null
}

/** ¿Está ocupado ese hueco de la grilla?
 *
 *  🔴 **Un bloqueo NO es un turno ocupado a estos efectos.** La grilla lo marca
 *  como no libre —la cancha no se puede reservar—, pero en la Caja «jugando»
 *  significa que hay gente adentro que después va a pagar. Un bloqueo por
 *  mantenimiento mostrado como jugando manda al encargado a cobrarle a nadie.
 */
function estaJugando(t: Turno): boolean {
  return !t.libre && t.estado !== 'bloqueo' && t.estado !== 'cancelada'
}

/**
 * Arma el mapa: una entrada por cancha, con su estado y sus cuentas.
 *
 * Función pura y exportada **a propósito**: es la única parte de esta pantalla
 * que tiene reglas, y probarla sin DOM es lo que permite cubrir los casos que
 * un test de render no llega a montar —dos cuentas en la misma cancha, el
 * bloqueo que no es «jugando», el turno que terminó y todavía debe—.
 *
 * @param ahora El instante contra el que se decide. Se pasa y no se lee de
 *   `new Date()` adentro: si no, el test se mueve junto con la app y un error
 *   de comparación de horarios queda invisible.
 */
export function armarMapa(
  canchas: Cancha[],
  turnosPorCancha: Record<string, Turno[]>,
  cuentas: TurnoPorCobrar[],
  ahora: Date,
): CanchaDelMapa[] {
  const t = ahora.getTime()
  return canchas.map((cancha) => {
    const delDia = turnosPorCancha[String(cancha.id)] ?? []
    const suyas = cuentas.filter((c) => c.cancha_id === cancha.id)
    const pendiente = suyas.reduce((a, c) => a + c.pendiente, 0)

    const enCurso = delDia.find(
      (x) =>
        estaJugando(x)
        && new Date(x.comienza_at).getTime() <= t
        && new Date(x.termina_at).getTime() > t,
    ) ?? null

    const proximo = delDia
      .filter((x) => estaJugando(x) && new Date(x.comienza_at).getTime() > t)
      .sort((a, b) => a.comienza_at.localeCompare(b.comienza_at))[0] ?? null

    const estado: EstadoDeCancha = pendiente > 0
      ? 'a-cobrar'
      : enCurso
        ? 'jugando'
        : proximo
          ? 'reservada'
          : 'libre'

    return { cancha, estado, pendiente, cuentas: suyas, enCurso, proximo }
  })
}

/** El color de cada estado.
 *
 *  🔑 **Sigue la paleta de dominio que ya usa la grilla de la Agenda** —ámbar lo
 *  que falta cerrar, esmeralda lo confirmado— en vez de inventar una. Dos
 *  pantallas del mismo producto diciendo cosas distintas con el mismo color es
 *  peor que no tener color.
 *
 *  «Libre» va con tokens del tema y borde punteado, y no con el gris de Tailwind
 *  que usa la Agenda para lo que ya pasó: acá libre no es «terminado», es «no
 *  hay nada», y el punteado lo dice sin gastar un color.
 */
const COLOR: Record<EstadoDeCancha, string> = {
  'a-cobrar': 'border-amber-400 bg-amber-50 dark:bg-amber-950/30',
  jugando: 'border-emerald-400 bg-emerald-50 dark:bg-emerald-950/30',
  reservada: 'border-sky-400 bg-sky-50 dark:bg-sky-950/30',
  libre: 'border-dashed border-input bg-card',
}

const NOMBRE: Record<EstadoDeCancha, string> = {
  'a-cobrar': 'A cobrar',
  jugando: 'Jugando',
  reservada: 'Reservada',
  libre: 'Libre',
}

const PUNTO: Record<EstadoDeCancha, string> = {
  'a-cobrar': 'bg-amber-400',
  jugando: 'bg-emerald-400',
  reservada: 'bg-sky-400',
  libre: 'border border-input bg-transparent',
}

export function MapaDeCanchas({ canchas, turnosPorCancha, cuentas, ahora, elegida, onElegir }: {
  canchas: Cancha[]
  turnosPorCancha: Record<string, Turno[]>
  cuentas: TurnoPorCobrar[]
  ahora: Date
  /** La cancha abierta, por id. */
  elegida: number | null
  onElegir: (canchaId: number | null) => void
}) {
  const mapa = useMemo(
    () => armarMapa(canchas, turnosPorCancha, cuentas, ahora),
    [canchas, turnosPorCancha, cuentas, ahora],
  )

  if (mapa.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Esta sucursal no tiene canchas cargadas.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {/* La leyenda arriba y no en un tooltip: son cuatro colores que el
          encargado tiene que poder leer sin aprenderlos. Mismo criterio que el
          mapa de mesas. */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {(Object.keys(NOMBRE) as EstadoDeCancha[]).map((e) => (
          <span key={e} className="flex items-center gap-1.5">
            <span className={`size-2.5 rounded-full ${PUNTO[e]}`} />
            {NOMBRE[e]}
          </span>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {mapa.map((m) => {
          const abierta = m.cancha.id === elegida
          // Sólo se puede entrar a cobrar donde hay algo que cobrar. Una cancha
          // libre no abre nada: sería un panel vacío detrás de un click.
          const cobrable = m.cuentas.length > 0
          const referencia = m.cuentas[0] ?? null
          return (
            <button
              key={m.cancha.id}
              type="button"
              disabled={!cobrable}
              aria-pressed={abierta}
              onClick={() => onElegir(abierta ? null : m.cancha.id)}
              className={
                'grid gap-1 rounded-lg border-2 p-2.5 text-left transition '
                + COLOR[m.estado]
                + (abierta ? ' ring-2 ring-primary' : '')
                + (cobrable ? ' hover:shadow-md' : ' cursor-default')
              }
            >
              <div className="flex items-baseline justify-between gap-1">
                <span className="truncate text-sm font-semibold">{m.cancha.nombre}</span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {NOMBRE[m.estado]}
                </span>
              </div>

              {/* La hora y el nombre de quien está: es lo que el encargado
                  contrasta con la persona que tiene enfrente. */}
              <div className="min-h-4 truncate text-xs text-muted-foreground">
                {referencia
                  ? `${hora(referencia.comienza_at)} · ${referencia.cliente}`
                  : m.enCurso
                    ? `${hora(m.enCurso.comienza_at)} · ${m.enCurso.cliente ?? 'sin nombre'}`
                    : m.proximo
                      ? `${hora(m.proximo.comienza_at)} · ${m.proximo.cliente ?? 'sin nombre'}`
                      : '—'}
              </div>

              {m.pendiente > 0 ? (
                <div className="flex items-baseline justify-between gap-1">
                  <span className="text-sm font-medium tabular-nums">
                    {pesos(m.pendiente)}
                  </span>
                  {/* Dos cuentas en la misma cancha pasa —dos turnos del día sin
                      cerrar— y el importe de arriba es la suma. Sin este contador
                      el encargado cobra una y no entiende por qué la tarjeta
                      sigue en ámbar. */}
                  {m.cuentas.length > 1 && (
                    <span className="text-xs text-muted-foreground">
                      {m.cuentas.length} cuentas
                    </span>
                  )}
                </div>
              ) : m.enCurso ? (
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Clock className="size-3" /> hasta {hora(m.enCurso.termina_at)}
                </div>
              ) : (
                <div className="min-h-5" />
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
