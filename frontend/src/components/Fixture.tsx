/** El fixture: el cuadro de llaves y las fechas de la fase de grupos.
 *
 * Los dos se dibujan acá porque un torneo por zonas tiene las dos cosas al
 * mismo tiempo, y quien lo mira necesita verlas juntas.
 */
import { CalendarClock, MapPin, Trophy } from 'lucide-react'

import type { Fixture as DatosDelFixture, PartidoDeTorneo } from '@/lib/api'
import { fecha, hora } from '@/lib/fechas'
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

/** El cuadro de eliminación, una columna por ronda.
 *
 * 🔑 **`justify-around` en cada columna, no posiciones absolutas.** Un bracket
 * dibujado con coordenadas hay que recalcularlo cuando cambia la altura de una
 * tarjeta, y con byes las rondas no tienen la misma cantidad de partidos. Que
 * cada columna reparta su espacio sola da la forma de embudo sin ninguna
 * cuenta, y aguanta que un partido crezca porque tiene resultado y cancha.
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
  const columnas = Array.from({ length: rondas }, (_, i) =>
    partidos.filter((p) => p.ronda === i + 1),
  )
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">Llaves</h3>
      {/* El cuadro scrollea solo: con 16 competidores son cuatro columnas y en
          un teléfono no entran. Lo que no puede pasar es que scrollee la
          página entera. */}
      <div className="overflow-x-auto pb-2">
        <div className="flex min-h-[16rem] gap-3">
          {columnas.map((deLaRonda, indice) => (
            <div
              key={indice}
              className="flex min-w-[15rem] flex-1 flex-col justify-around gap-3"
            >
              <h4 className="text-xs font-medium text-muted-foreground">
                {deLaRonda[0]?.instancia ?? ''}
              </h4>
              {deLaRonda.map((partido) => (
                <Partido key={partido.id} partido={partido} onAbrir={onAbrir} />
              ))}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

/** Una tarjeta de partido: quiénes juegan, dónde, cuándo y cómo salió. */
function Partido({
  partido,
  onAbrir,
}: {
  partido: PartidoDeTorneo
  onAbrir: (partido: PartidoDeTorneo) => void
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
      className="w-full rounded-lg border bg-card p-2 text-left text-sm hover:border-primary"
    >
      <Lado
        nombre={partido.competidor_a}
        gana={partido.finalizado && partido.ganador_id === partido.competidor_a_id}
      />
      <Lado
        nombre={partido.competidor_b}
        gana={partido.finalizado && partido.ganador_id === partido.competidor_b_id}
      />
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {resultado && <span className="font-medium text-foreground">{resultado}</span>}
        {partido.finalizado && !partido.ganador_id && <span>Empate</span>}
        {partido.comienza_at && (
          <span className="flex items-center gap-1">
            <CalendarClock className="size-3" />
            {fecha(partido.comienza_at)} {hora(partido.comienza_at)}
          </span>
        )}
        {partido.cancha && (
          <span className="flex items-center gap-1">
            <MapPin className="size-3" />
            {partido.cancha}
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
