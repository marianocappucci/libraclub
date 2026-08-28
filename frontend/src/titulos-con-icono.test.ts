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
    // ✅ **La lista quedó vacía el 2026-08-28.** Tenía una sola excepción, la
    // agenda: su único `<h2>` era el encabezado de cada cancha, adentro de un
    // `.map()`, y el auditor lo tomaba por el título. La nota de entonces decía
    // que ponerle un `TituloPantalla` sería *agregar* un título y no darle el
    // icono al que ya había — que es exactamente lo que el humano pidió el
    // 2026-08-28. Al estrenarlo, esta línea falló y obligó a mirarlo, que era
    // para lo que estaba escrita.
    expect(describirDesajustes(auditarTitulos(SRC).sinIcono)).toEqual([])
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
