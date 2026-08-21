/** El marco del portal: una cabecera y nada más.
 *
 * 🔴 **Sin el sidebar del backoffice, y no es una cuestión estética.** Ese menú
 * lleva a Caja, Usuarios y Logs: mostrárselo a un visitante de internet le
 * diría qué existe del otro lado y le daría links para probar. La API los gatea,
 * pero un portal que dibuja el menú de administración es una invitación.
 */
import { Link, NavLink, Outlet } from 'react-router-dom'

import { LOGO } from '@/branding'
import { useJugador } from '@/portal/JugadorContext'
import { Button } from '@/components/ui/button'

export function PortalLayout() {
  const { jugador, salir } = useJugador()

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 p-3">
          <Link to="/reservar" className="flex items-center gap-2">
            <img src={LOGO} alt="LibraClub" className="size-8 max-w-none object-contain" />
            <span className="font-semibold">Reservar cancha</span>
          </Link>

          <nav className="flex items-center gap-1 text-sm">
            <NavLink
              to="/reservar"
              className={({ isActive }) =>
                `rounded-md px-2 py-1 ${isActive ? 'bg-muted font-medium' : 'hover:bg-muted'}`
              }
            >
              Turnos
            </NavLink>
            {jugador && (
              <NavLink
                to="/mis-reservas"
                className={({ isActive }) =>
                  `rounded-md px-2 py-1 ${isActive ? 'bg-muted font-medium' : 'hover:bg-muted'}`
                }
              >
                Mis reservas
              </NavLink>
            )}
            {jugador ? (
              <Button variant="ghost" size="sm" onClick={salir}>
                Salir
              </Button>
            ) : (
              // Sin sesión no se ofrece "entrar" acá: la cuenta se pide al
              // elegir un turno, que es cuando tiene sentido para el jugador.
              <span className="px-2 text-muted-foreground">Elegí un turno</span>
            )}
          </nav>
        </div>
      </header>

      <main>
        <Outlet />
      </main>
    </div>
  )
}
