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
  CalendarDays, LayoutGrid, MapPin, Settings, Tags, UserCog, Users,
} from 'lucide-react'

import { useAuth } from '@/context/AuthContext'
import { useSucursal } from '@/context/SucursalContext'
import { SelectorDeSucursal } from '@/components/SelectorDeSucursal'
import { LOGO } from '@/branding'

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
    className: 'h-8 w-8 group-data-[collapsible=icon]:h-7 group-data-[collapsible=icon]:w-7',
  },
  icon: CalendarDays,
  homeTo: '/agenda',
  navSections: [
    // Sin label: es una sola entrada, y un encabezado arriba de un único ítem
    // es ruido. La agenda es la pantalla del día a día — el resto se toca al
    // configurar y después poco.
    { items: [{ to: '/agenda', label: 'Agenda', icon: CalendarDays }] },
    {
      label: 'Maestros',
      items: [
        { to: '/clientes', label: 'Clientes', icon: Users },
        { to: '/canchas', label: 'Canchas', icon: LayoutGrid },
        { to: '/tarifas', label: 'Tarifas', icon: Tags },
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
        { to: '/usuarios', label: 'Usuarios', icon: UserCog, adminOnly: true },
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
