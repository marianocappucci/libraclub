// Shim sobre libra-ui/Login: el login de la familia, con el branding propio.
//
// Reemplaza al formulario escrito a mano (un `useState` con `border-slate-300`)
// que este archivo tenía hasta el 2026-08-20. Lo que se gana además del dibujo:
// el ojito de `PasswordInput`, el `aria-label` que lo acompaña y el manejo de
// `ApiError` que ya está probado en el kit.
//
// **Sin `forgotPasswordPath` ni `demoPath`, a propósito.** Los dos son opt-in en
// `createLogin` y acá no hay nada del otro lado: `app/routers/auth.py` monta el
// router **sin** `incluir_password_reset` (necesita SMTP configurado) y **sin**
// `incluir_demo` (LibraClub todavía no tiene instancia demo). Un enlace de
// recuperación acá sería un link a un 404, y el botón de demo no aparecería
// igual porque el kit lo condiciona a la sonda en runtime.
import { createLogin } from 'libra-ui/Login'

export const Login = createLogin({
  productName: 'LibraClub',
  productInitial: 'C',
  // A la agenda y no a la raíz: es la pantalla con la que se trabaja todo el
  // día, y `App.tsx` manda cualquier ruta desconocida ahí mismo.
  redirectTo: '/agenda',
})
