"""ABM de usuarios, sobre el router único de `libraauth` (ADR-018, v0.43.0).

Antes este módulo tenía su propia copia del router. Ahora es un
`build_users_router()` con el prefijo, la tupla de roles y el guard que este
producto ya usaba -- ver el docstring de la factory en `libraauth.usuarios`
para el detalle de cada protección.

Existe para que el **backoffice de la suite** (`admin.libraclub.com.ar`) pueda
administrar los usuarios de esta instancia. Sin este router, la pestaña
"Usuarios" del panel contesta 404 contra este producto.

> El repositorio es el de `libraauth`: la tabla `usuarios` la crea y la versiona
> el motor, no este producto. Acá sólo se expone.
"""

from libraauth.usuarios import build_users_router

from app.auth import require_admin_o_servicio_o_panel

router = build_users_router(
    # El prefijo NO cambia: el resto de la API de este producto va en
    # castellano, y `libra-ui`, el backoffice y los bookmarks del cliente ya lo
    # conocen.
    prefix="/api/usuarios",
    roles=("admin", "staff"),
    # Rol admin, token de servicio **o** credencial del panel del cliente --
    # el guard `_que_recuerde_al_usuario(...)` de `app/auth.py`, tal cual ya
    # gateaba este router. Pasarlo desde `app.auth` (y no el
    # `json_api_require_admin_o_servicio_o_panel` sin envolver de `libraauth`)
    # es lo que mantiene la auditoría: ese envoltorio es el único lugar que
    # deja el id del usuario en `request.state` para que
    # `app/auditoria.py::_completar_auditoria` complete `created_by`/
    # `updated_by` en cualquier escritura de la misma request.
    #
    # 🔑 **El único router de este producto que acepta la credencial del
    # panel.** El resto de lo que gatea `require_admin_o_servicio` ---y son
    # siete lugares--- sigue cerrado para el panel: el guard se aplica router
    # por router justamente para no abrirlos todos de una.
    admin_guard=require_admin_o_servicio_o_panel,
)
