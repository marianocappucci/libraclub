import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { Agenda } from '@/pages/Agenda'
import { Caja } from '@/pages/Caja'
import { Canchas } from '@/pages/Canchas'
import { Configuracion } from '@/pages/Configuracion'
import { Clientes } from '@/pages/Clientes'
import { Login } from '@/pages/Login'
import { Logs } from '@/pages/Logs'
import { Sucursales } from '@/pages/Sucursales'
import { Tarifas } from '@/pages/Tarifas'
import { Usuarios } from '@/pages/Usuarios'
import { AuthProvider, useAuth } from '@/context/AuthContext'
import { SucursalProvider } from '@/context/SucursalContext'

function Ruteo() {
  const { user, loading } = useAuth()

  // Mientras no se sepa si hay sesión no se decide nada: con un `if (!user)`
  // directo, cada recarga mandaría al login a alguien que ya estaba adentro.
  if (loading) return <p className="p-6 text-muted-foreground">Cargando…</p>
  if (!user) return <Login />

  return (
    <SucursalProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/agenda" element={<Agenda />} />
          <Route path="/canchas" element={<Canchas />} />
          <Route path="/tarifas" element={<Tarifas />} />
          <Route path="/clientes" element={<Clientes />} />
          <Route path="/sucursales" element={<Sucursales />} />
          <Route path="/usuarios" element={<Usuarios />} />
          <Route path="/caja" element={<Caja />} />
          <Route path="/configuracion" element={<Configuracion />} />
          <Route path="/logs" element={<Logs />} />
          {/* Las rutas no llevan guarda de rol: el permiso lo decide el
              servidor, y una ruta escondida que igual carga datos no protege
              nada. Lo que las pantallas hacen es no ofrecer botones que van a
              dar 403. */}
          <Route path="*" element={<Navigate to="/agenda" replace />} />
        </Route>
      </Routes>
    </SucursalProvider>
  )
}

export function App() {
  return (
    <AuthProvider>
      <Ruteo />
    </AuthProvider>
  )
}
