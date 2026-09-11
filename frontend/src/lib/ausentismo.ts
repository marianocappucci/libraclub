/**
 * Los clientes que faltan sin avisar, como los ve el mostrador.
 *
 * 🔴 **Avisa, no bloquea.** Decisión del humano: el encargado ve cuántas veces
 * faltó y decide él. Por eso esto es un hook de lectura y no una validación del
 * alta — no hay nada acá que pueda impedir una reserva.
 */
import { useEffect, useState } from 'react'

import { ausentismo } from '@/lib/api'
import type { Reincidente } from '@/lib/api'

export interface Ausentismo {
  porCliente: Map<number, Reincidente>
  /** La ventana vigente, en días. La manda el backend junto con la lista. */
  dias: number
}

const VACIO: Ausentismo = { porCliente: new Map(), dias: 0 }

/**
 * Los reincidentes, indexados por cliente. Se piden cuando `activo` pasa a
 * `true` —el diálogo de reserva los pide cada vez que se abre, así un ausente
 * marcado hace un rato ya aparece—.
 *
 * ⚠️ **Si el pedido falla, no hay aviso y nada más.** Es información para el
 * mostrador, no una condición para reservar: un error acá no puede tapar el
 * diálogo ni impedir tomar el turno, que es justamente lo que se decidió no
 * hacer.
 */
export function useReincidentes(activo = true): Ausentismo {
  const [estado, setEstado] = useState<Ausentismo>(VACIO)

  useEffect(() => {
    if (!activo) return
    let vigente = true
    ausentismo
      .reincidentes()
      .then((r) => {
        if (!vigente) return
        setEstado({
          porCliente: new Map((r?.reincidentes ?? []).map((x) => [x.cliente_id, x])),
          dias: r?.dias ?? 0,
        })
      })
      .catch(() => {
        // Ver el ⚠️ de arriba: sin aviso, pero se reserva igual.
      })
    return () => {
      vigente = false
    }
  }, [activo])

  return estado
}
