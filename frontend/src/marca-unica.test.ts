// El verde de LibraClub está escrito en dos lugares, y tienen que decir lo mismo.
//
// 🔑 **No es una duplicación evitable.** `branding.ts` lo exporta como literal
// de JavaScript —lo usa el nombre del producto al lado del logo, en el login y
// en la sidebar— y `index.css` lo declara como token de CSS, que es lo único que
// pueden leer las reglas del ítem activo del menú y del encabezado de cancha de
// la agenda. No hay forma de compartir un literal entre los dos sin generar uno
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

  it('🔴 las dos reglas que usan el token siguen ahí', () => {
    // El token puede quedar declarado y sin usar, que es exactamente lo que le
    // pasó a los tokens de estado de la grilla: se declararon y se sacaron el
    // mismo día porque la agenda pintaba con clases fijas. Un bloque que dice
    // «esta es la paleta» mientras nadie la usa es peor que no tenerlo.
    expect(CSS).toMatch(/\[data-active='true'\][\s\S]{0,120}border-color:\s*var\(--marca\)/)
    expect(CSS).toMatch(/\.encabezado-de-cancha[\s\S]{0,200}var\(--marca\)/)
  })
})
