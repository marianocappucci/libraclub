/**
 * El plazo de la seña de una reserva tomada por teléfono o en el mostrador (`pendiente_pago`).
 *
 * Vence a las 24 horas de tomada, y nunca después de 2 horas antes del turno (libraclub ADR-029,
 * `vencimiento_de_sena` del backend). Acá **no se calcula nada**: el backend manda `vence_at` y la
 * pantalla lo dice. Dos pantallas con su propia cuenta terminarían diciendo plazos distintos.
 */
import { fecha, fechaHora, hora } from '@/lib/fechas'

/** Lo que ve el mostrador en el detalle. `null` si el estado no espera una seña. */
export function textoDelPlazoDeSena(
  estado: string | null | undefined,
  venceAt: string | null | undefined,
): string | null {
  if (estado !== 'pendiente_pago') return null
  return venceAt
    ? `Tiene hasta el ${fechaHora(venceAt)} para pagar la seña: después el turno se libera solo.`
    : 'Sin vencimiento: se tomó antes del plazo de 24 horas, así que hay que confirmarla o cancelarla a mano.'
}

/** Lo corto, para el casillero de la agenda: «seña hasta 29-10 10:00». `null` si no corresponde. */
export function textoCortoDeSena(
  estado: string | null | undefined,
  venceAt: string | null | undefined,
): string | null {
  if (estado !== 'pendiente_pago') return null
  if (!venceAt) return 'sin vencimiento'
  // `dd-mm` y no `dd-mm-aaaa`: el casillero es angosto y el año no ayuda a decidir.
  return `seña hasta ${fecha(venceAt).slice(0, 5)} ${hora(venceAt)}`
}
