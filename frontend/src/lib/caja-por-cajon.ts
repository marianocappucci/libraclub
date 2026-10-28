/** Qué de lo cobrado está en el cajón y qué no: el corte que hace cuadrar el arqueo.
 *
 * El arqueo cuenta **sólo el efectivo**: el esperado es el efectivo inicial más lo
 * cobrado en efectivo (neto de egresos), y se compara contra lo que se cuenta con
 * las manos. Lo cobrado por transferencia, tarjeta o Mercado Pago entró a la caja
 * igual, pero no está en el cajón: se concilia contra el banco, la terminal y el
 * resumen de Mercado Pago. Mezclar las dos cosas en una misma lista es lo que hace
 * que una caja con transferencias parezca cerrar con faltante.
 *
 * 🔑 **Esto no recalcula el arqueo.** El esperado y los netos por medio los calcula el
 * backend (el motor); acá sólo se parten por si el medio es `efectivo`, la misma
 * clave con la que el motor arma `efectivo_ventas`. Lo único que se suma es la lista
 * de los medios de afuera, para mostrar su subtotal, redondeado al centavo.
 */

/** La clave del medio que se cuenta a mano. La misma que usa el motor para el esperado. */
export const MEDIO_EN_EL_CAJON = 'efectivo'

export interface LineaDeMedio {
  medio: string
  total: number
}

export interface PartidoPorCajon {
  /** Lo del efectivo (cobros menos egresos), 0 si no hubo. */
  efectivo: number
  /** Los demás medios, del mayor al menor, sin los que están en cero. */
  fuera: LineaDeMedio[]
  /** La suma de los de afuera. */
  totalFuera: number
  /** Efectivo más lo de afuera: todo lo que cobró el turno o el día. */
  totalCobrado: number
}

function aCentavos(valor: number): number {
  return Math.round(valor * 100) / 100
}

/** Parte un `{medio: neto}` en lo que está en el cajón y lo que no. */
export function partirPorCajon(porMedio: Record<string, number> | null | undefined): PartidoPorCajon {
  const lineas = Object.entries(porMedio ?? {}).map(([medio, total]) => ({ medio, total: Number(total) || 0 }))
  const efectivo = lineas
    .filter((l) => l.medio === MEDIO_EN_EL_CAJON)
    .reduce((suma, l) => suma + l.total, 0)
  const fuera = lineas
    .filter((l) => l.medio !== MEDIO_EN_EL_CAJON && Math.abs(l.total) >= 0.005)
    .sort((a, b) => b.total - a.total)
  const totalFuera = aCentavos(fuera.reduce((suma, l) => suma + l.total, 0))
  return {
    efectivo: aCentavos(efectivo),
    fuera,
    totalFuera,
    totalCobrado: aCentavos(efectivo + totalFuera),
  }
}

/** Lo mismo desde la lista del cierre diario (`{medio_pago, neto}[]`). */
export function partirMediosDelCierre(
  medios: { medio_pago: string; neto: number }[] | null | undefined,
): PartidoPorCajon {
  const porMedio: Record<string, number> = {}
  for (const m of medios ?? []) porMedio[m.medio_pago] = (porMedio[m.medio_pago] ?? 0) + m.neto
  return partirPorCajon(porMedio)
}
