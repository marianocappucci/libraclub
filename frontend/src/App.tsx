import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { Agenda } from '@/pages/Agenda'
import { Buffet } from '@/pages/Buffet'
import { Caja } from '@/pages/Caja'
import { CuentaCorriente } from '@/pages/CuentaCorriente'
import { CuentaCorrienteDetalle } from '@/pages/CuentaCorrienteDetalle'
import { Horarios } from '@/pages/Horarios'
import { Canchas } from '@/pages/Canchas'
import { Configuracion } from '@/pages/Configuracion'
import { FacturaDetalle } from '@/pages/FacturaDetalle'
import { FacturaNueva } from '@/pages/FacturaNueva'
import { Facturas } from '@/pages/Facturas'
import { Clientes } from '@/pages/Clientes'
import { Login } from '@/pages/Login'
import { ForgotPassword, ResetPassword } from '@/pages/PasswordReset'
import { Logs } from '@/pages/Logs'
import { Sucursales } from '@/pages/Sucursales'
import { Tarifas } from '@/pages/Tarifas'
import { Torneo } from '@/pages/Torneo'
import { Torneos } from '@/pages/Torneos'
import { TurnosFijos } from '@/pages/TurnosFijos'
import { Usuarios } from '@/pages/Usuarios'
import { AuthProvider, useAuth } from '@/context/AuthContext'
import { JugadorProvider } from '@/portal/JugadorContext'
import { MisReservas } from '@/portal/MisReservas'
import { PortalLayout } from '@/portal/PortalLayout'
import { Partidos } from '@/portal/Partidos'
import { PortalReservar } from '@/portal/PortalReservar'
import { SucursalProvider } from '@/context/SucursalContext'

// Exportado para el test de ruteo: lo que hay que poder montar es ESTO —con
// un `MemoryRouter` alrededor y sin sesión— para verificar que
// `/forgot-password` no cae en el login. `App` trae su propio
// `AuthProvider`, que en el test se mockea.
/** El portal público, ANTES de todo lo demás.
 *
 * 🔴 **Fuera del `if (!user)` y también del lado autenticado.** El jugador que
 * entra desde internet no tiene sesión de staff y nunca la va a tener; si estas
 * rutas cayeran adentro de `Ruteo`, `/reservar` mostraría el login del
 * backoffice. Y tampoco pueden ir sólo en la rama sin sesión: el encargado que
 * abre el portal desde la computadora del mostrador —para mostrárselo a
 * alguien— vería el backoffice.
 *
 * Tiene su propio `JugadorProvider`: la sesión del jugador es otra cosa que la
 * del operador, con otra cookie. Ver `portal/JugadorContext.tsx`.
 */
export function Ruteo() {
  return (
    <Routes>
      <Route
        element={
          <JugadorProvider>
            <PortalLayout />
          </JugadorProvider>
        }
      >
        <Route path="/reservar" element={<PortalReservar />} />
        <Route path="/mis-reservas" element={<MisReservas />} />
        <Route path="/partidos" element={<Partidos />} />
      </Route>
      <Route path="/*" element={<Backoffice />} />
    </Routes>
  )
}

function Backoffice() {
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
          <Route path="/turnos-fijos" element={<TurnosFijos />} />
          <Route path="/torneos" element={<Torneos />} />
          {/* El detalle va acá y no anidado: no comparte nada con el listado
              salvo el camino, y anidarlo obligaría a un Outlet para nada. */}
          <Route path="/torneos/:id" element={<Torneo />} />
          <Route path="/horarios" element={<Horarios />} />
          <Route path="/clientes" element={<Clientes />} />
          <Route path="/sucursales" element={<Sucursales />} />
          <Route path="/usuarios" element={<Usuarios />} />
          <Route path="/caja" element={<Caja />} />
          <Route path="/buffet" element={<Buffet />} />
          <Route path="/cuenta-corriente" element={<CuentaCorriente />} />
          {/* Mismo criterio que el detalle de torneo: al lado del listado y no
              anidado, porque no comparte nada con él salvo el camino. */}
          <Route
            path="/cuenta-corriente/:id"
            element={<CuentaCorrienteDetalle />}
          />
          <Route path="/facturas" element={<Facturas />} />
          {/* Al lado del listado y no anidado, mismo criterio que el
              detalle de torneo y el de cuenta corriente: no comparten nada
              salvo el camino. */}
          {/* ANTES que `/facturas/:id`: react-router elige por especificidad
              y no por orden, pero dejarlo escrito arriba evita la duda al
              leerlo — "nueva" no es un id. */}
          <Route path="/facturas/nueva" element={<FacturaNueva />} />
          <Route path="/facturas/:id" element={<FacturaDetalle />} />
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
