// Shim sobre libra-ui/FacturaDetalle, la misma pantalla que Contalibra y
// Restolibra. Acá se monta desde que el producto tiene los doce endpoints del
// motor (2026-08-27): antes no había con qué alimentarla.
//
// El rol no se puede leer desde el paquete: cada producto arma su contexto con
// `createAuthContext`, así que el `useAuth` de libra-ui apunta a otro contexto y
// devolvería siempre vacío. Entra como prop.
//
// 🔑 **`muestraCobros` prendido desde que el backend tiene su propio hook de
// cobro** (`_cobrar_del_turno` en `app/routers/facturas.py`): la plata entra
// por la caja del **turno abierto**, y `POST /api/facturas/{id}/cobrar` queda
// atado a la factura igual que cualquier otro cobro de este producto. Antes
// estaba apagado porque el hook no existía —el default del motor escribía el
// movimiento sin `turno_id`, fuera de todo arqueo— y porque el selector no
// tenía de dónde sacar los medios: `/api/cajas` exige `sucursal_id` y
// `/api/ventas/medios-pago` no existe en este producto, así que los dos
// pedidos que hace el paquete fallan y el selector abriría vacío. Se
// completa con `mediosDeCobro`, más abajo.
//
// Lo que sí queda igual: el comprobante, su CAE, el PDF, reintentar la
// autorización, mandarlo por mail, emitir la nota de crédito o de débito, y
// borrarlo mientras no tenga CAE.
import { FacturaDetalle as FacturaDetalleCompartida } from 'libra-ui/FacturaDetalle'

import { useAuth } from '@/context/AuthContext'
import { useMediosDePago } from '@/lib/medios-pago'

export function FacturaDetalle() {
  const { user } = useAuth()
  const { medios } = useMediosDePago()
  return (
    <FacturaDetalleCompartida
      esAdmin={user?.role === 'admin'}
      // Los medios de ESTE producto —`GET /api/caja/medios-pago`—, en la forma
      // que pide el paquete. Sin esto el selector de cobro abriría vacío: ver
      // el comentario de arriba.
      mediosDeCobro={medios.map((m) => ({ id: m.valor, label: m.etiqueta }))}
      // 🔴 **Acá el PDF lo sirve la API, no un router aparte.** El default del
      // kit es `/facturas/{id}/pdf`, que es donde lo tienen Contalibra y
      // Restolibra con su router Jinja2 viejo. Este producto no lo tiene, así
      // que esa ruta **no daba 404**: caía en el catch-all de la SPA y devolvía
      // el `index.html` con 200. Apretar «Ver PDF» abría una pestaña con la
      // aplicación adentro. Lo reportó el humano el 2026-08-28.
      urlDelPdf={(id) => `/api/facturas/${id}/pdf`}
      // Este producto **no imprime ticket**: el botón llevaba al mismo callejón.
      // `null` lo saca en vez de dejarlo apuntando a ninguna parte.
      urlDelTicket={null}
      // Este producto tampoco emite recibo de cobro: no hay ruta que servir.
      urlDelRecibo={null}
    />
  )
}
