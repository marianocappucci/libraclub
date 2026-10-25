/** Las tablas de la fase de grupos, una por zona. */
import { Trophy } from 'lucide-react'

import type { TablaDeZona } from '@/lib/api'
import { cn } from '@/lib/utils'

function conSigno(n: number | null | undefined): string {
  if (n === null || n === undefined) return ''
  return n > 0 ? `+${n}` : String(n)
}

export function TablaDePosiciones({
  tablas,
  clasifican,
  terminaEnZonas = false,
}: {
  tablas: TablaDeZona[]
  /** Cuántos pasan por zona. `null` en una liga, que no tiene playoff, y en un
   *  torneo que termina en las zonas. */
  clasifican: number | null
  /** Sin llaves: el primero de cada zona es su campeón. */
  terminaEnZonas?: boolean
}) {
  const conSets = tablas.some((t) => t.con_sets)
  return (
    <div className="space-y-4">
      {tablas.map((tabla) => (
        <section key={tabla.zona_id ?? 'unica'} className="space-y-2">
          {tabla.nombre && <h3 className="text-sm font-semibold">{tabla.nombre}</h3>}
          {/* La tabla scrollea sola en pantalla angosta: nueve columnas no
              entran en un teléfono, y lo que no puede pasar es que scrollee la
              página. */}
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-xs text-muted-foreground">
                <tr>
                  <th className="p-2 text-left font-medium">#</th>
                  <th className="p-2 text-left font-medium">
                    {tabla.con_sets ? 'Pareja' : 'Competidor'}
                  </th>
                  <th className="p-2 text-right font-medium" title="Partidos jugados">PJ</th>
                  <th className="p-2 text-right font-medium" title="Ganados">PG</th>
                  {!tabla.con_sets && (
                    <th className="p-2 text-right font-medium" title="Empatados">PE</th>
                  )}
                  <th className="p-2 text-right font-medium" title="Perdidos">PP</th>
                  {tabla.con_sets ? (
                    <>
                      {/* En pádel y tenis no hay empates, así que los puntos son
                          los partidos ganados y la columna sobra. Lo que sí
                          desempata, en este orden: el cara a cara entre dos,
                          los sets y los games. */}
                      <th className="p-2 text-right font-medium" title="Diferencia de sets">
                        Dif. sets
                      </th>
                      <th className="p-2 text-right font-medium" title="Diferencia de games">
                        Dif. games
                      </th>
                      <th className="p-2 text-right font-medium" title="Games a favor">
                        Games a favor
                      </th>
                    </>
                  ) : (
                    <>
                      {/* En fútbol son goles. El encabezado no dice cuál:
                          cambia por torneo y quien la mira ya sabe a qué está
                          jugando. */}
                      <th className="p-2 text-right font-medium" title="A favor">AF</th>
                      <th className="p-2 text-right font-medium" title="En contra">EC</th>
                      <th className="p-2 text-right font-medium" title="Diferencia">Dif</th>
                      <th className="p-2 text-right font-medium">Pts</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {tabla.filas.map((fila, indice) => (
                  <tr
                    key={fila.competidor_id}
                    className={cn(
                      'border-t',
                      // 🔑 La línea de corte: quién está clasificando ahora
                      // mismo. Es lo primero que busca el que mira una tabla, y
                      // contarlo a mano con ocho equipos se equivoca.
                      clasifican !== null && indice === clasifican - 1 &&
                        'border-b-2 border-b-primary/50',
                    )}
                  >
                    <td className="p-2 text-muted-foreground">{indice + 1}</td>
                    <td className="p-2 font-medium">
                      <span className="inline-flex items-center gap-1.5">
                        {fila.nombre}
                        {terminaEnZonas && tabla.completa && indice === 0 && (
                          <Trophy
                            className="size-3.5"
                            aria-label={`Campeón de ${tabla.nombre ?? 'la zona'}`}
                          />
                        )}
                      </span>
                    </td>
                    <td className="p-2 text-right">{fila.jugados}</td>
                    <td className="p-2 text-right">{fila.ganados}</td>
                    {!tabla.con_sets && <td className="p-2 text-right">{fila.empatados}</td>}
                    <td className="p-2 text-right">{fila.perdidos}</td>
                    {tabla.con_sets ? (
                      <>
                        <td className="p-2 text-right">{conSigno(fila.diferencia_sets)}</td>
                        <td className="p-2 text-right">{conSigno(fila.diferencia)}</td>
                        <td className="p-2 text-right">{fila.a_favor}</td>
                      </>
                    ) : (
                      <>
                        <td className="p-2 text-right">{fila.a_favor}</td>
                        <td className="p-2 text-right">{fila.en_contra}</td>
                        <td className="p-2 text-right">{conSigno(fila.diferencia)}</td>
                        <td className="p-2 text-right font-semibold">{fila.puntos}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
      {conSets ? (
        <p className="text-xs text-muted-foreground">
          Se ordena por partidos ganados. Si dos parejas empatan, define el
          resultado entre ellas; si empatan tres o más —o todavía no se
          enfrentaron—, la diferencia de sets, después la de games y después los
          games a favor.
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          Ganar suma 3 y empatar 1. Se ordena por puntos, después por diferencia y
          después por lo hecho a favor.
        </p>
      )}
    </div>
  )
}
