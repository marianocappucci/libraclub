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
import { Usuarios as UsuariosCompartido } from 'libra-ui/Usuarios'

export function Usuarios() {
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">Usuarios</h1>
      <p className="text-sm text-slate-500">
        Los usuarios de esta instancia. El mismo alta la puede hacer el
        backoffice de la suite, que entra por esta misma API con un token de
        servicio en vez de una sesión.
      </p>
      <UsuariosCompartido basePath="/api/usuarios" />
    </div>
  )
}
