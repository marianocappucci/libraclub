// Guard: si el producto muestra el selector de modo claro / oscuro (`libra-ui/Layout`), el arranque lo aplica al cargar.
//
// 🔴 **Lee los FUENTES, no el DOM.** El selector guarda la elección en `localStorage`, pero quien la vuelve a poner al recargar es
// `iniciarModo()` en el `main.tsx`; sin esa llamada una recarga (Ctrl+F5) volvía a claro. El motor vive en `libra-ui/auditoria-del-modo`
// (ADR-104 del kit) y tiene sus propios tests allá.
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { auditarArranqueDelModo, describirArranqueDelModo } from 'libra-ui/auditoria-del-modo'

const r = auditarArranqueDelModo(join(process.cwd(), 'src'))

describe('el arranque aplica el modo guardado', () => {
  it('🔴 el control: el guard vio el Layout del kit y un main.tsx', () => {
    expect(r.usaElSelector).toBe(true)
    expect(r.archivoDeArranque).not.toBeNull()
  })

  it('🔴 el main.tsx llama a iniciarModo() o a cargarTema()', () => {
    expect(describirArranqueDelModo(r)).toEqual([])
  })
})
