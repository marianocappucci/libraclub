// Guard: los reportes y los tableros toman sus íconos del catálogo, no de lucide (ADR-038, libra-ui v0.128.0).
//
// 🔴 **Lee los FUENTES, no el DOM.** Lo que hay que impedir no es que una pantalla se rompa sino que vuelvan a divergir: que el próximo
// KPI importe un ícono de lucide porque quedaba bien y el menú diga otra cosa. Eso se ve en el `import`, no en un render. El motor vive
// en `libra-ui/auditoria-de-indicadores` y tiene sus propios tests allá.
//
// ⚠️ **El guard elige las pantallas por el nombre del archivo** (`Reporte*`, `Dashboard*`, `Inicio*`…) y en este producto ninguna lo lleva:
// el reporte de plata se llama `CajaPorMedio`. Por eso se lista acá; una pantalla de reporte o de tablero nueva con otro nombre se suma
// a `PANTALLAS_DE_INDICADORES` (si no, el guard no la mide).
import { describe, expect, it } from 'vitest'
import { join } from 'node:path'
import {
  auditarIndicadores, describirInfracciones, esPantallaDeIndicadores,
} from 'libra-ui/auditoria-de-indicadores'

const SRC = join(process.cwd(), 'src')

/** Las pantallas con KPI o reportes cuyo nombre no lo dice. */
const PANTALLAS_DE_INDICADORES = ['pages/CajaPorMedio.tsx']

describe('los reportes y tableros usan el catálogo de íconos', () => {
  const r = auditarIndicadores(SRC, {
    esPantalla: (ruta) => esPantallaDeIndicadores(ruta) || PANTALLAS_DE_INDICADORES.includes(ruta),
  })

  it('🔴 el control — el guard midió las pantallas (un parser que devuelve cero sería un falso verde)', () => {
    expect(r.archivos).toBeGreaterThan(0)
    expect(r.pantallas).toBeGreaterThanOrEqual(PANTALLAS_DE_INDICADORES.length)
  })

  it('🔴 ninguna pantalla de reporte o de tablero importa un ícono de concepto de lucide', () => {
    expect(describirInfracciones(r.infracciones)).toEqual([])
  })
})
