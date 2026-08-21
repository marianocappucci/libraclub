// La identidad de LibraClub en la pantalla que la muestra sin sesión: el logo
// a 72 px y el nombre en Montserrat Bold #2d2d2d, como los otros siete
// productos de la familia.
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
  it('🔴 el logo mide 72 px', async () => {
    await pantalla()
    const logo = screen.getByRole('img', { name: 'LibraClub' })
    // El nombre del archivo y no la ruta entera: Vite le pone un hash al asset
    // y fijarlo haría fallar el test en cada rebuild.
    expect(logo).toHaveAttribute('src', expect.stringContaining('logo-libraclub'))
    expect(logo.className).toContain('h-[72px]')
    // La contracara: sin clase propia queda el tamaño con el que libra-ui
    // dibuja el box de la inicial, que es el defecto que este test cierra.
    expect(logo.className).not.toContain('h-10')
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
