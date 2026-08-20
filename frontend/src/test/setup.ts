import '@testing-library/jest-dom/vitest'

/**
 * jsdom no implementa `<dialog>`.
 *
 * Medido: en jsdom 25, `showModal` y `close` de un `<dialog>` son `undefined`,
 * así que cualquier componente que los llame explota con "is not a function" —
 * un error que habla del arnés y no del código.
 *
 * 🟡 **Esto es un doble, y hay que saber qué NO prueba.** El stub sólo mueve el
 * atributo `open`: no atrapa el foco, no marca el resto de la página como
 * inerte y no cierra con `Escape`. Todo eso lo pone el navegador de verdad, y
 * **ningún test de este repo lo verifica** — si algún día importa, se mide en
 * un navegador, no acá.
 */
/**
 * jsdom tampoco implementa `Range.getBoundingClientRect()`.
 *
 * `libra-ui/data-table` lo usa para medir el ancho natural de cada encabezado y
 * dimensionar las columnas. En jsdom devuelve `undefined` y el render explota
 * con "Cannot read properties of undefined (reading 'width')" — un error que
 * habla del entorno de test y no del código.
 *
 * 🟡 **Devuelve ceros, y hay que saber qué NO prueba.** Cualquier cosa que
 * dependa del ancho medido —que una columna no se corte, que la tabla no se
 * desborde— es invisible acá. Eso se mide en un navegador de verdad, y para
 * esta pantalla se midió así el 2026-08-20.
 */
if (typeof Range !== 'undefined' && !Range.prototype.getBoundingClientRect) {
  const vacio = () =>
    ({
      x: 0, y: 0, width: 0, height: 0,
      top: 0, right: 0, bottom: 0, left: 0,
      toJSON: () => ({}),
    }) as DOMRect
  Range.prototype.getBoundingClientRect = vacio
  Range.prototype.getClientRects = () =>
    ({ length: 0, item: () => null, [Symbol.iterator]: function* () {} }) as unknown as DOMRectList
}

if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function abrir(this: HTMLDialogElement) {
    this.open = true
  }
  HTMLDialogElement.prototype.close = function cerrar(this: HTMLDialogElement) {
    this.open = false
    this.dispatchEvent(new Event('close'))
  }
}

/**
 * jsdom no implementa `window.matchMedia`.
 *
 * `libra-ui/use-mobile` lo llama para decidir si la sidebar arranca colapsada,
 * así que **cualquier** test que monte el Layout del kit explota con
 * "matchMedia is not a function" — un error del entorno, no del código.
 *
 * 🟡 **Devuelve siempre "no matchea", y hay que saber qué NO prueba.** Con este
 * doble todo test corre en la rama de escritorio: el comportamiento en mobile
 * —que la sidebar arranque cerrada, que aparezca el trigger flotante— es
 * invisible acá. Eso se mide en un navegador, redimensionando de verdad.
 */
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList
}
