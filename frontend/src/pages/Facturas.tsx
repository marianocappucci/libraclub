// Shim sobre libra-ui/Facturas, la misma pantalla que Contalibra y Restolibra.
//
// 🔑 **Este producto NO era una tercera copia**: su listado se escribió aparte y
// difería en 448 líneas. Entra acá por un motivo funcional, no de prolijidad —
// desde que LibraClub emite notas de crédito y débito (2026-08-27), el listado
// sin pestañas las dejaba sin ningún lugar donde verse.
//
// Dos cosas que este producto apaga:
//
// - **`muestraCobros`**, porque el cruce `caja_movimientos.factura_id` sólo lo
//   llena el cobro por QR: el efectivo se carga como monto y concepto libre, sin
//   vínculo con la reserva. Con esto prendido, todo lo cobrado en efectivo diría
//   «Sin cobrar». Es la misma decisión que se tomó para la columna de cobrado.
// `rutaDelDetalle` **sí** va desde el 2026-08-27: la pantalla de detalle existe
// y es la compartida del kit. Antes estaba apagada porque `/facturas/:id` no
// existía, y un botón hacia una ruta inexistente en estas SPA no da 404 — cae en
// el catch-all y saca al usuario a la Agenda.
import { Facturas as FacturasCompartida } from 'libra-ui/Facturas'

export function Facturas() {
  return (
    <FacturasCompartida
      // Acá el PDF lo sirve la API, no un router aparte.
      urlDelPdf={(id) => `/api/facturas/${id}/pdf`}
      muestraCobros={false}
      rutaDelDetalle={(id) => `/facturas/${id}`}
      // Sin botón de alta todavía: la pantalla de emisión manual no existe. La
      // factura de un turno se emite desde la Agenda.
      mensajeVacio="Todavía no se emitió ningún comprobante. Se facturan desde el turno, en la Agenda."
    />
  )
}
