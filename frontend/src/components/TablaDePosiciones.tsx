/** Las tablas de la fase de grupos, una por zona. */
import type { TablaDeZona } from '@/lib/api'
import { cn } from '@/lib/utils'

export function TablaDePosiciones({
  tablas,
  clasifican,
}: {
  tablas: TablaDeZona[]
  /** Cuántos pasan por zona. `null` en una liga, que no tiene playoff. */
  clasifican: number | null
}) {
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
                  <th className="p-2 text-left font-medium">Competidor</th>
                  <th className="p-2 text-right font-medium" title="Partidos jugados">PJ</th>
                  <th className="p-2 text-right font-medium" title="Ganados">PG</th>
                  <th className="p-2 text-right font-medium" title="Empatados">PE</th>
                  <th className="p-2 text-right font-medium" title="Perdidos">PP</th>
                  {/* En fútbol son goles y en pádel games. El encabezado no
                      dice cuál: cambia por torneo y quien la mira ya sabe a qué
                      está jugando. */}
                  <th className="p-2 text-right font-medium" title="A favor">AF</th>
                  <th className="p-2 text-right font-medium" title="En contra">EC</th>
                  <th className="p-2 text-right font-medium" title="Diferencia">Dif</th>
                  <th className="p-2 text-right font-medium">Pts</th>
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
                    <td className="p-2 font-medium">{fila.nombre}</td>
                    <td className="p-2 text-right">{fila.jugados}</td>
                    <td className="p-2 text-right">{fila.ganados}</td>
                    <td className="p-2 text-right">{fila.empatados}</td>
                    <td className="p-2 text-right">{fila.perdidos}</td>
                    <td className="p-2 text-right">{fila.a_favor}</td>
                    <td className="p-2 text-right">{fila.en_contra}</td>
                    <td className="p-2 text-right">
                      {fila.diferencia > 0 ? `+${fila.diferencia}` : fila.diferencia}
                    </td>
                    <td className="p-2 text-right font-semibold">{fila.puntos}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
      <p className="text-xs text-muted-foreground">
        Ganar suma 3 y empatar 1. Se ordena por puntos, después por diferencia y
        después por lo hecho a favor.
      </p>
    </div>
  )
}
