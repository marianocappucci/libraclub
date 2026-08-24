// Guard: ningún día del calendario se saca de un `toISOString()`.
//
// 🔴 La regla que busca es la **propiedad final**, no el nombre de un helper:
// "un `aaaa-mm-dd` no se deriva nunca de un instante en UTC". Prohibir en
// cambio `todayIso` —el nombre que tenían las copias— habría dejado pasar la
// próxima, que se va a llamar de otra forma.
//
// Y prohíbe el RECORTE, no `toISOString()` a secas: mandarle a la API un
// instante completo en UTC está bien y se sigue haciendo. Lo que nunca está
// bien es quedarse con los primeros diez caracteres, porque a partir de las
// 21:00 de Argentina esos diez caracteres son los de mañana.
//
// Lee el FUENTE en vez de renderizar: son decenas de pantallas, muchas detrás
// de una sesión y de datos que habría que sembrar. El precio es que no ve una
// fuga que pase por una variable intermedia; a cambio cubre todas, no las
// pocas que tienen test de render.
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { cwd } from 'node:process'

import { describe, expect, it } from 'vitest'

/** El frontend del producto. `cwd()` en vitest es el directorio del proyecto. */
const RAIZ = cwd()
const DIRECTORIOS = [join(RAIZ, 'src')]
/** Si el barrido ve menos que esto, la ruta está mal y el cero no vale. */
const MINIMO_DE_ARCHIVOS = 20

/** 🔴 **Vacía a propósito, y esa es la afirmación.** Ningún módulo de este
 *  producto deriva un día del calendario de un `toISOString()`: eso lo hace
 *  `libra-ui/fechas`, donde el `Date` está anclado al mediodía UTC. Si algún
 *  día hiciera falta una exención, se agrega acá con su razón — no se ensancha
 *  el patrón. */
const EXENTAS: string[] = []

/** Sacarle el día a un instante UTC. Las tres formas que toma en la práctica. */
const RECORTE_UTC =
  /\.toISOString\(\)\s*\.\s*(?:slice|substring)\(\s*0\s*,\s*10\s*\)|\.toISOString\(\)\s*\.\s*split\(\s*['"]T['"]\s*\)\s*\[\s*0\s*\]/

/**
 * El primero del mes armado con la zona del navegador.
 *
 * Hoy no da el día equivocado en Argentina —por eso sobrevivió a la barrida
 * anterior— pero decide QUÉ MES es con el reloj de la máquina del cliente.
 */
const PRIMERO_DE_MES_LOCAL =
  /new Date\(\s*\w+\.getFullYear\(\)\s*,\s*\w+\.getMonth\(\)/

export function fugasEn(texto: string): number[] {
  const fugas: number[] = []
  texto.split('\n').forEach((linea, i) => {
    // Un comentario que EXPLICA el patrón prohibido no es un uso. Sin esta
    // línea, el guard se marcaría a sí mismo y a cada docstring que documenta
    // por qué la regla existe.
    if (/^\s*(?:\/\/|\/\*|\*)/.test(linea)) return
    if (RECORTE_UTC.test(linea) || PRIMERO_DE_MES_LOCAL.test(linea)) {
      fugas.push(i + 1)
    }
  })
  return fugas
}

function archivos(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) return archivos(p)
    return /\.tsx?$/.test(n) && !/\.test\./.test(n) ? [p] : []
  })
}

describe('ningún día del calendario sale de un toISOString', () => {
  it('el detector encuentra una fuga cuando la hay', () => {
    // 🔴 Control POSITIVO. Sin él, un regex roto —uno que no matchea nada— da
    // exactamente el mismo verde que un código limpio: el cero de más abajo
    // sólo significa algo si este test pasa.
    expect(fugasEn('  return new Date().toISOString().slice(0, 10)')).toEqual([1])
    expect(fugasEn('  return d.toISOString().substring(0, 10)')).toEqual([1])
    expect(fugasEn("  const hoy = new Date().toISOString().split('T')[0]")).toEqual([1])
    expect(fugasEn('  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString()')).toEqual([1])
  })

  it('el detector NO marca lo que la regla permite', () => {
    // Un instante completo en UTC es legítimo: eso es un timestamp, no un día.
    expect(fugasEn('  await api.post(url, { ts: new Date().toISOString() })')).toEqual([])
    // Y un comentario que explica la regla no es un uso.
    expect(fugasEn('  // 🔴 NO usar new Date().toISOString().slice(0, 10)')).toEqual([])
    expect(fugasEn('   * `toISOString().slice(0, 10)` da la fecha en UTC.')).toEqual([])
  })

  it('la lista de exentas está vacía en este producto', () => {
    // 🔴 Un `for` sobre una lista vacía es un test que no puede fallar. Éste
    // sí: afirma que en este producto NADA está exento, que es la propiedad
    // que se quiere sostener. El día que alguien agregue una ruta, este assert
    // lo obliga a mirar esta decisión.
    expect(EXENTAS).toEqual([])
  })

  it('el detector distingue el recorte a 10 del recorte a 19', () => {
    // `slice(0, 19)` es "un instante sin los milisegundos", no un día. La
    // distinción importa: prohibirlo también habría hecho ruido sobre código
    // correcto y el guard se habría terminado apagando.
    expect(fugasEn('  return d.toISOString().slice(0, 19)')).toEqual([])
  })

  it('las exenciones son rutas vivas, no comodines olvidados', () => {
    // 🔴 Una exención que apunta a un archivo que ya no existe no protege nada
    // y **sigue tapando** todo lo que su patrón alcance. Si alguien renombra o
    // borra un módulo exento, esto avisa acá en vez de dejar un agujero mudo.
    for (const ruta of EXENTAS) {
      expect(existsSync(join(RAIZ, ruta))).toBe(true)
    }
  })

  it('no queda ninguna fuga en el código', () => {
    const sitios: string[] = []
    let revisados = 0
    for (const dir of DIRECTORIOS) {
      for (const f of archivos(dir)) {
        // 🔴 Comparación EXACTA contra la lista, no `endsWith('fechas.ts')`.
        // Aquel sufijo eximía también al `lib/fechas.ts` de cada producto —el
        // módulo de presentación, que no tiene ninguna razón para estar
        // exento— y así el guard tenía un punto ciego del tamaño de un archivo
        // entero.
        if (EXENTAS.includes(relative(RAIZ, f))) continue
        revisados += 1
        for (const linea of fugasEn(readFileSync(f, 'utf8'))) {
          sitios.push(`${relative(RAIZ, f)}:${linea}`)
        }
      }
    }
    // 🔴 Sin este assert, una ruta mal armada haría que el barrido no
    // encontrara ningún archivo y la lista vacía de abajo daría verde. Un cero
    // que también es el cero de "no miré nada" no prueba nada.
    expect(revisados).toBeGreaterThan(MINIMO_DE_ARCHIVOS)
    expect(sitios).toEqual([])
  })
})
