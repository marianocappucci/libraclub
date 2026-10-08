// Guard: una pantalla no agrega relleno propio arriba de lo que ya le da el `Layout` (ADR-040, libra-ui v0.129.0).
//
// 🔴 **Lee los FUENTES, no el DOM.** Un `<div className="p-6">` de más no rompe nada: deja «un espacio vacío arriba» y el título más abajo que
// el nombre de la app. Vuelve solo cuando la próxima pantalla copia la de al lado. El motor vive en `libra-ui/auditoria-de-relleno`.
//
// Las pantallas que se dibujan FUERA del `Layout` (la hoja que se imprime, las páginas públicas) necesitan su propio relleno: van en
// `EXCEPCIONES`, cada una con su motivo. Una excepción que ya no hace falta sale en `sobrantes` y el test falla.
import { describe, expect, it } from 'vitest'
import { join } from 'node:path'
import { auditarRelleno, describirInfracciones, describirSobrantes } from 'libra-ui/auditoria-de-relleno'

const SRC = join(process.cwd(), 'src')

const EXCEPCIONES: Record<string, string> = {}

describe('las pantallas no agregan relleno propio arriba', () => {
  const r = auditarRelleno(SRC, { excepciones: EXCEPCIONES })

  it('🔴 el control — el guard midió pantallas (un parser que devuelve cero sería un falso verde)', () => {
    expect(r.archivos).toBeGreaterThan(0)
    expect(r.pantallas).toBeGreaterThan(0)
    expect(r.raices).toBeGreaterThan(0)
  })

  it('ninguna raíz de pantalla lleva p-N, py-N, pt-N, mt-N ni my-N', () => {
    expect(describirInfracciones(r.infracciones)).toEqual([])
  })

  it('las excepciones declaradas siguen haciendo falta', () => {
    expect(describirSobrantes(r.sobrantes)).toEqual([])
  })
})
