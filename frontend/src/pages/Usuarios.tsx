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
import { useAuth } from '@/context/AuthContext'

export function Usuarios() {
  const { user } = useAuth()

  return (
    <div className="space-y-3">
      {/* El título lo pone la pantalla compartida, que desde libra-ui v0.34.0
          recibe el icono del sidebar de este producto. Antes había uno acá
          también y la pantalla decía «Usuarios» dos veces. */}
      {/* `roles` queda en su default (`staff`/`admin`): es exactamente la
          tupla `("admin", "staff")` del `UserRepository` de este producto. */}
      <UsuariosCompartido
        icono={UserCog}
        basePath="/api/usuarios"
        // El backend adoptó `libraauth.usuarios.build_users_router()`
        // (ADR-018, v0.43.0), que trae el `DELETE` con las guardas del único
        // admin -- recién con eso tiene sentido ofrecer el botón acá.
        permitirEliminar
        // Oculta el botón «Eliminar» en la fila propia: el backend igual lo
        // rechaza (409), pero mejor no ofrecerlo.
        usuarioActualId={user?.id}
      />
      <p className="text-sm text-muted-foreground">
        Los usuarios de esta instancia. El mismo alta la puede hacer el
        backoffice de la suite, que entra por esta misma API con un token de
        servicio en vez de una sesión, o el panel del cliente con su
        credencial propia.
      </p>
    </div>
  )
}
