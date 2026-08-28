// Shim sobre libra-ui/Layout: branding y navegación propios de LibraClub.
//
// Reemplaza al encabezado horizontal escrito a mano que vivía acá hasta el
// 2026-08-20. El kit no tiene barra superior —se eliminó en v0.19.0 para los
// seis productos, porque repetía el nombre del producto y le comía 3,5rem de
// alto a todas las pantallas—, así que las dos cosas que vivían en ese
// encabezado se mudan: la navegación al sidebar, y el selector de sucursal al
// menú del usuario (ver `SelectorDeSucursal.tsx`).
//
// Dos ítems del mismo menú no comparten dibujo — si comparten, el icono deja de
// distinguir y hay que leer el texto igual, que es lo que el icono venía a
// evitar.
import { Outlet } from 'react-router-dom'
import { createLayout } from 'libra-ui/Layout'
import {
  CalendarDays, Clock, CreditCard, CupSoda, LayoutGrid, MapPin, NotebookText, Receipt, Repeat, ScrollText, Settings, Tags, Trophy, UserCog, Users, Wallet,
} from 'lucide-react'

import { useAuth } from '@/context/AuthContext'
import { useSucursal } from '@/context/SucursalContext'
import { SelectorDeSucursal } from '@/components/SelectorDeSucursal'
import { LOGO, WORDMARK } from '@/branding'

type Usuario = { role?: string; name?: string; username?: string; sucursal?: string }

/** La sesión, más el nombre de la sucursal activa.
 *
 *  `createLayout` recibe un `useAuth` y le pide el usuario; agregándole ahí la
 *  sucursal, el encabezado se actualiza solo cuando el selector cambia, sin que
 *  el Layout tenga que saber de dónde salió. Mismo truco que usa LibraCargo
 *  para el nombre de la empresa.
 *
 *  🔴 Es lo que impide que esconder el selector en el menú deje la sucursal
 *  fuera de la vista. Ver la advertencia en `SelectorDeSucursal.tsx`.
 */
function useAuthConSucursal() {
  const sesion = useAuth() as unknown as {
    user: Usuario | null
    logout: () => Promise<void>
  }
  const { sucursales, actual } = useSucursal()
  const elegida = sucursales.find((s) => s.id === actual)
  return {
    ...sesion,
    user: sesion.user ? { ...sesion.user, sucursal: elegida?.nombre } : null,
  }
}

const Cascaron = createLayout<Usuario>({
  productName: 'LibraClub',
  productInitial: 'C',
  // 🔑 El `logo` le gana a `icon`: son dos formas de llenar el mismo hueco y el
  // logo es la más específica. Se deja `icon` igual porque es el piso si algún
  // día se saca el logo, y porque `CalendarDays` es el mismo dibujo que la
  // Agenda — el ítem del menú y el encabezado no se confunden porque el
  // encabezado ahora muestra el logo.
  //
  // El override de colapsado NO es decorativo: con la sidebar en modo icono el
  // ancho útil son 32px, y sin bajarlo el logo se sale de la barra.
  logo: {
    src: LOGO,
    alt: 'LibraClub',
    className: 'h-9 w-9 group-data-[collapsible=icon]:h-8 group-data-[collapsible=icon]:w-8',
  },
  // 🔴 El interlineado va PEGADO al tamaño (`/[21px]`) y no como un
  // `leading-*` aparte: en Tailwind v4 una utilidad de tamaño emite TAMBIÉN
  // su `line-height`, así que el `leading-none` de `libra-ui` pierde contra
  // el `text-[15px]` de acá. El 21 sale de 36 (el logo) menos 15 (la línea
  // del complejo): el bloque de texto mide exactamente lo que mide el logo.
  wordmarkClassName: `${WORDMARK} text-[15px]/[21px]`,
  icon: CalendarDays,
  homeTo: '/agenda',
  navSections: [
    // Sin label: es una sola entrada, y un encabezado arriba de un único ítem
    // es ruido. La agenda es la pantalla del día a día — el resto se toca al
    // configurar y después poco.
    // La agenda y la caja son lo del día a día: el mostrador abre la caja al
    // empezar el turno y trabaja sobre la grilla. Por eso van juntas y arriba.
    {
      items: [
        { to: '/agenda', label: 'Agenda', icon: CalendarDays },
        // Junto a la Agenda: una cancha fija ES agenda, y el encargado la
        // toca cuando el grupo pide o deja el turno — no cuando configura.
        { to: '/turnos-fijos', label: 'Turnos fijos', icon: Repeat },
        // Con la agenda y los turnos fijos: los tres son formas de que una
        // cancha quede ocupada. Un torneo programado bloquea turnos igual que
        // una cancha fija, y el encargado lo toca durante el torneo — no
        // cuando configura el complejo.
        { to: '/torneos', label: 'Torneos', icon: Trophy },
        { to: '/caja', label: 'Caja', icon: Wallet },
        // La cobranza va con la caja y no en Maestros: se mira el mismo día que
        // se cobra, y el pago a cuenta entra por el turno abierto.
        { to: '/cuenta-corriente', label: 'Cuenta corriente', icon: NotebookText },
      ],
    },
    {
      label: 'Maestros',
      items: [
        { to: '/clientes', label: 'Clientes', icon: Users },
        { to: '/canchas', label: 'Canchas', icon: LayoutGrid },
        { to: '/tarifas', label: 'Tarifas', icon: Tags },
        // 🔑 Los mostradores son configuración, como las canchas y las tarifas:
        // se dan de alta al abrir el complejo y no se tocan más. Lo que se toca
        // todos los días es el turno, que está en Caja.
        { to: '/cajas', label: 'Cajas', icon: Wallet },
        // 🔑 **El buffet es mantenimiento, no operación.** Estuvo con la Caja
        // hasta el 2026-08-28 con el argumento de que "es lo que se toca durante
        // el turno", y era falso: el consumo se carga **desde el turno**, en el
        // detalle de la reserva. Lo que esta pantalla hace es el catálogo y el
        // stock — cargar productos y reponer cantidades—, que es exactamente lo
        // que hacen las otras de este grupo.
        //
        // ⚠️ Tiene además una **venta de mostrador** (el consumo sin reserva).
        // Es la minoría del uso y sigue estando acá adentro; si esa venta pasa a
        // ser frecuente, merece su propio acceso y no volver a mudar la pantalla.
        { to: '/buffet', label: 'Buffet', icon: CupSoda },
        // Junto a Tarifas y no en Configuración: las dos definen qué se
        // vende y a cuánto, y se cargan en la misma sesión al abrir el
        // complejo. El horario decide qué turnos existen; la tarifa, su precio.
        { to: '/horarios', label: 'Horario de atención', icon: Clock },
      ],
    },
    {
      label: 'Administración',
      items: [
        // Sucursales **no** lleva `adminOnly`: el listado lo puede ver un
        // encargado (`staff`) y lo que el backend gatea con `require_admin` es
        // el alta, la edición y la baja. La pantalla ya esconde esos botones
        // por su cuenta.
        { to: '/sucursales', label: 'Sucursales', icon: MapPin },
        // Usuarios sí: el router entero exige admin, así que a un encargado el
        // link le daría 403. Un menú que ofrece lo que no se puede usar es peor
        // que no ofrecerlo.
        // Acá y no al lado de Caja: la caja es la plata del turno, que el
        // encargado abre y cierra todos los días; esto es el registro fiscal
        // del complejo, que el dueño o el contador miran una vez por mes.
        //
        // `adminOnly` porque el router entero lleva `require_admin`: a un
        // encargado el link le daría 403, y un menú que ofrece lo que no se
        // puede usar es peor que no ofrecerlo. La factura de SU turno la
        // sigue viendo desde la Agenda, que es de mostrador.
        { to: '/facturas', label: 'Comprobantes', icon: Receipt, adminOnly: true },
        // Debajo de Comprobantes y no al lado de Caja: la bandeja es plata
        // que YA entró a la cuenta de MercadoPago y que hay que conciliar y
        // facturar — el mismo trabajo mensual que el registro fiscal, no el
        // arqueo diario del mostrador.
        //
        // `adminOnly` porque el router lleva `require_admin`: el mostrador
        // cobra, pero conciliar lo que entró a la cuenta es del dueño.
        { to: '/mp-bandeja', label: 'Pagos MercadoPago', icon: CreditCard, adminOnly: true },
        { to: '/usuarios', label: 'Usuarios', icon: UserCog, adminOnly: true },
        // Junto a Usuarios y no en Configuración: se mira para responder
        // "quién hizo esto", que es una pregunta sobre la gente y no sobre
        // los ajustes. Mismo criterio que LibraCargo y LibraDesk.
        { to: '/logs', label: 'Log de actividad', icon: ScrollText, adminOnly: true },
        // Configuración es de admin por los dos lados: el router de empresa
        // lleva `require_admin` y el de SMTP lo exige por dentro.
        { to: '/configuracion', label: 'Configuración', icon: Settings, adminOnly: true },
      ],
    },
  ],
  // `name` es el nombre real de la persona y viene en el contrato de
  // `libraauth`; el `|| username` es el piso para un usuario sembrado sin
  // nombre, que si no dejaría el pie del sidebar en blanco.
  getUserName: (u) => u.name || u.username || '',
  // La sucursal activa, debajo de "LibraClub" en el encabezado del sidebar.
  // Con una sola sucursal el selector no se dibuja, pero esto sí: saber en cuál
  // se está mirando no depende de que haya otra.
  getUserSubtitle: (u) => u.sucursal,
  userMenu: <SelectorDeSucursal />,
  useAuth: useAuthConSucursal,
})

/** El cascarón del kit, adaptado al router de este producto.
 *
 *  `createLayout` devuelve un componente que recibe `children`; LibraClub usa
 *  el patrón de **layout-route** de react-router (una ruta padre sin path, con
 *  las pantallas como rutas hijas), donde el contenido llega por `Outlet` y no
 *  como children. Este envoltorio traduce entre los dos.
 *
 *  No se toca el router para evitarlo: LibraCargo anida un segundo `Routes`
 *  adentro del Layout, pero rehacer un ruteo que ya anda para parecerse a él
 *  sería churn sin ganancia. Lo que importa que sea igual entre productos es el
 *  dibujo del Layout, y eso lo da el cascarón.
 */
export function Layout() {
  return (
    <Cascaron>
      <Outlet />
    </Cascaron>
  )
}

export default Layout
