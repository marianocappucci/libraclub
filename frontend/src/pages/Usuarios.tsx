/**
 * ABM de usuarios — el de `libra-ui`, apuntado al router de este producto.
 *
 * No se reimplementa nada: es la misma pantalla que ven los otros productos de
 * la familia, y lo único propio es la ruta del backend. LibraClub tiene su API
 * en castellano, así que el `basePath` es `/api/usuarios` y no el `/users` que
 * el componente trae por default.
 *
 * Es también la primera pantalla del producto que sale del kit compartido: si
 * ésta anda, el resto de `libra-ui` está disponible.
 */
import { UserCog } from 'lucide-react'
import { Usuarios as UsuariosCompartido } from 'libra-ui/Usuarios'

export function Usuarios() {
  return (
    <div className="space-y-3">
      {/* El título lo pone la pantalla compartida, que desde libra-ui v0.34.0
          recibe el icono del sidebar de este producto. Antes había uno acá
          también y la pantalla decía «Usuarios» dos veces. */}
      <UsuariosCompartido icono={UserCog} basePath="/api/usuarios" />
      <p className="text-sm text-muted-foreground">
        Los usuarios de esta instancia. El mismo alta la puede hacer el
        backoffice de la suite, que entra por esta misma API con un token de
        servicio en vez de una sesión.
      </p>
    </div>
  )
}
