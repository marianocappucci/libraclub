// Shim sobre libra-ui/PasswordReset, mismo patrón que Login.
//
// Las dos pantallas son **públicas**: van fuera del `ProtectedRoute` de
// `App.tsx`, porque quien las usa justamente no puede entrar.
import { createForgotPassword, createResetPassword } from 'libra-ui/PasswordReset'

import { LOGO } from '@/branding'

// El mismo branding que el login: si el logo apareciera en una pantalla y no en
// la otra, la de recuperación parecería de otro sistema — que es exactamente la
// duda que uno no quiere sembrar en la pantalla donde se pide una contraseña.
const branding = {
  productName: 'LibraClub',
  productInitial: 'C',
  logo: { src: LOGO, alt: 'LibraClub' },
}

export const ForgotPassword = createForgotPassword(branding)
export const ResetPassword = createResetPassword(branding)
