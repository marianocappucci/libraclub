// La cola de comprobantes del nodo: las facturas que se pidieron sin conexión y todavía no salieron en ARCA.
//
// Es `BandejaDeLaCola` del kit (libra-ui ADR-094) y LibraClub sólo le pone lo suyo: quién puede resolver y cómo se llama cada pedido.
// LibraClub no tiene `BandejaDeComprobantes` (no recibe comprobantes de otros sistemas), así que la cola va en su propia pantalla y no
// como pestaña (`<BandejaDeComprobantes cola />`).
//
// 🔑 **Sólo tiene sentido en un nodo.** El menú la muestra únicamente ahí (`Layout.tsx`); si alguien escribe `/cola` en otra instancia, el
// panel contesta «esta instalación no es un nodo» por su cuenta, sin romper nada.
//
// Reintentar, descartar y marcar emitido deciden sobre un documento fiscal: `puedeResolver` es sólo de admin, igual que el motor
// (`build_cola_del_nodo_router(resolver_con=require_admin)` en `app/main.py`). El mostrador la mira y puede pedir «Emitir ahora».
import { BandejaDeLaCola } from 'libra-ui/BandejaDeLaCola'
import { ETIQUETA_DE_TIPO, type PedidoDeCola } from 'libra-ui/cola-del-nodo'

import { useAuth } from '@/context/AuthContext'
import { numeroDeReserva } from '@/lib/reservas'

/** El título de cada tarjeta: «Factura · reserva #41». El `origen_id` de LibraClub es el id de la reserva, **en texto**; una reserva
 *  dada en el nodo y todavía sin subir tiene un id negativo, y ése no es un número que el cliente haya oído nunca. */
export function describirPedido(pedido: PedidoDeCola): string {
  const tipo = ETIQUETA_DE_TIPO[pedido.origen_tipo] ?? pedido.origen_tipo
  return `${tipo} · reserva ${numeroDeReserva(pedido.origen_id)}`
}

export function Cola() {
  const { user } = useAuth()
  return <BandejaDeLaCola puedeResolver={user?.role === 'admin'} describir={describirPedido} />
}
