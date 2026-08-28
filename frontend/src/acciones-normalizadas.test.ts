// La columna de acciones de toda tabla lleva su título, y sus botones llevan
// borde.
//
// 🔴 **Lee los FUENTES, no el DOM**, igual que el guard de los iconos del
// título. Lo que hay que impedir no es que una pantalla se rompa —ninguna se
// rompe sin encabezado ni sin borde— sino que **vuelvan a divergir**, y eso sólo
// se ve mirando todas las tablas a la vez.
//
// El estado que lo motivó (2026-08-28, reportado por el humano mirando `dev`):
// las **tres** columnas de acciones del producto tenían `header: ''` y sus
// **seis** botones eran `ghost`, sin un borde que los delimite. Contalibra, que
// es la referencia, tiene título en 12 de sus 17 columnas y 42 botones `outline`
// contra 10 `ghost`. Y el mismo día entró la bandeja de MercadoPago, que viene
// del kit y usa `outline`: quedaron los dos estilos conviviendo en la app.
//
// ⚠️ `ghost` **no está prohibido**: Contalibra lo usa para controles adentro de
// un formulario —quitar una línea de una factura, por ejemplo— y este producto
// también. Lo que este guard mira es sólo lo que hay **dentro de una columna de
// acciones**.
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const SRC = join(process.cwd(), 'src')

type Columna = { archivo: string; bloque: string }

/** Los archivos de pantalla y de componente, sin los tests. */
function fuentes(): { nombre: string; texto: string }[] {
  const salida: { nombre: string; texto: string }[] = []
  for (const carpeta of ['pages', 'components']) {
    for (const f of readdirSync(join(SRC, carpeta))) {
      if (!f.endsWith('.tsx') || f.includes('.test.')) continue
      salida.push({
        nombre: `${carpeta}/${f}`,
        texto: readFileSync(join(SRC, carpeta, f), 'utf8'),
      })
    }
  }
  return salida
}

/** Cada definición de columna de acciones, desde su `id` hasta que la sangría
 *  vuelve al nivel en el que abrió. Es lo que delimita un objeto de columna en
 *  estos archivos sin tener que parsear TypeScript. */
function columnasDeAcciones(): Columna[] {
  const encontradas: Columna[] = []
  for (const { nombre, texto } of fuentes()) {
    const lineas = texto.split('\n')
    for (let i = 0; i < lineas.length; i++) {
      const m = /^(\s*)id:\s*'acciones',/.exec(lineas[i])
      if (!m) continue
      const sangria = m[1]
      const bloque = [lineas[i]]
      for (let j = i + 1; j < lineas.length; j++) {
        bloque.push(lineas[j])
        if (lineas[j] === `${sangria}},`) break
      }
      encontradas.push({ archivo: nombre, bloque: bloque.join('\n') })
    }
  }
  return encontradas
}

const COLUMNAS = columnasDeAcciones()

describe('las columnas de acciones', () => {
  it('🔴 el control — el guard encontró tablas de verdad', () => {
    // Sin esto, los dos casos de abajo pasarían en verde el día que el regex
    // deje de matchear: una lista vacía cumple cualquier condición. Es la forma
    // exacta en que este tipo de guard falla sin avisar.
    expect(COLUMNAS.length).toBeGreaterThanOrEqual(4)
    expect(COLUMNAS.map((c) => c.archivo)).toContain('components/listado.tsx')
  })

  it('🔴 todas llevan el título «Acciones»', () => {
    const sinTitulo = COLUMNAS
      .filter((c) => !/header:.*Acciones/.test(c.bloque))
      .map((c) => c.archivo)
    expect(sinTitulo).toEqual([])
  })

  it('🔴 sus botones llevan borde, no son `ghost`', () => {
    const sinBorde = COLUMNAS
      .filter((c) => /variant="ghost"/.test(c.bloque))
      .map((c) => c.archivo)
    expect(sinBorde).toEqual([])
  })

  it('🔴 el segundo control — el guard sabe reconocer una columna mal hecha', () => {
    // Los dos casos de arriba comparan contra una lista vacía, así que pasarían
    // igual si los regex no matchearan nada. Acá se les da de comer una columna
    // rota a propósito y se verifica que la marquen.
    const rota = `        id: 'acciones',
        header: '',
        cell: () => <Button variant="ghost" size="icon" />,
        },`
    expect(/header:.*Acciones/.test(rota)).toBe(false)
    expect(/variant="ghost"/.test(rota)).toBe(true)

    // Y el positivo: una bien hecha no se marca.
    const sana = `        id: 'acciones',
        header: () => <div className="text-right">Acciones</div>,
        cell: () => <Button variant="outline" size="icon" />,
        },`
    expect(/header:.*Acciones/.test(sana)).toBe(true)
    expect(/variant="ghost"/.test(sana)).toBe(false)
  })
})

/** El primer `className` del `return (` de la pantalla: su contenedor. */
function contenedorDe(texto: string): string | null {
  const lineas = texto.split('\n')
  for (let i = 0; i < lineas.length; i++) {
    if (!/^\s*return \(\s*$/.test(lineas[i])) continue
    for (let j = i + 1; j < Math.min(i + 4, lineas.length); j++) {
      const m = /className="([^"]*)"/.exec(lineas[j])
      if (m) return m[1]
    }
  }
  return null
}

describe('el ancho de las pantallas', () => {
  it('🔴 ninguna pantalla se topea el ancho a sí misma', () => {
    // `FacturaNueva` abría con `max-w-4xl` y era la ÚNICA de las 22 con un tope
    // en su contenedor: el humano lo vio como "no ocupa el ancho de la pantalla"
    // el 2026-08-28. El ancho lo decide el layout, que es uno solo para todas;
    // una pantalla que se lo pone encima queda angosta sin que nada lo explique.
    // Contalibra, de donde salió esa pantalla, tampoco tiene ninguno.
    //
    // ⚠️ Mira **el contenedor**, no el archivo entero: `max-w-sm` adentro de una
    // tarjeta —como el arqueo de Caja— es legítimo y no tiene nada que ver.
    const topeadas = fuentes()
      .map(({ nombre, texto }) => ({ nombre, clase: contenedorDe(texto) ?? '' }))
      .filter(({ clase }) => /\bmax-w-/.test(clase))
      .map(({ nombre }) => nombre)
    expect(topeadas).toEqual([])
  })

  it('🔴 el control — el detector distingue el contenedor de una tarjeta', () => {
    // Sin esto, la lista vacía de arriba pasaría igual si `contenedorDe`
    // devolviera siempre `null`.
    const conTope = 'export function X() {\n  return (\n    <div className="grid max-w-4xl gap-4">\n'
    const sinTope = 'export function X() {\n  return (\n    <div className="space-y-3">\n'
    expect(contenedorDe(conTope)).toBe('grid max-w-4xl gap-4')
    expect(contenedorDe(sinTope)).toBe('space-y-3')
    // Y una tarjeta con tope, ADENTRO, no es el contenedor de la pantalla.
    const tarjeta = 'export function X() {\n  return (\n    <div className="space-y-4">\n      <div className="max-w-sm rounded-lg border" />\n'
    expect(contenedorDe(tarjeta)).toBe('space-y-4')
    expect(/\bmax-w-/.test(contenedorDe(tarjeta) ?? '')).toBe(false)
  })

  it('🔴 el tercer control — hay pantallas que mirar', () => {
    const conContenedor = fuentes().filter(({ texto }) => contenedorDe(texto) !== null)
    expect(conContenedor.length).toBeGreaterThanOrEqual(10)
  })
})
