// Cómo se nombra una reserva en pantalla.
import { esReservaProvisoria } from 'libra-ui/reservas-del-nodo'

/** El texto de «la reserva N». Una reserva dada en un nodo sin conexión y todavía sin subir al central tiene un **id negativo**
 *  (`libraedge.mapeo`, ADR-022): no es un número que el cliente ni el mostrador hayan oído nunca, y mostrarlo como «#-48213» es inventar
 *  una reserva que no existe. Hasta que el central le da el definitivo se dice que no tiene número todavía.
 *
 *      numeroDeReserva(41)    // «#41»
 *      numeroDeReserva('41')  // «#41» (el `origen_id` de la cola viene en texto)
 *      numeroDeReserva(-7)    // «sin número todavía»
 */
export function numeroDeReserva(id: number | string | null | undefined): string {
  if (id === null || id === undefined || id === '') return '—'
  if (esReservaProvisoria(id)) return 'sin número todavía'
  return `#${id}`
}
