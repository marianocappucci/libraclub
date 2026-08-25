/** Los medios de pago de este complejo, del backend.
 *
 *  🔴 **No hay lista acá.** La declara `app/servicios/caja.py` y llega por
 *  `GET /api/caja/medios-pago`. Ver la nota en `lib/api.ts`.
 */
import { useEffect, useState } from 'react'

import { api, type MedioDePago } from './api'

/** Cache de módulo: la lista no cambia mientras la pestaña esté abierta, y la
 *  piden cuatro pantallas. */
let cache: MedioDePago[] | null = null

export function useMediosDePago() {
  const [medios, setMedios] = useState<MedioDePago[]>(cache ?? [])

  useEffect(() => {
    if (cache) return
    api.get<MedioDePago[]>('/api/caja/medios-pago')
      .then((ms) => {
        // Se comprueba la forma, no se confía en ella: un cuerpo truncado es
        // truthy y el `.map()` de las pantallas tumbaría la vista entera.
        cache = Array.isArray(ms) ? ms : []
        setMedios(cache)
      })
      .catch(() => {})
  }, [])

  return {
    medios,
    /** Cómo se muestra un medio. **Nunca vacío**: uno que el backend no nombró
     *  sale con su clave cruda, que es la única forma de enterarse. Cubre las
     *  grafías viejas — hay cobros registrados con `tarjeta`. */
    etiqueta: (valor: string) =>
      medios.find((m) => m.valor === valor)?.etiqueta ?? ETIQUETA_VIEJA[valor] ?? valor,
  }
}

/** Lo que el backend ya no ofrece pero está en cobros de antes. Espeja a
 *  `medios_pago.HISTORICOS`; sin esto la grilla muestra la clave cruda. */
const ETIQUETA_VIEJA: Record<string, string> = {
  tarjeta: 'Tarjeta',
  debito: 'Tarjeta de débito',
  credito: 'Tarjeta de crédito',
  mercado_pago: 'Mercado Pago',
}
