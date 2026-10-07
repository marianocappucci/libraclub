// El verde de LibraClub está escrito en dos lugares, y tienen que decir lo mismo.
//
// 🔑 **No es una duplicación evitable.** `branding.ts` lo exporta como literal
// de JavaScript —lo usa el nombre del producto al lado del logo, en el login y
// en la sidebar— y `index.css` lo declara como token de CSS, que es lo único que
// pueden leer las reglas del encabezado de cancha de la agenda. (El ítem activo
// del menú ya no usa este token: lo pinta `aplicarIdentidad`, ver más abajo.) No
// hay forma de compartir un literal entre los dos sin generar uno
// desde el otro.
//
// 🔴 **Y el modo de fallar es invisible.** Nadie mira el nombre del producto y
// el borde del menú al mismo tiempo: si uno se toca y el otro no, quedan dos
// verdes que casi coinciden y nadie lo reporta nunca. Este test es lo único que
// los ata.
//
// El valor no se inventó en ninguno de los dos: sale del `--brand` de la landing
// (`libraclub_web`), que genera `libra-web-kit` desde `site_css_tokens.py`.
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { MARCA } from '@/branding'

const CSS = readFileSync(join(process.cwd(), 'src', 'index.css'), 'utf8')

function tokenDeMarca(css: string): string | null {
  const m = /^\s*--marca:\s*([^;]+);/m.exec(css)
  return m ? m[1].trim() : null
}

describe('el verde de la marca', () => {
  it('🔴 el token de CSS dice lo mismo que `branding.ts`', () => {
    expect(tokenDeMarca(CSS)).toBe(MARCA)
  })

  it('🔴 el control — el lector encuentra el token, no devuelve null', () => {
    // Sin esto, el caso de arriba pasaría en verde el día que el regex deje de
    // matchear: compararía `null` contra `null` si alguien "arreglara" el test.
    expect(tokenDeMarca(CSS)).not.toBeNull()
    expect(tokenDeMarca('  --marca: #123456;')).toBe('#123456')
    expect(tokenDeMarca('/* sin token */')).toBeNull()
  })

  it('🔴 el color del ítem activo del menú lo pone la identidad del kit, no una variable propia', () => {
    // Desde libra-ui 0.126.0 (ADR-036) `aplicarIdentidad('libraclub')` fija `--libra-menu-activo-fondo|borde|texto` desde el color del producto. Si
    // el `index.css` volviera a declararlas, el defecto de LibraClub dejaría de salir de la identidad (y de lo que muestra «Apariencia»).
    expect(CSS).not.toMatch(/--libra-menu-activo-/)
    // Y la identidad tiene que seguir aplicándose, en el arranque, con el producto correcto.
    const MAIN = readFileSync(join(process.cwd(), 'src', 'main.tsx'), 'utf8')
    expect(MAIN).toMatch(/aplicarIdentidad\('libraclub'\)/)
  })

  it('🔴 la regla que usa el token sigue ahí', () => {
    // El token puede quedar declarado y sin usar, que es exactamente lo que le
    // pasó a los tokens de estado de la grilla: se declararon y se sacaron el
    // mismo día porque la agenda pintaba con clases fijas. Un bloque que dice
    // «esta es la paleta» mientras nadie la usa es peor que no tenerlo.
    // 🔴 **Las DOS declaraciones del encabezado, no «alguna».** La primera
    // versión pedía un `var(--marca)` en los 200 caracteres siguientes a la
    // clase, y eso lo cumplía la línea del borde aunque el fondo se hubiera
    // hardcodeado. Lo delató la mutación: hardcodear el fondo dejaba el guard
    // en verde.
    const mezclas = CSS.match(
      /@supports \(color: color-mix[\s\S]*?\.encabezado-de-cancha \{([\s\S]*?)\}/,
    )
    expect(mezclas).not.toBeNull()
    const cuerpo = mezclas?.[1] ?? ''
    expect(cuerpo).toMatch(/background-color:\s*color-mix\([^)]*var\(--marca\)/)
    expect(cuerpo).toMatch(/border-bottom-color:\s*color-mix\([^)]*var\(--marca\)/)
  })
})
