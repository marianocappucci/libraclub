/**
 * El **único** lugar donde se formatea una fecha en el frontend.
 *
 * La regla del ecosistema: la API habla ISO 8601 en las dos direcciones, y
 * `dd-mm-aaaa` es sólo presentación. Repetir el formateo por vista es cómo
 * terminan tres pantallas mostrando la misma fecha de tres formas, y cómo una
 * de ellas queda en UTC sin que nadie lo note.
 */

import { sumarDiasISO } from 'libra-ui/fechas'

export const TZ = 'America/Argentina/Buenos_Aires'

/**
 * `dd-mm-aaaa`. Acepta ISO o `Date`.
 *
 * 🔴 Se arma con `formatToParts` y no se usa el `format()` de `es-AR` directo:
 * ese devuelve `01/09/2026`, **con barras**, y la convención del ecosistema es
 * con guiones. Lo agarró el test; leyendo el código, `es-AR` + `2-digit` parece
 * que ya diera el formato pedido.
 */
/** Un `aaaa-mm-dd` pelado, tal como lo serializa una columna `date`. */
const SOLO_FECHA = /^(\d{4})-(\d{2})-(\d{2})$/

export function fecha(valor: string | Date | null | undefined): string {
  // 🔴 **Un `aaaa-mm-dd` no es un instante: es un día del calendario**, y
  // convertirlo de zona lo corre uno para atrás SIEMPRE. `new Date('2026-08-22')`
  // es medianoche UTC, que en Argentina son las 21:00 del 21 — así que el
  // extracto de la cuenta corriente, las fechas de un torneo y la ventana de una
  // serie mostraban todas el día anterior. No es un caso de borde nocturno como
  // el que cuida `diaISO`: es cada valor, a toda hora.
  //
  // Se reordena el texto sin construir un `Date`, que es lo único que no puede
  // volver a corromperse: no hay zona de la que convertir.
  if (typeof valor === 'string') {
    const partes = SOLO_FECHA.exec(valor)
    if (partes) return `${partes[3]}-${partes[2]}-${partes[1]}`
  }
  const d = aDate(valor)
  if (!d) return ''
  const partes = new Intl.DateTimeFormat('es-AR', {
    timeZone: TZ,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).formatToParts(d)
  const parte = (tipo: Intl.DateTimeFormatPartTypes) =>
    partes.find((p) => p.type === tipo)?.value ?? ''
  return `${parte('day')}-${parte('month')}-${parte('year')}`
}

/** `dd-mm-aaaa HH:MM`, reloj de 24 h, en hora de Argentina. */
export function fechaHora(valor: string | Date | null | undefined): string {
  const d = aDate(valor)
  if (!d) return ''
  return `${fecha(d)} ${hora(d)}`
}

/** Sólo `HH:MM`, en hora de Argentina. Es lo que se ve en la grilla. */
export function hora(valor: string | Date | null | undefined): string {
  const d = aDate(valor)
  if (!d) return ''
  return new Intl.DateTimeFormat('es-AR', {
    timeZone: TZ,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(d)
}

/**
 * La fecha en ISO `aaaa-mm-dd` **para el complejo**, no para el navegador.
 *
 * 🔴 `Date.toISOString().slice(0,10)` da el día en UTC: a las 22:00 de Argentina
 * ya devuelve el día siguiente, y la agenda abriría en el día equivocado
 * justamente en la franja más usada.
 */
export function diaISO(valor: string | Date | null | undefined): string {
  const d = aDate(valor)
  if (!d) return ''
  // `en-CA` formatea como `aaaa-mm-dd`, que es exactamente ISO.
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(d)
}

/** El lunes de la semana de `valor`, en ISO. La agenda arranca ahí. */
export function lunesDeLaSemana(valor: string | Date = new Date()): string {
  const iso = diaISO(valor)
  // El anclaje al mediodía UTC —para que ningún corrimiento de zona mueva el
  // día mientras se restan— lo hace ahora `sumarDiasISO` del paquete, que es
  // donde vive esa cuenta para toda la familia.
  const offset = (new Date(`${iso}T12:00:00Z`).getUTCDay() + 6) % 7 // 0 = lunes
  return sumarDiasISO(iso, -offset)
}

/** Nombre del día, capitalizado. `2026-09-01` → `Martes`. */
export function nombreDelDia(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`)
  const nombre = new Intl.DateTimeFormat('es-AR', {
    timeZone: 'UTC',
    weekday: 'long',
  }).format(d)
  return nombre.charAt(0).toUpperCase() + nombre.slice(1)
}

/** Pesos argentinos. Nunca `€`: el símbolo del ecosistema es `$`. */
export function pesos(valor: string | number | null | undefined): string {
  if (valor === null || valor === undefined || valor === '') return ''
  const numero = typeof valor === 'string' ? Number(valor) : valor
  if (Number.isNaN(numero)) return ''
  return new Intl.NumberFormat('es-AR', {
    style: 'currency',
    currency: 'ARS',
    maximumFractionDigits: 2,
  }).format(numero)
}

function aDate(valor: string | Date | null | undefined): Date | null {
  if (!valor) return null
  const d = valor instanceof Date ? valor : new Date(valor)
  return Number.isNaN(d.getTime()) ? null : d
}

/**
 * `dd-mm`, sin año. Es la cabecera de cada columna de la grilla semanal, donde
 * el año no entra en el ancho de la celda.
 *
 * 🔴 Con GUION, como el resto del ecosistema. La cabecera lo armaba a mano con
 * barra (`22/08`) justo en el producto que sirve de modelo del helper unico:
 * que el formato sea corto no lo saca de la convencion, y tenerlo suelto en la
 * vista es como se escapo.
 *
 * Se reordena el texto sin construir un `Date`, por lo mismo que `fecha()`: un
 * `aaaa-mm-dd` es un dia del calendario, no un instante.
 */
export function diaYMes(iso: string): string {
  const m = SOLO_FECHA.exec(iso ?? '')
  return m ? `${m[3]}-${m[2]}` : (iso ?? '')
}
