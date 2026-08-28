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
    />
  )
}
