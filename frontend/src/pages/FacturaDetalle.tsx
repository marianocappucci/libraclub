// Shim sobre libra-ui/FacturaDetalle, la misma pantalla que Contalibra y
// Restolibra. Acá se monta desde que el producto tiene los doce endpoints del
// motor (2026-08-27): antes no había con qué alimentarla.
//
// El rol no se puede leer desde el paquete: cada producto arma su contexto con
// `createAuthContext`, así que el `useAuth` de libra-ui apunta a otro contexto y
// devolvería siempre vacío. Entra como prop.
//
// 🔴 **`muestraCobros={false}`**, y no es cosmético. Los medios del selector
// salen de `/api/cajas` y `/api/ventas/medios-pago`, que este producto **no
// expone** — su caja es otra cosa, con otra forma—. Sin apagarlo, la pantalla
// diría «Pendiente de cobro» sobre algo que puede estar cobrado, ofrecería un
// botón, y el diálogo abriría con el selector **vacío**. Es la misma decisión
// que ya se tomó para el listado y para la columna de cobrado.
//
// Lo que sí queda: el comprobante, su CAE, el PDF, reintentar la autorización,
// mandarlo por mail, emitir la nota de crédito o de débito, y borrarlo mientras
// no tenga CAE.
import { FacturaDetalle as FacturaDetalleCompartida } from 'libra-ui/FacturaDetalle'

import { useAuth } from '@/context/AuthContext'

export function FacturaDetalle() {
  const { user } = useAuth()
  return (
    <FacturaDetalleCompartida
      esAdmin={user?.role === 'admin'}
      muestraCobros={false}
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
      // Ídem el recibo del cobro, que además necesita `muestraCobros`.
      urlDelRecibo={null}
    />
  )
}
