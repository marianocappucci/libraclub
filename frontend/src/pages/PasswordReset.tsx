// Shim sobre libra-ui/PasswordReset, mismo patrón que Login.
//
// Las dos pantallas son **públicas**: van fuera del `ProtectedRoute` de
// `App.tsx`, porque quien las usa justamente no puede entrar.
import { createForgotPassword, createResetPassword } from 'libra-ui/PasswordReset'

// El mismo branding que el login. 🔴 `createForgotPassword`/`createResetPassword` (libra-ui v0.123.0) NO aceptan `logo` ni `producto`: dibujan la
// inicial sobre `bg-primary` (que con `aplicarIdentidad` ya es el acento del producto). Se retira el `logo` que se pasaba y el kit ignoraba;
// la marca de estas dos pantallas es una mejora pendiente en libra-ui.
const branding = {
  productName: 'LibraClub',
  productInitial: 'C',
}

// El captcha va en «olvidé mi contraseña» porque el backend lo exige ahí
// (`captcha=True`): sin él, ese endpoint manda correos a pedido de cualquiera.
// El reset con token no lo lleva — el token ya prueba que llegó el correo.
export const ForgotPassword = createForgotPassword({ ...branding, captchaPath: '/auth/captcha' })
export const ResetPassword = createResetPassword(branding)
