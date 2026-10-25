/** El mapa de calor de la ocupación: días de la semana en las columnas, horas en las filas.
 *
 * Una grilla simple de 7 × N celdas, sin librería de gráficos: es una tabla, así que un lector de pantalla la recorre
 * por fila y columna y cada celda dice su valor (`title` y `aria-label`).
 *
 * 🔑 **El color es una mezcla de tokens del tema y no un color.** Cada celda mezcla `--marca` (el verde del producto)
 * con `--card` en el porcentaje de ocupación: en modo oscuro `--card` es oscuro y la misma cuenta da una escala oscura, sin
 * una segunda paleta. La cifra de adentro se pasa a clara sólo en las celdas casi llenas, donde el fondo ya es el verde
 * entero — con el texto del tema se perdería.
 *
 * ⚠️ **Una celda cerrada no es una celda en 0 %.** El backend no manda las horas en que el complejo no abre; acá se
 * dibujan rayadas y dicen «cerrado». Pintarlas como vacías diría «no vendió» donde lo cierto es «no había nada que vender»,
 * el mismo cuidado que el `null` de la ocupación total.
 */
import type { FranjaDeOcupacion } from '@/lib/api'
import { DIAS_CORTOS, DIAS_LARGOS, horasDelMapa, porcentaje, rangoDeHora } from '@/lib/panel-del-dueno'

//: A partir de acá la celda es casi el verde entero y la cifra tiene que ser clara.
const UMBRAL_DE_CIFRA_CLARA = 85

function fondo(pct: number): string {
  return `color-mix(in oklab, var(--marca) ${Math.min(100, Math.max(0, pct))}%, var(--card))`
}

export function LeyendaDelMapa() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" data-slot="leyenda-del-mapa">
      <span className="flex items-center gap-2">
        <span>0 %</span>
        <span
          aria-hidden
          className="h-3 w-28 rounded-sm border border-border"
          style={{ backgroundImage: `linear-gradient(to right, ${fondo(0)}, ${fondo(100)})` }}
        />
        <span>100 % de las horas abiertas, reservadas</span>
      </span>
      <span className="flex items-center gap-2">
        <span aria-hidden className="h-3 w-5 rounded-sm border border-dashed border-border bg-muted/30" />
        <span>Cerrado</span>
      </span>
    </div>
  )
}

export function MapaDeCalor({ franjas, etiqueta }: { franjas: FranjaDeOcupacion[]; etiqueta: string }) {
  const horas = horasDelMapa(franjas)
  const valores = new Map(franjas.map((f) => [`${f.dia}-${f.hora}`, f.ocupacion_pct]))

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table aria-label={etiqueta} className="border-separate border-spacing-1 text-xs">
          <thead>
            <tr>
              <th scope="col"><span className="sr-only">Hora</span></th>
              {DIAS_CORTOS.map((dia) => (
                <th key={dia} scope="col" className="px-1 pb-1 text-center font-medium text-muted-foreground">
                  {dia}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {horas.map((hora) => (
              <tr key={hora}>
                <th scope="row" className="pr-2 text-right font-normal tabular-nums text-muted-foreground">
                  {String(hora).padStart(2, '0')}:00
                </th>
                {DIAS_LARGOS.map((dia, indice) => {
                  const clave = `${indice}-${hora}`
                  const lugar = `${dia[0].toUpperCase()}${dia.slice(1)} ${rangoDeHora(hora)}`
                  if (!valores.has(clave) || valores.get(clave) == null) {
                    return (
                      <td
                        key={clave}
                        data-estado="cerrado"
                        title={`${lugar}: cerrado`}
                        aria-label={`${lugar}: cerrado`}
                        className="h-8 min-w-12 rounded-sm border border-dashed border-border bg-muted/30"
                      />
                    )
                  }
                  const pct = valores.get(clave) as number
                  const texto = `${lugar}: ${porcentaje(pct)} de ocupación`
                  return (
                    <td
                      key={clave}
                      data-pct={pct}
                      title={texto}
                      aria-label={texto}
                      className="h-8 min-w-12 rounded-sm border border-border text-center font-medium tabular-nums"
                      style={{
                        backgroundColor: fondo(pct),
                        ...(pct >= UMBRAL_DE_CIFRA_CLARA ? { color: 'oklch(0.985 0 0)' } : {}),
                      }}
                    >
                      {Math.round(pct)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <LeyendaDelMapa />
    </div>
  )
}
