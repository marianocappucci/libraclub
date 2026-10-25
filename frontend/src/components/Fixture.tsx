/** El fixture: el cuadro de llaves y las fechas de la fase de grupos.
 *
 * Los dos se dibujan acá porque un torneo por zonas tiene las dos cosas al
 * mismo tiempo, y quien lo mira necesita verlas juntas.
 */
import { CalendarClock, MapPin, Trophy } from 'lucide-react'

import type { Fixture as DatosDelFixture, PartidoDeTorneo } from '@/lib/api'
import { fecha, hora } from '@/lib/fechas'
import {
  ALTO_DE_FILA,
  ALTO_DE_PARTIDO,
  ALTO_DE_TITULO,
  ANCHO_DE_PARTIDO,
  anchoDelCuadro,
  disponerLlaves,
  trazoDelConector,
  xDeColumna,
  yEnRem,
} from '@/components/llaves'
import { marcador, nombreDe } from '@/components/torneo'
import { cn } from '@/lib/utils'

export function Fixture({
  fixture,
  onAbrir,
}: {
  fixture: DatosDelFixture
  onAbrir: (partido: PartidoDeTorneo) => void
}) {
  const grupos = fixture.partidos.filter((p) => p.etapa === 'grupos')
  const llaves = fixture.partidos.filter((p) => p.etapa === 'llaves')

  if (!fixture.partidos.length) {
    return (
      <p className="rounded-md border bg-card p-4 text-sm text-muted-foreground">
        Todavía no se sorteó. Cargá los competidores y sorteá el torneo para que
        aparezca el fixture.
      </p>
    )
  }

  return (
    <div className="space-y-6">
      {grupos.length > 0 && <Grupos partidos={grupos} onAbrir={onAbrir} />}
      {llaves.length > 0 && (
        <Llaves partidos={llaves} rondas={fixture.rondas} onAbrir={onAbrir} />
      )}
    </div>
  )
}

/** Las fechas de la fase de grupos, agrupadas por zona. */
function Grupos({
  partidos,
  onAbrir,
}: {
  partidos: PartidoDeTorneo[]
  onAbrir: (partido: PartidoDeTorneo) => void
}) {
  const porZona = new Map<string, PartidoDeTorneo[]>()
  for (const partido of partidos) {
    // La clave es el nombre de la zona, o vacío en una liga —que no tiene
    // zonas—: así el mismo componente sirve para los dos.
    const clave = partido.zona ?? ''
    porZona.set(clave, [...(porZona.get(clave) ?? []), partido])
  }

  return (
    <div className="space-y-4">
      {[...porZona.entries()].map(([zona, deLaZona]) => (
        <section key={zona} className="space-y-2">
          {zona && <h3 className="text-sm font-semibold">{zona}</h3>}
          {[...new Set(deLaZona.map((p) => p.ronda))].map((ronda) => (
            <div key={ronda} className="space-y-1">
              <h4 className="text-xs font-medium text-muted-foreground">
                Fecha {ronda}
              </h4>
              <ul className="space-y-1">
                {deLaZona
                  .filter((p) => p.ronda === ronda)
                  .map((partido) => (
                    <li key={partido.id}>
                      <Partido partido={partido} onAbrir={onAbrir} />
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </section>
      ))}
    </div>
  )
}

/** El color de las líneas: el del borde del tema, un poco más cerca del texto.
 *  Con el `--border` puro, en oscuro (blanco al 10%) las líneas casi no se ven,
 *  y son justo lo que este cuadro viene a mostrar. */
const COLOR_DE_LINEA = 'color-mix(in oklab, var(--border) 60%, var(--muted-foreground))'

/** El cuadro de eliminación: una columna por ronda y las líneas que unen cada
 * par de partidos con el que sigue, como un bracket de papel.
 *
 * 🔑 **Posiciones calculadas, no `justify-around`.** El reparto automático deja
 * el partido siguiente «más o menos» entre sus dos orígenes, y con byes ni eso:
 * las rondas no tienen la misma cantidad de partidos, así que cada columna
 * repartía distinto y las líneas no tenían dónde caer. Acá cada partido va a
 * la altura media exacta de los que lo alimentan (`disponerLlaves`, que lee
 * `avanza_a_id` y `avanza_a_slot`). Lo que hacía frágil a un bracket con
 * coordenadas —que una tarjeta crezca y haya que recalcular— se evita con el
 * alto fijo de la tarjeta (`ALTO_DE_PARTIDO`): lo que no entra se recorta en
 * una línea, y el detalle completo está en el diálogo que abre al tocarla.
 *
 * 🔑 **Un solo SVG para todas las líneas, detrás de las tarjetas.** Las
 * unidades del SVG son rem —el mismo `rem` con que se ubican las tarjetas—, así
 * que líneas y tarjetas no pueden desalinearse al cambiar el tamaño de letra.
 * Con byes el partido siguiente tiene un solo origen y la línea es recta; el que
 * entró directo no tiene línea (ver `llaves.ts`).
 */
function Llaves({
  partidos,
  rondas,
  onAbrir,
}: {
  partidos: PartidoDeTorneo[]
  rondas: number
  onAbrir: (partido: PartidoDeTorneo) => void
}) {
  const { nodos, conectores, filas } = disponerLlaves(partidos)
  const porId = new Map(nodos.map((n) => [n.partido.id, n]))
  const columnas = Math.max(rondas, ...nodos.map((n) => n.columna + 1))
  const ancho = anchoDelCuadro(columnas)
  const alto = filas * ALTO_DE_FILA
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">Llaves</h3>
      {/* El cuadro scrollea solo: con 16 competidores son cuatro columnas y en
          un teléfono no entran. Lo que no puede pasar es que scrollee la
          página entera. */}
      <div className="overflow-x-auto pb-2">
        <div
          data-testid="cuadro-de-llaves"
          className="relative"
          style={{ width: `${ancho}rem`, height: `${ALTO_DE_TITULO + alto}rem` }}
        >
          <svg
            aria-hidden="true"
            focusable="false"
            className="pointer-events-none absolute left-0"
            style={{ top: `${ALTO_DE_TITULO}rem`, width: `${ancho}rem`, height: `${alto}rem` }}
            viewBox={`0 0 ${ancho} ${alto}`}
          >
            {conectores.map((conector) => (
              <path
                key={conector.hacia}
                data-conector=""
                data-hacia={conector.hacia}
                data-desde={conector.desde.join(',')}
                d={trazoDelConector(conector, porId)}
                fill="none"
                stroke={COLOR_DE_LINEA}
                strokeWidth={1.5}
                strokeLinecap="square"
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>
          {Array.from({ length: columnas }, (_, columna) => {
            const deLaRonda = nodos
              .filter((n) => n.columna === columna)
              .sort((a, b) => a.y - b.y)
            return (
              <div
                key={columna}
                className="absolute top-0"
                style={{ left: `${xDeColumna(columna)}rem`, width: `${ANCHO_DE_PARTIDO}rem` }}
              >
                <h4
                  className="text-xs font-medium text-muted-foreground"
                  style={{ height: `${ALTO_DE_TITULO}rem` }}
                >
                  {deLaRonda[0]?.partido.instancia ?? ''}
                </h4>
                <ul>
                  {deLaRonda.map((nodo) => (
                    <li
                      key={nodo.partido.id}
                      data-partido={nodo.partido.id}
                      data-y={nodo.y}
                      data-origenes={nodo.origenes.join(',')}
                      className="absolute inset-x-0"
                      style={{
                        top: `${ALTO_DE_TITULO + yEnRem(nodo.y) - ALTO_DE_PARTIDO / 2}rem`,
                        height: `${ALTO_DE_PARTIDO}rem`,
                      }}
                    >
                      <Partido partido={nodo.partido} onAbrir={onAbrir} compacta />
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

/** Una tarjeta de partido: quiénes juegan, dónde, cuándo y cómo salió. */
function Partido({
  partido,
  onAbrir,
  compacta = false,
}: {
  partido: PartidoDeTorneo
  onAbrir: (partido: PartidoDeTorneo) => void
  /** En el cuadro de llaves: alto fijo (lo ponen las líneas) y una sola línea
   *  de detalle, recortada. */
  compacta?: boolean
}) {
  const resultado = marcador(partido)
  return (
    <button
      type="button"
      onClick={() => onAbrir(partido)}
      // 🔑 El nombre accesible lleva la instancia y los dos competidores. Sin
      // él, un cuadro de 16 son quince botones que un lector de pantalla
      // anuncia igual, y no hay forma de saber cuál se está por abrir.
      aria-label={`${partido.instancia}: ${nombreDe(partido.competidor_a)} contra ${nombreDe(partido.competidor_b)}`}
      className={cn(
        'w-full rounded-lg border bg-card p-2 text-left text-sm hover:border-primary',
        compacta && 'flex h-full flex-col justify-center overflow-hidden',
      )}
    >
      <Lado
        nombre={partido.competidor_a}
        gana={partido.finalizado && partido.ganador_id === partido.competidor_a_id}
      />
      <Lado
        nombre={partido.competidor_b}
        gana={partido.finalizado && partido.ganador_id === partido.competidor_b_id}
      />
      <div
        className={cn(
          'mt-1 flex items-center gap-x-3 text-xs text-muted-foreground',
          compacta ? 'h-4 min-w-0 flex-nowrap whitespace-nowrap' : 'flex-wrap gap-y-1',
        )}
      >
        {resultado && <span className="font-medium text-foreground">{resultado}</span>}
        {partido.finalizado && !partido.ganador_id && <span>Empate</span>}
        {partido.comienza_at && (
          <span className="flex items-center gap-1">
            <CalendarClock className="size-3" />
            {fecha(partido.comienza_at)} {hora(partido.comienza_at)}
          </span>
        )}
        {partido.cancha && (
          <span className="flex min-w-0 items-center gap-1" title={partido.cancha}>
            <MapPin className="size-3 shrink-0" />
            <span className="truncate">{partido.cancha}</span>
          </span>
        )}
        {/* 🔑 Se avisa que falta cancha sólo si el partido se puede jugar. Un
            cruce que todavía espera un ganador no está "sin programar": está
            esperando, y marcarlo daría trabajo que no existe. */}
        {!partido.comienza_at &&
          !partido.finalizado &&
          partido.competidor_a_id &&
          partido.competidor_b_id && <span>Sin cancha</span>}
      </div>
    </button>
  )
}

function Lado({ nombre, gana }: { nombre: string | null; gana: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span
        className={cn(
          'truncate',
          gana && 'font-semibold',
          !nombre && 'text-muted-foreground italic',
        )}
      >
        {nombreDe(nombre)}
      </span>
      {gana && <Trophy className="size-3 shrink-0 text-muted-foreground" />}
    </div>
  )
}
