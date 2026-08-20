/**
 * El **único** lugar donde se formatea una fecha en el frontend.
 *
 * La regla del ecosistema: la API habla ISO 8601 en las dos direcciones, y
 * `dd-mm-aaaa` es sólo presentación. Repetir el formateo por vista es cómo
 * terminan tres pantallas mostrando la misma fecha de tres formas, y cómo una
 * de ellas queda en UTC sin que nadie lo note.
 */

export const TZ = 'America/Argentina/Buenos_Aires'

/**
 * `dd-mm-aaaa`. Acepta ISO o `Date`.
 *
 * 🔴 Se arma con `formatToParts` y no se usa el `format()` de `es-AR` directo:
 * ese devuelve `01/09/2026`, **con barras**, y la convención del ecosistema es
 * con guiones. Lo agarró el test; leyendo el código, `es-AR` + `2-digit` parece
 * que ya diera el formato pedido.
 */
export function fecha(valor: string | Date | null | undefined): string {
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
  // Se reconstruye a mediodía UTC para que ningún corrimiento de zona lo mueva
  // de día mientras se le restan los días.
  const d = new Date(`${iso}T12:00:00Z`)
  const offset = (d.getUTCDay() + 6) % 7 // 0 = lunes
  d.setUTCDate(d.getUTCDate() - offset)
  return d.toISOString().slice(0, 10)
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
