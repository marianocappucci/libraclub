import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Guarda contra la vuelta de los colores fijos.
 *
 * El 2026-08-20 se migraron 134 usos de `slate-*` a los tokens del tema
 * (`text-muted-foreground`, `bg-card`, `border-input`…). Sin esta guarda, la
 * próxima pantalla nace con `text-slate-600` porque es lo que había en las
 * otras, y a los tres meses la mitad del producto volvió a estar fija.
 *
 * 🔴 **El patrón exige el prefijo de utilidad, y ahí está la trampa.** Un
 * `includes('slate-')` pelado matchea **`translate-x-`**, que shadcn usa en el
 * diálogo y en el sheet: daba 147 "pendientes" e incluía los `components/ui/`,
 * que están limpios. Medido el mismo día. El test de más abajo prueba que el
 * patrón discrimina — sin él, esta guarda podría estar contando cualquier cosa.
 *
 * Se lee el FUENTE y no el DOM a propósito: cubre las 14 pantallas de una vez,
 * incluidas las que ningún test renderiza.
 */

//: `process.cwd()` es la raíz del proyecto cuando corre vitest.
const RAIZ = join(process.cwd(), 'src')

//: Las utilidades de color de Tailwind con paleta fija. `bg-white` y
//: `text-white` entran también: son igual de fijas que un `slate-500`.
const FIJO =
  /(?:^|[\s"'`:{])(?:bg|text|border|ring|divide|placeholder|from|to|via|shadow|outline|accent|caret|decoration)-(?:slate|gray|zinc|neutral|stone)-\d{2,3}\b/

//: Lo que sí puede tener color fijo, con el motivo.
const PERMITIDO: Record<string, string> = {
  // La paleta de dominio de la grilla: ámbar lo que falta cerrar, esmeralda lo
  // confirmado, gris lo que ya pasó. No se puede tokenizar porque `--muted`,
  // `--accent` y `--secondary` son los tres `oklch(0.97 0 0)` en este tema, y
  // `jugada` y `bloqueo` quedarían del mismo color. Ver el comentario del mapa
  // `COLOR` en esa pantalla.
  'pages/Agenda.tsx': 'la paleta de estados de la grilla',
}

function tsx(dir: string, acc: string[] = []): string[] {
  for (const e of readdirSync(join(RAIZ, dir), { withFileTypes: true })) {
    const rel = `${dir}/${e.name}`
    if (e.isDirectory()) {
      // `components/ui` es shadcn vendorizado: no se edita a mano acá.
      if (e.name !== 'ui') tsx(rel, acc)
    } else if (e.name.endsWith('.tsx') && !e.name.endsWith('.test.tsx')) {
      acc.push(rel.replace(/^\//, ''))
    }
  }
  return acc
}

describe('no vuelven los colores fijos', () => {
  it('ninguna pantalla usa la paleta gris de Tailwind en vez de los tokens', () => {
    const archivos = [...tsx('components'), ...tsx('pages')]
    // 🔴 Sin esto, una raíz mal resuelta escanea CERO archivos y el test pasa
    // en verde sin haber mirado nada. Ya pasó al escribirlo: `import.meta.url`
    // resolvía a `/src` y el `readdirSync` tiraba ENOENT — con un `try` de más
    // habría quedado verde y vacío.
    expect(archivos.length).toBeGreaterThan(10)

    const culpables: string[] = []
    for (const archivo of archivos) {
      if (archivo in PERMITIDO) continue
      const lineas = readFileSync(join(RAIZ, archivo), 'utf8').split('\n')
      lineas.forEach((l, i) => {
        // Los comentarios quedan afuera: hay uno en `Login.tsx` que **cita** un
        // `border-slate-300` para contar qué reemplazó. Citarlo no es usarlo.
        if (/^\s*(\/\/|\*|\/\*)/.test(l)) return
        if (FIJO.test(l)) culpables.push(`${archivo}:${i + 1}  ${l.trim().slice(0, 70)}`)
      })
    }
    expect(culpables, `usar tokens del tema:\n${culpables.join('\n')}`).toEqual([])
  })

  // 🔑 Control positivo. Sin esto, un patrón roto haría pasar el test de arriba
  // siempre, y la guarda no guardaría nada.
  it('el patrón detecta lo que tiene que detectar', () => {
    expect(FIJO.test('<p className="text-slate-600">')).toBe(true)
    expect(FIJO.test("const c = 'bg-gray-100 border-zinc-300'")).toBe(true)
    expect(FIJO.test('className="rounded border-neutral-400"')).toBe(true)
  })

  // 🔴 Control negativo, y es el que importa: `translate-x-` **contiene** la
  // subcadena `slate-`. Un patrón sin el prefijo de utilidad marcaría todo el
  // `components/ui` de shadcn, que está limpio.
  it('el patrón NO se come a translate-, que contiene "slate-"', () => {
    expect(FIJO.test('className="translate-x-[-50%] translate-y-[-50%]"')).toBe(false)
    expect(FIJO.test('data-[state=open]:slide-in-from-top-2')).toBe(false)
    expect(FIJO.test('className="text-muted-foreground bg-card border-input"')).toBe(false)
  })
})
