// El icono de cada deporte.
//
// 🔑 **Los siete salen de un set real y no son aproximaciones.** `lucide-react`
// —el set del resto del producto— **no tiene** tenis, básquet, fútbol, hockey ni
// pádel: se probaron sus 6.095 iconos y lo único deportivo es `Volleyball`,
// `Goal`, `Dumbbell` y `Trophy`. Los de acá vienen de Material Design Icons por
// `unplugin-icons`, que es **el mismo plugin que ya usa `libra-ui`** para sus
// iconos de acción: no es un segundo sistema, es otra colección del mismo.
//
// Se compilan a SVG inline en el build, así que no cargan un runtime ni pesan
// más que el path que dibujan.
//
// ⚠️ **Pádel usa el de `racquetball`** —una paleta y una pelota— porque no
// existe un icono de pádel en ningún set relevado. Es el más cercano y se
// distingue del de tenis, que es raqueta con cuerdas.
import IconoPadel from '~icons/mdi/racquetball'
import IconoFutbol from '~icons/mdi/soccer'
import IconoTenis from '~icons/mdi/tennis'
import IconoBasquet from '~icons/mdi/basketball'
import IconoVoley from '~icons/mdi/volleyball'
import IconoHockey from '~icons/mdi/hockey-sticks'
import IconoOtro from '~icons/mdi/dumbbell'

import type { ComponentType, SVGProps } from 'react'

type Icono = ComponentType<SVGProps<SVGSVGElement>>

/** Las claves son las del enum `Deporte` del backend, igual que
 *  `NOMBRE_DE_DEPORTE`. El guard de `tests/test_etiquetas_de_deporte.py` cubre
 *  ese mapa; éste se mantiene al lado para que se vean juntos. */
export const ICONO_DE_DEPORTE: Record<string, Icono> = {
  padel: IconoPadel,
  futbol: IconoFutbol,
  tenis: IconoTenis,
  basquet: IconoBasquet,
  voley: IconoVoley,
  hockey: IconoHockey,
  otro: IconoOtro,
}

/** El icono del deporte, o el genérico si es uno que este mapa no conoce.
 *
 * Nunca devuelve `undefined`: una pestaña sin icono al lado de seis que lo
 * tienen se lee como un error de carga. */
export function iconoDeDeporte(deporte: string): Icono {
  return ICONO_DE_DEPORTE[deporte] ?? IconoOtro
}
