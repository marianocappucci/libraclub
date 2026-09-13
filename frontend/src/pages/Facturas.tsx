// Shim sobre libra-ui/Facturas, la misma pantalla que Contalibra y Restolibra.
//
// 🔑 **Este producto NO era una tercera copia**: su listado se escribió aparte y
// difería en 448 líneas. Entra acá por un motivo funcional, no de prolijidad —
// desde que LibraClub emite notas de crédito y débito (2026-08-27), el listado
// sin pestañas las dejaba sin ningún lugar donde verse.
//
// Dos cosas que este producto apaga:
//
// - **`muestraCobros`**, y ya no por lo que decía este comentario hasta el
//   2026-09-13: desde el 2026-08-28 el cruce `caja_movimientos.factura_id` NO
//   lo llena sólo el cobro por QR. El cobro de un turno desde la Agenda pasa
//   `factura_id=reserva.factura_id` en las dos direcciones —si ya estaba
//   facturada al cobrar, y al revés `vincular_cobros_a_factura` ata al facturar
//   los cobros que habían entrado antes—, y desde este cambio el cobro del
//   propio detalle de la factura (`FacturaDetalle.tsx`) también lo llena
//   siempre: ahí `muestraCobros` SÍ está prendido.
//   Lo que sigue faltando para prenderlo acá, en el LISTADO agregado, es sólo
//   lo de ANTES del 2026-08-28: un comprobante cuyo cobro en efectivo se
//   registró cuando el vínculo todavía no existía se vería «Sin cobrar» para
//   siempre, sobre plata que sí entró — nada lo revisa en retrospectiva. En el
//   detalle de UN comprobante el operador puede mirar el número y decidir; en
//   una grilla con filas de esa época mezcladas con las nuevas, un falso «Sin
//   cobrar» no se nota y no hay con qué contrastarlo.
// `rutaDelDetalle` **sí** va desde el 2026-08-27: la pantalla de detalle existe
// y es la compartida del kit. Antes estaba apagada porque `/facturas/:id` no
// existía, y un botón hacia una ruta inexistente en estas SPA no da 404 — cae en
// el catch-all y saca al usuario a la Agenda.
import { Link } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { Facturas as FacturasCompartida } from 'libra-ui/Facturas'

import { Button } from '@/components/ui/button'

export function Facturas() {
  return (
    <FacturasCompartida
      // Acá el PDF lo sirve la API, no un router aparte.
      urlDelPdf={(id) => `/api/facturas/${id}/pdf`}
      muestraCobros={false}
      rutaDelDetalle={(id) => `/facturas/${id}`}
      // Las notas no se emiten desde acá: salen del detalle de la factura que
      // anulan o ajustan, porque sin comprobante asociado no existen.
      acciones={(
        <Button asChild>
          <Link to="/facturas/nueva"><Plus />Nueva factura</Link>
        </Button>
      )}
      mensajeVacio="Todavía no se emitió ningún comprobante. Los de un turno se facturan desde la Agenda."
    />
  )
}
