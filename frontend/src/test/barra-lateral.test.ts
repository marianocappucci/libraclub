// Guard: el fondo, el hover y el borde de la barra lateral los da libra-ui, no el producto (ADR-042 del kit).
//
// 🔴 **Lee las HOJAS DE ESTILO, no el DOM.** Lo que hay que impedir no es que la barra se vea mal hoy sino que vuelva a divergir: que
// alguien copie del producto de al lado el bloque de variables de shadcn (`--sidebar: oklch(0.985 0 0)`) y la suite quede con dos tonos
// de menú. El motor vive en `libra-ui/auditoria-de-barra-lateral` y tiene sus propios tests allá.
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { auditarBarraLateral, describirInfracciones } from 'libra-ui/auditoria-de-barra-lateral'

const r = auditarBarraLateral(join(process.cwd(), 'src'))

describe('la barra lateral toma su defecto del kit', () => {
  it('🔴 ninguna hoja declara --sidebar, --sidebar-accent ni --sidebar-border', () => {
    expect(describirInfracciones(r.infracciones)).toEqual([])
  })

  it('🔴 el producto importa libra-ui/tema.css (sin eso la barra quedaría sin fondo)', () => {
    expect(r.importaElTema).toBe(true)
  })

  it('🔴 el control — el guard midió hojas (si no, una lista vacía no probaría nada)', () => {
    expect(r.hojas).toBeGreaterThan(0)
  })
})
