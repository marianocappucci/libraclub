import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { Agenda } from '@/pages/Agenda'
import { Buffet } from '@/pages/Buffet'
import { Caja } from '@/pages/Caja'
import { CuentaCorriente } from '@/pages/CuentaCorriente'
import { Horarios } from '@/pages/Horarios'
import { Canchas } from '@/pages/Canchas'
import { Configuracion } from '@/pages/Configuracion'
import { Clientes } from '@/pages/Clientes'
import { Login } from '@/pages/Login'
import { ForgotPassword, ResetPassword } from '@/pages/PasswordReset'
import { Logs } from '@/pages/Logs'
import { Sucursales } from '@/pages/Sucursales'
import { Tarifas } from '@/pages/Tarifas'
import { Usuarios } from '@/pages/Usuarios'
import { AuthProvider, useAuth } from '@/context/AuthContext'
import { SucursalProvider } from '@/context/SucursalContext'

// Exportado para el test de ruteo: lo que hay que poder montar es ESTO —con
// un `MemoryRouter` alrededor y sin sesión— para verificar que
// `/forgot-password` no cae en el login. `App` trae su propio
// `AuthProvider`, que en el test se mockea.
export function Ruteo() {
  const { user, loading } = useAuth()

  // Mientras no se sepa si hay sesión no se decide nada: con un `if (!user)`
  // directo, cada recarga mandaría al login a alguien que ya estaba adentro.
  if (loading) return <p className="p-6 text-muted-foreground">Cargando…</p>

  // 🔴 **Las dos pantallas de recuperación van ANTES del `if (!user)`.** Este
  // producto no rutea el login: sin sesión devuelve `<Login />` para cualquier
  // URL. Con las rutas puestas más abajo, el enlace "¿Olvidaste tu contraseña?"
  // llevaría de nuevo al login —la URL cambiaría y la pantalla no— y el correo
  // con el enlace de reset abriría el login pidiendo la contraseña que la
  // persona justamente no tiene. Quien las usa es exactamente quien no puede
  // entrar, así que no pueden estar del lado autenticado.
  if (!user) {
    return (
      <Routes>
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }

  return (
    <SucursalProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/agenda" element={<Agenda />} />
          <Route path="/canchas" element={<Canchas />} />
          <Route path="/tarifas" element={<Tarifas />} />
          <Route path="/horarios" element={<Horarios />} />
          <Route path="/clientes" element={<Clientes />} />
          <Route path="/sucursales" element={<Sucursales />} />
          <Route path="/usuarios" element={<Usuarios />} />
          <Route path="/caja" element={<Caja />} />
          <Route path="/buffet" element={<Buffet />} />
          <Route path="/cuenta-corriente" element={<CuentaCorriente />} />
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
