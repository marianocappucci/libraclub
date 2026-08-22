// La pantalla vive en `libra-ui`, igual que `Usuarios`: nació en LibraDesk y se
// extrajo porque es la misma en todos los productos — el backend le manda hasta
// la lista de entidades y los colores de cada acción.
//
// 🔴 Con `basePath`, porque el router NO va en el `/logs` que el kit trae por
// default: esa ruta es la de esta misma pantalla, y FastAPI resuelve sus rutas
// antes que el catch-all de la SPA — entrar a `/logs` devolvía el JSON crudo
// del endpoint. El backend lo monta en `/api/logs`, igual que `/api/usuarios`.
//
// ⚠️ Esta pantalla es la razón por la que hubo que vendorizar
// `components/ui/tabs`: desde `libra-ui` v0.29.0 separa Actividad y Accesos en
// dos pestañas, y el kit resuelve `@/components/ui/*` contra el CONSUMIDOR. Sin
// ese archivo el build no resuelve el import — no es un error de runtime, no
// llega a compilar.
import { ScrollText } from 'lucide-react'
import { Logs as LogsCompartido } from 'libra-ui/Logs'

export function Logs() {
  return <LogsCompartido icono={ScrollText} basePath="/api/logs" />
}
