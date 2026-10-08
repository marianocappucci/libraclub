// Guard: todo desplegable de datos se busca escribiendo (ADR-039, libra-ui v0.129.0).
//
// 🔴 **Lee los FUENTES, no el DOM.** Lo que hay que impedir no es que una pantalla se rompa sino que vuelva a nacer un desplegable de datos
// (clientes, canchas, medios…) que no se puede buscar. Eso se ve en el JSX, no en un render con datos de prueba. El motor vive en
// `libra-ui/auditoria-de-selects` y tiene sus propios tests allá.
//
// Un desplegable de datos es `SelectBuscable`. Uno de lista cerrada (un enum del código) puede seguir siendo `<Select>`/`<select>` si lleva
// un comentario `select-cerrado: <motivo>` en su renglón o en los tres de arriba; los de ≤ 8 opciones escritas a mano no necesitan marca.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'
import { auditarSelects, describirInfracciones } from 'libra-ui/auditoria-de-selects'

const SRC = join(process.cwd(), 'src')

describe('los desplegables de datos se buscan escribiendo', () => {
  const r = auditarSelects(SRC)

  it('🔴 el control — el guard midió desplegables (un parser que devuelve cero sería un falso verde)', () => {
    expect(r.archivos).toBeGreaterThan(0)
    expect(r.desplegables).toBeGreaterThan(0)
  })

  it('ningún desplegable de datos (ni uno de más de 8 opciones fijas) deja de ser SelectBuscable', () => {
    expect(describirInfracciones(r.infracciones)).toEqual([])
  })
})

// ── La × de un SelectBuscable con centinela ────────────────────────────────────────────────────────────────────────────────────────────
//
// 🔴 Hasta libra-ui v0.129.0 el campo ofrecía por defecto una × que vacía la selección; desde la v0.129.1 **sólo con `limpiable`**. Un uso con un
// centinela propio (`{ value: TODOS, label: 'Todos' }`, `NONE`, `SIN_DEPOSITO`…) no debe pedirla: con «Todos» elegido la × mandaría `''`, que el
// estado de la pantalla no entiende (`Number('')` es 0: el filtro por cliente se queda sin resultados, o un `actualizarCampo({ cliente_id: 0 })`
// llega al backend), y ningún test ni el JSX lo muestran: sólo apretando la ×. Lo que se vigila ahora es que nadie le ponga `limpiable` (o
// `limpiable={true}`) a un campo así; `limpiable={false}` sigue siendo válido (y redundante). Se lee en los fuentes, igual que el guard de arriba.
function fuentesTsx(dir: string): string[] {
  return readdirSync(dir).flatMap((nombre) => {
    if (nombre === 'node_modules' || nombre === 'test') return []
    const ruta = join(dir, nombre)
    if (statSync(ruta).isDirectory()) return fuentesTsx(ruta)
    return /\.tsx$/.test(nombre) && !/\.test\.tsx$/.test(nombre) ? [ruta] : []
  })
}

/** Cada `<SelectBuscable …/>` de un fuente, con su renglón. El `>` de una flecha o de un `a > b` adentro de `{…}` no cierra la etiqueta. */
function usosDeSelectBuscable(fuente: string): { linea: number; etiqueta: string }[] {
  const usos: { linea: number; etiqueta: string }[] = []
  for (const m of fuente.matchAll(/<SelectBuscable\b/g)) {
    let llaves = 0
    let i = m.index + m[0].length
    for (; i < fuente.length; i++) {
      const c = fuente[i]
      if (c === '{') llaves++
      else if (c === '}') llaves--
      else if (c === '>' && llaves === 0 && fuente[i - 1] !== '=') break
    }
    usos.push({ linea: fuente.slice(0, m.index).split('\n').length, etiqueta: fuente.slice(m.index, i + 1) })
  }
  return usos
}

/** ¿La etiqueta tiene una opción de valor-constante (`value: TODOS,`) **y** pide la × (`limpiable`, `limpiable={true}`, no `limpiable={false}`)? */
function pideLaCruzConUnCentinela(etiqueta: string): boolean {
  return /value:\s*[A-Z][A-Z_]+\s*,/.test(etiqueta) && /\blimpiable\b(?!=\{false\})/.test(etiqueta)
}

describe('un SelectBuscable con un centinela propio no ofrece la ×', () => {
  const todos = fuentesTsx(SRC).flatMap((ruta) =>
    usosDeSelectBuscable(readFileSync(ruta, 'utf8')).map((u) => ({ ...u, archivo: relative(SRC, ruta).replaceAll('\\', '/') })))

  it('🔴 el control — el guard encontró los usos de SelectBuscable', () => {
    expect(todos.length).toBeGreaterThan(0)
  })

  it('🔴 el control — el predicado marca un centinela con `limpiable` y deja pasar los demás usos (un guard que no se pone rojo no vigila nada)', () => {
    const centinela = "<SelectBuscable value={v} onChange={f} opciones={[{ value: TODOS, label: 'Todos' }, ...xs]}"
    expect(pideLaCruzConUnCentinela(`${centinela} limpiable />`)).toBe(true)
    expect(pideLaCruzConUnCentinela(`${centinela} limpiable={true} />`)).toBe(true)
    expect(pideLaCruzConUnCentinela(`${centinela} />`)).toBe(false)
    expect(pideLaCruzConUnCentinela(`${centinela} limpiable={false} />`)).toBe(false)
    expect(pideLaCruzConUnCentinela("<SelectBuscable value={v} onChange={f} opciones={xs} limpiable />")).toBe(false)
  })

  it('un uso con una opción de valor-constante (TODOS, NONE, SIN_…) no lleva `limpiable`: la × mandaría \'\' y el estado no lo entiende', () => {
    const infracciones = todos
      .filter((u) => pideLaCruzConUnCentinela(u.etiqueta))
      .map((u) => `${u.archivo}:${u.linea}: <SelectBuscable> con una opción de valor-constante y con limpiable: la × mandaría '' y el estado no lo entiende`)
    expect(infracciones).toEqual([])
  })
})
