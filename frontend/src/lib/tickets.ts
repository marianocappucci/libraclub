/**
 * Abrir un PDF para imprimirlo desde el visor del navegador: un ticket del
 * cierre diario (el del día o el de un turno) o el recibo de un turno.
 *
 * Un solo helper para todos: las rutas (`cierreDiario.urlDelTicket`,
 * `cierreDiario.urlDelTicketDeTurno`, `cobroDelTurno.urlDelRecibo`) son del
 * mismo origen que la SPA, así que
 * la cookie de sesión viaja sola en la navegación — no hace falta `fetch` ni
 * armar un blob, mismo criterio que `facturacion.urlDelPdf` en `lib/api.ts`.
 * `window.open` y no un `<a target="_blank">` porque los tres lugares que
 * imprimen un ticket son un botón de fila de tabla o el aviso de éxito de un
 * cierre, no un enlace suelto en la pantalla.
 */
export function abrirTicket(url: string): void {
  window.open(url, '_blank', 'noopener')
}
