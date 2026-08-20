import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { Agenda } from '@/pages/Agenda'
import { Canchas } from '@/pages/Canchas'
import { Login } from '@/pages/Login'
import { Tarifas } from '@/pages/Tarifas'
import { AuthProvider, useAuth } from '@/context/AuthContext'
import { SucursalProvider } from '@/context/SucursalContext'

function Ruteo() {
  const { usuario, cargando } = useAuth()

  // Mientras no se sepa si hay sesión no se decide nada: con un `if (!usuario)`
  // directo, cada recarga mandaría al login a alguien que ya estaba adentro.
  if (cargando) return <p className="p-6 text-slate-500">Cargando…</p>
  if (!usuario) return <Login />

  return (
    <SucursalProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/agenda" element={<Agenda />} />
          <Route path="/canchas" element={<Canchas />} />
          <Route path="/tarifas" element={<Tarifas />} />
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
