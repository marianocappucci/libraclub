// Shim sobre libra-ui/AuthContext (mismo patrón que el resto de la familia).
//
// La instancia pre-configurada del kit apunta a `/auth/me`, `/auth/login` y
// `/auth/logout`, que son **exactamente** las tres rutas que monta
// `build_json_api_auth_router()` en `app/routers/auth.py`. Por eso alcanza con
// re-exportar: no hace falta `createAuthContext` con rutas propias, como sí lo
// necesitan Contalibra y Restolibra.
//
// 🔴 Los nombres pasan a ser los del kit —`user`, `loading`, `login`,
// `logout`— y no los de antes en español (`usuario`, `cargando`, `entrar`,
// `salir`). Se migran los call sites en vez de envolver el hook para
// traducirlos: una capa de traducción haría que este producto se lea distinto
// de sus cinco hermanos justo en el archivo donde uno va a buscar la sesión, y
// esa divergencia no compra nada.
//
// El `User` que devuelve el kit es el contrato completo de `_UserOut` de
// libraauth (`id`, `username`, `name`, `role`, `active`) — más de lo que
// declaraba el contexto propio, que sólo tipaba `username` y `role`.
export { AuthProvider, useAuth } from 'libra-ui/AuthContext'
