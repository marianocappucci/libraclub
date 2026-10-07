// La identidad de LibraClub en la pantalla que la muestra sin sesión: la marca
// (el icono sobre un cuadrado del verde) y el nombre en Montserrat Bold #2d2d2d,
// como los otros siete productos de la familia.
//
// 🔴 Existe por un defecto real. LibraClub adoptó el logo del kit el
// 2026-08-21 pero no el CABLEADO que lo acompaña: pasaba `logo` sin clase de
// tamaño y sin `wordmarkClassName`, así que `libra-ui` lo dibujaba al tamaño
// del box de la inicial que reemplaza —la mitad— y el nombre salía con la
// tipografía de la interfaz. Los iconos estaban bien, el archivo era el
// correcto, y aun así la pantalla no era la de la familia.
//
// El MECANISMO —que `logo` gane sobre la inicial, que `cn` mergee las clases—
// lo prueba libra-ui. Lo de acá es lo que este producto le pasa, que es
// justamente lo que el motor no puede ver.
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthProvider } from '@/context/AuthContext'
import { WORDMARK } from '@/branding'

import { Login } from '@/pages/Login'

afterEach(() => {
  vi.unstubAllGlobals()
})

/** Igual que en `Login.demo.test.tsx`: la pantalla pide `/auth/me` y la sonda
 *  de demo antes de dibujarse. */
function montar() {
  vi.stubGlobal('fetch', vi.fn(async () =>
    new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
  ))
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Login />
      </AuthProvider>
    </MemoryRouter>,
  )
}

async function pantalla() {
  const { container } = montar()
  await waitFor(() => expect(container.querySelector('input[type="password"]')).not.toBeNull())
}

describe('el login', () => {
  it('🔴 muestra la marca del producto (el icono sobre un cuadrado de su verde), no un logo ilustrado', async () => {
    await pantalla()
    const marca = screen.getByRole('img', { name: 'LibraClub' })
    // La marca (libra-ui ADR-033) es un cuadrado con un icono SVG adentro: no una <img> con un asset. Si alguien vuelve a pasar `logo`, o
    // `producto` se pierde, el elemento deja de ser un div con fondo y esto se pone rojo.
    expect(marca.tagName).toBe('DIV')
    expect(marca).not.toHaveAttribute('src')
    expect(marca.querySelector('svg')).not.toBeNull()
    // El cuadrado es el `color` de la identidad de LibraClub (`libra-ui/identidad`), el mismo verde que la landing y que `MARCA`. Desde libra-ui
    // v0.124.0 (ADR-034) la marca es un SVG incrustado y el cuadrado va DENTRO del dibujo: ya no es el `background-color` del contenedor.
    expect(marca.innerHTML.toLowerCase()).toContain('#017b4b')
    // `Login` la dibuja a 48 px (`h-12 w-12`, libra-ui v0.124.0: el dibujo tiene más detalle que un glifo); el default del cuadrado (32 px)
    // tiene que haber PERDIDO el merge.
    expect(marca.className).toContain('h-12')
    expect(marca.className).not.toContain('h-8')
  })

  it('🔴 el nombre va en Montserrat Bold #2d2d2d, a 22 px', async () => {
    await pantalla()
    const nombre = screen.getByText('LibraClub')
    for (const clase of WORDMARK.split(' ')) expect(nombre.className).toContain(clase)
    expect(nombre.className).toContain('text-[22px]')
    // El default de libra-ui tiene que haber PERDIDO el merge: si sobreviviera,
    // el tamaño lo decidiría el orden en que Tailwind emite las reglas.
    expect(nombre.className).not.toContain('text-xl')
  })
})

// 🔴 Los fuentes se leen con `fs`, como DATOS: con `import.meta.glob` cada
// archivo entraría al grafo de módulos y su cobertura saltaría a 100 % sin un
// solo test nuevo.
describe('el color del wordmark se define una sola vez', () => {
  const COLOR = '#2d2d2d'

  function fuentes(dir: string): string[] {
    return readdirSync(join(process.cwd(), dir), { withFileTypes: true }).flatMap((e) =>
      e.isDirectory()
        ? fuentes(join(dir, e.name))
        : /\.tsx?$/.test(e.name) ? [join(dir, e.name)] : [],
    )
  }

  it('🔴 ningún archivo fuera de branding.ts escribe el color a mano', () => {
    // El login y la sidebar no se ven juntos: una copia que diverja no la
    // reporta nadie. Este es el único chequeo que mira TODO el árbol y no sólo
    // lo que algún test monta.
    const culpables = fuentes('src')
      .filter((f) => !f.endsWith('branding.ts') && !f.includes('/test/'))
      .filter((f) => readFileSync(join(process.cwd(), f), 'utf8').includes(COLOR))
    expect(culpables).toEqual([])
  })

  it('el control — branding.ts sí lo tiene, y el lector ve los archivos', () => {
    // Sin esto, el caso de arriba pasaría en verde con una lista vacía o con el
    // color cambiado y nadie enterándose.
    expect(fuentes('src').length).toBeGreaterThan(30)
    expect(readFileSync(join(process.cwd(), 'src/branding.ts'), 'utf8')).toContain(COLOR)
  })
})
