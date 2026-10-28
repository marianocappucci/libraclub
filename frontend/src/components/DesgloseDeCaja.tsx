/** Lo cobrado, partido en «en el cajón» y «fuera del cajón».
 *
 * Lo comparten la caja abierta, el detalle de un turno cerrado y el cierre diario:
 * las tres mostraban los medios en una sola lista, con el efectivo mezclado entre
 * las transferencias, y quien arqueaba tenía que adivinar cuáles de esas líneas
 * eran las del cajón. Acá van separadas, cada bloque con la frase de a dónde
 * mirar para cotejarlo.
 *
 * El corte es de `lib/caja-por-cajon.ts`; los números los calcula el backend.
 */
import type { ReactNode } from 'react'

import { partirPorCajon } from '@/lib/caja-por-cajon'
import { pesos } from '@/lib/fechas'

export function DesgloseDeCaja({
  porMedio, etiquetaDeMedio, inicial, esperado, children,
}: {
  /** El neto de cada medio: `{efectivo: 9000, transferencia: 4000}`. */
  porMedio: Record<string, number>
  etiquetaDeMedio: (medio: string) => string
  /** El efectivo con el que arrancó el turno (en el cierre diario, el de todos los turnos del día). Sin él no se dibuja. */
  inicial?: number
  /** Lo que tiene que haber en el cajón. Lo calcula quien llama (el motor lo cierra así). */
  esperado?: number
  children?: ReactNode
}) {
  const { efectivo, fuera, totalFuera, totalCobrado } = partirPorCajon(porMedio)

  return (
    <div className="space-y-3 text-sm">
      <section aria-label="En el cajón" className="space-y-1">
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          En el cajón
          <span className="ml-1 font-normal normal-case tracking-normal">· se cuenta a mano</span>
        </h3>
        {inicial !== undefined && (
          <div className="flex justify-between">
            <span className="text-muted-foreground">Efectivo inicial</span>
            <span className="tabular-nums">{pesos(inicial)}</span>
          </div>
        )}
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Efectivo (menos egresos)</span>
          <span className="shrink-0 tabular-nums">{pesos(efectivo)}</span>
        </div>
        {esperado !== undefined && (
          <div className="flex justify-between border-t pt-1 font-medium">
            <span>Esperado en el cajón</span>
            <span className="tabular-nums">{pesos(esperado)}</span>
          </div>
        )}
      </section>

      <section aria-label="Fuera del cajón" className="space-y-1">
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Fuera del cajón
          <span className="ml-1 font-normal normal-case tracking-normal">
            · se concilia con el banco, la terminal y Mercado Pago
          </span>
        </h3>
        {fuera.length === 0 ? (
          <p className="text-muted-foreground">No se cobró nada por otros medios.</p>
        ) : (
          <>
            {fuera.map((l) => (
              <div key={l.medio} className="flex justify-between">
                <span className="text-muted-foreground">{etiquetaDeMedio(l.medio)}</span>
                <span className="tabular-nums">{pesos(l.total)}</span>
              </div>
            ))}
            <div className="flex justify-between border-t pt-1 font-medium">
              <span>Total fuera del cajón</span>
              <span className="tabular-nums">{pesos(totalFuera)}</span>
            </div>
          </>
        )}
      </section>

      <div className="flex justify-between border-t pt-2 font-medium">
        <span>Total cobrado</span>
        <span className="tabular-nums">{pesos(totalCobrado)}</span>
      </div>
      {children}
    </div>
  )
}
