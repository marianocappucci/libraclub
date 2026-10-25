/** La grilla de doble entrada de una zona, como se hace en un americano de club.
 *
 * Las parejas de la zona van en las filas y en las columnas; la diagonal —una
 * pareja no juega contra sí misma— queda rellena de rojo; y cada casillero dice
 * cómo le fue a **la pareja de la fila** contra la de la columna. Al costado
 * están las columnas de la tabla de posiciones, así que la hoja entera se puede
 * imprimir y pegar en la pared.
 *
 * 🔑 **Todo sale de datos que la pantalla ya tiene** —los partidos del fixture y
 * la tabla de posiciones—: la grilla es otra forma de mirarlos y no suma ninguna
 * llamada ni ningún estado que pueda desincronizarse.
 */
import { createPortal } from 'react-dom'
import { useEffect, useState } from 'react'
import { Printer, Trophy } from 'lucide-react'

import type { PartidoDeTorneo, TablaDeZona, Torneo } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { comoSeJuega, sujetoDelDeporte, tituloDelTorneo } from '@/components/torneo'
import { fecha, hora } from '@/lib/fechas'
import { cn } from '@/lib/utils'

/** Los parciales de un partido jugado, **desde el punto de vista de `filaId`**.
 *
 * 🔴 El partido guarda `puntos_a` y `puntos_b` según quién quedó de cada lado en
 * el sorteo. Si la pareja de la fila quedó del lado `b`, el `6-4` del partido es
 * un `4-6` para ella: dibujarlo sin dar vuelta el casillero le atribuiría a la
 * pareja de la fila una victoria que fue de la columna. */
export function parcialesDesdeLaFila(partido: PartidoDeTorneo, filaId: number): string[] {
  if (!partido.finalizado) return []
  const propio = partido.competidor_a_id === filaId
  return partido.parciales.map((p) =>
    propio ? `${p.puntos_a}-${p.puntos_b}` : `${p.puntos_b}-${p.puntos_a}`,
  )
}

/** El resultado en una línea: `6-4 3-6 7-5`. Vacío si no se jugó. */
export function resultadoDesdeLaFila(partido: PartidoDeTorneo, filaId: number): string {
  return parcialesDesdeLaFila(partido, filaId).join(' ')
}

/** El cruce entre dos parejas, sin importar de qué lado quedó cada una. */
export function cruceEntre(
  partidos: PartidoDeTorneo[],
  uno: number,
  otro: number,
): PartidoDeTorneo | undefined {
  return partidos.find(
    (p) =>
      (p.competidor_a_id === uno && p.competidor_b_id === otro) ||
      (p.competidor_a_id === otro && p.competidor_b_id === uno),
  )
}

function conSigno(n: number | null | undefined): string {
  if (n === null || n === undefined) return ''
  return n > 0 ? `+${n}` : String(n)
}

export function GrillaDeZona({
  tabla,
  partidos,
  clasifican,
  terminaEnZonas,
  onAbrir,
  paraPapel = false,
  deporte,
}: {
  tabla: TablaDeZona
  /** Los partidos de grupos **de esta zona**. */
  partidos: PartidoDeTorneo[]
  /** Cuántos pasan a llaves por zona; `null` si no hay llaves. */
  clasifican: number | null
  terminaEnZonas: boolean
  onAbrir: (partido: PartidoDeTorneo) => void
  /** Sin botones, para la hoja que se imprime. */
  paraPapel?: boolean
  /** Para nombrar a quienes juegan. Sin él, una tabla con sets son parejas. */
  deporte?: string
}) {
  const sujeto = sujetoDelDeporte(deporte ?? (tabla.con_sets ? 'padel' : undefined))
  // Las parejas en el orden en que se inscribieron, y no por la tabla: si las
  // filas se reordenaran con cada resultado, la hoja pegada en la pared no
  // coincidiría con la de ayer.
  const parejas = [...tabla.filas].sort((a, b) => a.competidor_id - b.competidor_id)
  const posicion = new Map(tabla.filas.map((f, i) => [f.competidor_id, i + 1]))
  const conSets = tabla.con_sets === true
  const campeon = terminaEnZonas && tabla.completa ? tabla.filas[0] : undefined

  return (
    <div className={cn('space-y-2', paraPapel && 'grilla-papel')}>
      {/* La grilla scrollea sola en pantalla angosta: con seis parejas son más
          de diez columnas y lo que no puede pasar es que scrollee la página. */}
      <div className={cn('rounded-lg border', !paraPapel && 'overflow-x-auto')}>
        <table className="grilla-de-zona w-full border-collapse text-sm">
          <caption className="sr-only">
            {tabla.nombre ?? 'Todos contra todos'}: resultado de cada {sujeto.nombre} de
            la fila contra {sujeto.articulo} de la columna
          </caption>
          <thead className="bg-muted/50 text-xs">
            <tr>
              <th scope="col" className="grilla-esquina p-2 text-left font-semibold uppercase">
                {tabla.nombre ?? 'Zona única'}
              </th>
              {parejas.map((pareja) => (
                <th
                  key={pareja.competidor_id}
                  scope="col"
                  className="min-w-[5.5rem] max-w-[8rem] border-l p-2 text-center font-medium"
                >
                  {pareja.nombre}
                </th>
              ))}
              {/* 🔑 La tabla de fútbol se ordena por puntos (ganar 3, empatar 1),
                  no por partidos ganados: con PG se vería un equipo de 0 PG
                  arriba de uno con 1 PG. Misma regla que `TablaDePosiciones`:
                  con sets, PG; sin sets, Pts. */}
              <th
                scope="col"
                className="border-l p-2 text-center font-medium"
                title={conSets ? 'Partidos ganados' : 'Puntos'}
              >
                {conSets ? 'PG' : 'Pts'}
              </th>
              {conSets && (
                <th scope="col" className="p-2 text-center font-medium" title="Diferencia de sets">
                  Sets
                </th>
              )}
              <th
                scope="col"
                className="p-2 text-center font-medium"
                title={conSets ? 'Diferencia de games' : 'Diferencia'}
              >
                {conSets ? 'Games' : 'Dif'}
              </th>
              <th scope="col" className="p-2 text-center font-medium" title="Posición">
                Pos.
              </th>
            </tr>
          </thead>
          <tbody>
            {parejas.map((fila) => {
              const lugar = posicion.get(fila.competidor_id) ?? 0
              // Sin partidos jugados la posición todavía no dice nada: es el
              // orden alfabético del desempate, no un puesto.
              const conLugar = fila.jugados > 0
              const clasificada = conLugar && clasifican !== null && lugar <= clasifican
              return (
                <tr key={fila.competidor_id} className="border-t">
                  <th scope="row" className="p-2 text-left font-medium">
                    {fila.nombre}
                  </th>
                  {parejas.map((columna) => {
                    if (columna.competidor_id === fila.competidor_id) {
                      // La diagonal: una pareja no juega contra sí misma.
                      return (
                        <td
                          key={columna.competidor_id}
                          aria-hidden="true"
                          className="grilla-diagonal border-l"
                        />
                      )
                    }
                    const partido = cruceEntre(partidos, fila.competidor_id, columna.competidor_id)
                    return (
                      <td key={columna.competidor_id} className="border-l p-0 text-center">
                        <Casillero
                          partido={partido}
                          fila={fila.competidor_id}
                          nombreFila={fila.nombre}
                          nombreColumna={columna.nombre}
                          onAbrir={onAbrir}
                          paraPapel={paraPapel}
                        />
                      </td>
                    )
                  })}
                  <td className="border-l p-2 text-center">
                    {conLugar ? (conSets ? fila.ganados : fila.puntos) : ''}
                  </td>
                  {conSets && (
                    <td className="p-2 text-center">{conLugar ? conSigno(fila.diferencia_sets) : ''}</td>
                  )}
                  <td className="p-2 text-center">{conLugar ? conSigno(fila.diferencia) : ''}</td>
                  <td
                    className={cn(
                      'p-2 text-center font-semibold',
                      clasificada && 'bg-primary/10',
                    )}
                  >
                    {conLugar ? lugar : ''}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {campeon && (
        <p className="flex items-center gap-1.5 text-sm font-medium">
          <Trophy className="size-4" />
          Campeón de {tabla.nombre ?? 'la zona'}: {campeon.nombre}
        </p>
      )}
    </div>
  )
}

function Casillero({
  partido,
  fila,
  nombreFila,
  nombreColumna,
  onAbrir,
  paraPapel,
}: {
  partido: PartidoDeTorneo | undefined
  fila: number
  nombreFila: string
  nombreColumna: string
  onAbrir: (partido: PartidoDeTorneo) => void
  paraPapel: boolean
}) {
  const parciales = partido ? parcialesDesdeLaFila(partido, fila) : []
  const gana = partido?.finalizado && partido.ganador_id === fila
  const pierde = partido?.finalizado && partido.ganador_id !== null && partido.ganador_id !== fila
  const contenido = parciales.map((p, i) => (
    <span key={i} className="mx-0.5 inline-block whitespace-nowrap">
      {p}
    </span>
  ))
  if (paraPapel || !partido) {
    return <div className={cn('grilla-casillero p-2', gana && 'font-semibold')}>{contenido}</div>
  }
  const cuando = partido.comienza_at
    ? `${fecha(partido.comienza_at)} ${hora(partido.comienza_at)}${partido.cancha ? ` · ${partido.cancha}` : ''}`
    : undefined
  return (
    <button
      type="button"
      onClick={() => onAbrir(partido)}
      // 🔑 El nombre accesible dice quiénes son y el resultado: sin él, una
      // grilla de seis son treinta botones iguales para un lector de pantalla.
      aria-label={`${nombreFila} contra ${nombreColumna}${parciales.length ? `: ${parciales.join(' ')}` : ''}`}
      title={cuando}
      className={cn(
        'grilla-casillero block h-full min-h-10 w-full p-2 hover:bg-accent',
        gana && 'font-semibold',
        pierde && 'text-muted-foreground',
      )}
    >
      {contenido}
    </button>
  )
}

/** Todas las grillas del torneo, cada una con su botón de imprimir.
 *
 * Las que no tienen partidos (un torneo sin sortear) no llegan acá: la pestaña
 * sólo existe si hay tablas. */
export function GrillasDelTorneo({
  torneo,
  tablas,
  partidos,
  onAbrir,
}: {
  torneo: Torneo
  tablas: TablaDeZona[]
  /** Todos los partidos del fixture; acá se filtran los de grupos de cada zona. */
  partidos: PartidoDeTorneo[]
  onAbrir: (partido: PartidoDeTorneo) => void
}) {
  // Qué zona se está imprimiendo: la clave de la tabla o `todas`. `null` = nada.
  const [aImprimir, setAImprimir] = useState<string | null>(null)

  useEffect(() => {
    if (aImprimir === null) return
    // Un tick para que la hoja ya esté montada cuando se abre el diálogo.
    const espera = setTimeout(() => {
      window.print()
      setAImprimir(null)
    }, 0)
    return () => clearTimeout(espera)
  }, [aImprimir])

  const grupos = partidos.filter((p) => p.etapa === 'grupos')
  const claveDe = (t: TablaDeZona) => String(t.zona_id ?? 'unica')
  const deLaZona = (t: TablaDeZona) => grupos.filter((p) => p.zona_id === t.zona_id)
  const titulo = tituloDelTorneo(torneo)
  const sujeto = sujetoDelDeporte(torneo.deporte)
  const elegidas = tablas.filter((t) => aImprimir === 'todas' || aImprimir === claveDe(t))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold uppercase tracking-wide">{titulo}</h2>
          <p className="text-xs text-muted-foreground">
            Cada casillero es el resultado {sujeto.de} de la fila contra{' '}
            {sujeto.articulo} de la columna. Tocalo para cargarlo o corregirlo.
          </p>
        </div>
        {tablas.length > 0 && (
          <Button variant="outline" size="sm" onClick={() => setAImprimir('todas')}>
            <Printer className="size-4" />
            {tablas.length > 1 ? 'Imprimir todas' : 'Imprimir'}
          </Button>
        )}
      </div>

      {tablas.map((tabla) => (
        <section key={claveDe(tabla)} className="space-y-2">
          <GrillaDeZona
            tabla={tabla}
            partidos={deLaZona(tabla)}
            clasifican={torneo.clasifican_por_zona}
            terminaEnZonas={torneo.termina_en_zonas}
            onAbrir={onAbrir}
            deporte={torneo.deporte}
          />
          {tablas.length > 1 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setAImprimir(claveDe(tabla))}
              aria-label={`Imprimir ${tabla.nombre ?? 'la grilla'}`}
            >
              <Printer className="size-4" />
              Imprimir {tabla.nombre ?? 'la grilla'}
            </Button>
          )}
        </section>
      ))}

      {/* La hoja se monta fuera de la raíz, como hijo de `body`, y en pantalla no
          se ve: al imprimir `index.css` esconde todo menos ella. Sólo existe
          mientras se imprime. */}
      {aImprimir !== null &&
        createPortal(
          <HojaDeGrillas torneo={torneo} tablas={elegidas} partidos={grupos} onAbrir={onAbrir} />,
          document.body,
        )}
    </div>
  )
}

/** La hoja que se imprime: una zona por página, con el título del torneo arriba.
 *
 * Es el contenido del portal de `GrillasDelTorneo`; vive aparte para poder
 * mirarla —y probarla— sin pasar por el diálogo de impresión. */
export function HojaDeGrillas({
  torneo,
  tablas,
  partidos,
  onAbrir,
}: {
  torneo: Torneo
  tablas: TablaDeZona[]
  /** Los partidos de grupos del torneo. */
  partidos: PartidoDeTorneo[]
  onAbrir: (partido: PartidoDeTorneo) => void
}) {
  const titulo = tituloDelTorneo(torneo)
  return (
    <div id="hoja-impresa" className="hoja-impresa hoja-grilla">
      {tablas.map((tabla) => (
        <section key={String(tabla.zona_id ?? 'unica')} className="grilla-pagina">
          <header>
            <h1>{titulo}</h1>
            <p>
              {fecha(torneo.desde)}
              {torneo.hasta ? ` al ${fecha(torneo.hasta)}` : ''} · {comoSeJuega(torneo)}
            </p>
          </header>
          <GrillaDeZona
            tabla={tabla}
            partidos={partidos.filter((p) => p.zona_id === tabla.zona_id)}
            clasifican={torneo.clasifican_por_zona}
            terminaEnZonas={torneo.termina_en_zonas}
            onAbrir={onAbrir}
            paraPapel
            deporte={torneo.deporte}
          />
        </section>
      ))}
    </div>
  )
}
