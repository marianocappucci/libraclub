// El icono del título es el que el sidebar le da a esa misma pantalla.
//
// 🔴 **Lee los FUENTES, no el DOM.** Lo que hay que impedir no es que una
// pantalla se rompa —ninguna se rompe con el icono equivocado— sino que
// **vuelvan a divergir**: eso se ve cruzando el mapa de navegación contra cada
// pantalla, y sólo si alguien se acuerda de cruzar. El motor vive en
// `libra-ui/auditoria-de-titulos` y tiene sus propios tests allá.
//
// ⚠️ **Lo que este guard NO cubre**: las pantallas que `libra-ui` rinde enteras
// —`/usuarios`, `/logs` y `/configuracion`—, porque no viven en `pages/` de
// este producto. A ésas las cubre el TIPO: desde la v0.34.0 el `icono` es una
// prop requerida, así que el compilador no deja montarlas sin pasarlo.
import { describe, expect, it } from 'vitest'
import { join } from 'node:path'
import { auditarTitulos, describirDesajustes } from 'libra-ui/auditoria-de-titulos'

const SRC = join(process.cwd(), 'src')

describe('el icono del título sale del sidebar', () => {
  it('🔴 ninguna pantalla usa un icono distinto al de su entrada del menú', () => {
    expect(describirDesajustes(auditarTitulos(SRC).distinto)).toEqual([])
  })

  it('🔴 ninguna pantalla del menú tiene el título sin icono', () => {
    // La lista es EXACTA y no un "contiene": una pantalla nueva sin icono hace
    // fallar esto igual, que es lo que el guard viene a cuidar.
    expect(describirDesajustes(auditarTitulos(SRC).sinIcono)).toEqual([
      // 🔑 La agenda **no tiene título de pantalla**. Su único `<h2>` es el
      // encabezado de cada cancha, adentro de un `.map()`, y el auditor —que
      // busca el primer `<h1>`/`<h2>` del archivo— lo toma por el título.
      // Ponerle un `TituloPantalla` sería AGREGAR un título, no darle el icono
      // al que ya hay, que no es lo que se pidió. Queda documentado acá en vez
      // de silenciado adentro del auditor: si algún día la agenda estrena
      // título propio, esta línea falla y obliga a mirarlo.
      '/agenda (Agenda): título=título SIN icono, sidebar=CalendarDays',
    ])
  })

  it('🔴 el control — el guard midió algo', () => {
    // Sin esto, los dos casos de arriba pasarían en verde si el parser dejara
    // de encontrar el Layout, el router o las pantallas: dos listas vacías
    // contra dos listas vacías. Es la forma en que este guard falló mientras se
    // escribía.
    const { rutasDelNav, pantallas, conIcono } = auditarTitulos(SRC)
    expect(rutasDelNav).toBeGreaterThanOrEqual(7)
    expect(pantallas).toBeGreaterThanOrEqual(7)
    expect(conIcono).toBeGreaterThan(0)
  })
})
