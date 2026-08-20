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
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function abrir(this: HTMLDialogElement) {
    this.open = true
  }
  HTMLDialogElement.prototype.close = function cerrar(this: HTMLDialogElement) {
    this.open = false
    this.dispatchEvent(new Event('close'))
  }
}
