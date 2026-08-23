/** La pastilla del saldo de una cuenta corriente.
 *
 *  Vive acá y no en cada pantalla porque el listado de cobranza y el detalle
 *  del cliente muestran **el mismo número**: si cada uno decidiera su tono y su
 *  redacción, el mismo saldo se leería de dos formas distintas al hacer un
 *  click.
 */
import { BadgeEstado } from 'libra-ui/badge-estado'

import { pesos } from '@/lib/fechas'

/**
 * 🔑 **Un saldo a favor se dice, no se muestra en negativo.** Un `-$2.500` en la
 * columna del que pagó de más obliga a interpretar un signo; «A favor $2.500»
 * no. Y el signo tampoco se pierde: lo lleva el tono.
 *
 * Los tres tonos son los de `libra-ui/badge-estado` (ver
 * `identidad-visual-suite-libra`): `atencion` para lo que hay que ir a cobrar,
 * `ok` para lo que está resuelto, `neutro` para la cuenta sin nada pendiente.
 */
export function BadgeDeSaldo({ monto }: { monto: number }) {
  if (monto > 0) return <BadgeEstado tono="atencion">Debe {pesos(monto)}</BadgeEstado>
  if (monto < 0) return <BadgeEstado tono="ok">A favor {pesos(-monto)}</BadgeEstado>
  return <BadgeEstado tono="neutro">Al día</BadgeEstado>
}
