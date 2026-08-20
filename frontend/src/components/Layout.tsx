import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { useSucursal } from '@/context/SucursalContext'

const SECCIONES = [
  { a: '/agenda', texto: 'Agenda' },
  { a: '/clientes', texto: 'Clientes' },
  { a: '/canchas', texto: 'Canchas' },
  { a: '/tarifas', texto: 'Tarifas' },
  { a: '/sucursales', texto: 'Sucursales' },
]

export function Layout() {
  const { usuario, salir } = useAuth()
  const { sucursales, actual, elegir } = useSucursal()

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-3">
          <span className="text-lg font-semibold tracking-tight">LibraClub</span>

          {/*
            El selector de sucursal vive en el encabezado y no dentro de cada
            pantalla: es una dimensión de TODO lo que se ve abajo —agenda,
            canchas, tarifas, caja—, y repetirlo por pantalla deja que dos digan
            cosas distintas al mismo tiempo.
          */}
          {sucursales.length > 1 && (
            <label className="flex items-center gap-2 text-sm">
              <span className="text-slate-500">Sucursal</span>
              <select
                className="rounded-md border border-slate-300 bg-white px-2 py-1"
                value={actual ?? ''}
                onChange={(e) => elegir(Number(e.target.value))}
              >
                {sucursales.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.nombre}
                  </option>
                ))}
              </select>
            </label>
          )}

          <nav className="flex gap-1">
            {SECCIONES.map((s) => (
              <NavLink
                key={s.a}
                to={s.a}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm ${
                    isActive
                      ? 'bg-slate-900 text-white'
                      : 'text-slate-600 hover:bg-slate-100'
                  }`
                }
              >
                {s.texto}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3 text-sm text-slate-500">
            <span>{usuario?.username}</span>
            <button
              onClick={salir}
              className="rounded-md border border-slate-300 px-3 py-1.5 hover:bg-slate-100"
            >
              Salir
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
