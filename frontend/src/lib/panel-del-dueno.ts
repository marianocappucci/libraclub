/** Las cuentas chicas del panel del dueño que no son de ninguna pantalla.
 *
 * 🔑 **Los números grandes vienen del backend y acá sólo se suman o se comparan.** Las horas, los cobros y los
 * porcentajes de cada sucursal los calcula `servicios/panel_del_dueno.py`; esta pantalla no recalcula una ocupación
 * ni un ingreso por su cuenta (dos lugares calculando es cómo terminan mostrando cifras que no coinciden). Lo único
 * que se arma acá es lo que depende de qué sucursales se están mirando: el total de una columna y la variación.
 */
import type { FranjaDeOcupacion, IngresosDelPanel, SucursalDelPanel } from '@/lib/api'

export const DIAS_CORTOS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'] as const
export const DIAS_LARGOS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'] as const

/** Los orígenes que conoce la pantalla, en el orden en que se muestran. Un valor nuevo del enum del backend aparece igual
 *  (al final, con su clave como rótulo): la pantalla no esconde lo que no sabe nombrar. */
export const ORIGENES: Record<string, string> = {
  mostrador: 'Mostrador',
  telefono: 'Teléfono',
  whatsapp: 'WhatsApp',
  portal: 'Portal',
  serie: 'Turno fijo',
}

export function etiquetaDeOrigen(clave: string): string {
  return ORIGENES[clave] ?? clave
}

/** Las claves de origen que hay que mostrar: las conocidas primero y, después, las que el backend sume. */
export function clavesDeOrigen(sucursales: SucursalDelPanel[]): string[] {
  const vistas = new Set<string>(Object.keys(ORIGENES))
  for (const s of sucursales) for (const k of Object.keys(s.origen)) vistas.add(k)
  return [...vistas]
}

const PORCENTAJE = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 })

/** `63,5 %`, o `—` si no hubo horas abiertas (el backend manda `null`, que no es lo mismo que 0 %). */
export function porcentaje(valor: number | null | undefined): string {
  return valor == null ? '—' : `${PORCENTAJE.format(valor)} %`
}

/** El cambio porcentual entre dos períodos, o `null` si no hay contra qué comparar (el anterior fue cero): decir «+∞ %» o
 *  «+100 %» sobre una base vacía es inventar una tendencia. */
export function variacion(actual: number, anterior: number): number | null {
  if (!(anterior > 0)) return null
  return ((actual - anterior) / anterior) * 100
}

export type TotalDeIngresos = IngresosDelPanel & { medible: boolean }

/** Los ingresos de varias sucursales sumados. `medible` es falso si **alguna** no puede medir la plata: un total que
 *  deja afuera a una sucursal sin decirlo es peor que no mostrarlo. */
export function sumarIngresos(sucursales: SucursalDelPanel[]): TotalDeIngresos {
  const total: TotalDeIngresos = {
    reservas: 0, senas: 0, buffet: 0, total: 0, total_periodo_anterior: 0, medible: sucursales.length > 0,
  }
  for (const s of sucursales) {
    if (s.ingresos === null) {
      total.medible = false
      continue
    }
    total.reservas += s.ingresos.reservas
    total.senas += s.ingresos.senas
    total.buffet += s.ingresos.buffet
    total.total += s.ingresos.total
    total.total_periodo_anterior += s.ingresos.total_periodo_anterior
  }
  return total
}

/** Cuántos turnos se perdieron (cancelados o ausentes) y qué parte de los pedidos fue. El ausente ya está en `reservas`
 *  (se ocupó y se cobra) y el cancelado no: lo pedido es `reservas + canceladas`. `null` si no se pidió ninguno. */
export function turnosPerdidos(canceladas: number, ausentes: number, reservas: number) {
  const pedidos = reservas + canceladas
  return { perdidos: canceladas + ausentes, pct: pedidos > 0 ? ((canceladas + ausentes) / pedidos) * 100 : null }
}

/** Las horas que se dibujan, de arriba hacia abajo. Las madrugadas de un complejo que cierra pasada la medianoche
 *  (0, 1, 2…) van **después** de las de la noche y no arriba de todo: ordenadas por número, el día arrancaría a la 1. */
export function horasDelMapa(franjas: FranjaDeOcupacion[]): number[] {
  const horas = [...new Set(franjas.map((f) => f.hora))]
  const hayNoche = horas.some((h) => h >= 12)
  const clave = (h: number) => (hayNoche && h < 6 ? h + 24 : h)
  return horas.sort((a, b) => clave(a) - clave(b))
}

/** `18:00 – 19:00`, para el `title` de una celda. */
export function rangoDeHora(hora: number): string {
  const dos = (n: number) => String(n % 24).padStart(2, '0')
  return `${dos(hora)}:00 – ${dos(hora + 1)}:00`
}
