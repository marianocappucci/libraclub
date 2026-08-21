// Shim sobre libra-ui/Login: el login de la familia, con el branding propio.
//
// Reemplaza al formulario escrito a mano (un `useState` con `border-slate-300`)
// que este archivo tenía hasta el 2026-08-20. Lo que se gana además del dibujo:
// el ojito de `PasswordInput`, el `aria-label` que lo acompaña y el manejo de
// `ApiError` que ya está probado en el kit.
//
// `forgotPasswordPath` es opt-in en `createLogin`, y hasta el 2026-08-21 no
// estaba: el argumento era que hacía falta SMTP configurado y un enlace sería un
// link a un 404. **Las dos mitades del argumento eran falsas** — la ruta existe
// del lado del cliente aunque no haya correo, y sin SMTP el endpoint contesta
// 503 con el motivo. Los otros seis productos de la familia lo tienen así desde
// julio; éste y LibraCargo eran los dos que faltaban.
import { createLogin } from 'libra-ui/Login'

import { LOGO, WORDMARK } from '@/branding'

export const Login = createLogin({
  productName: 'LibraClub',
  // `productInitial` se sigue pasando aunque haya logo: es obligatorio en la
  // config del kit, y es lo que se dibuja si algún día el logo no carga.
  productInitial: 'C',
  // El logo reemplaza al box con la inicial, a 72 px: el tamaño que eligió el
  // humano sobre las tres variantes maquetadas para LibraDesk y que llevan los
  // ocho productos. Sin la clase, `libra-ui` lo dibuja al tamaño del box que
  // reemplaza —40 px—, que es como estuvo esta pantalla hasta el 2026-08-21.
  logo: { src: LOGO, alt: 'LibraClub', className: 'h-[72px] w-[72px]' },
  wordmarkClassName: `${WORDMARK} text-[22px]`,
  // A la agenda y no a la raíz: es la pantalla con la que se trabaja todo el
  // día, y `App.tsx` manda cualquier ruta desconocida ahí mismo.
  redirectTo: '/agenda',
  forgotPasswordPath: '/forgot-password',
  // Botón "Entrar a la demo" — va de la mano con `incluir_demo=True` en
  // `app/routers/auth.py`.
  //
  // 🔴 Declararlo acá NO alcanza para que aparezca, y esa es la mitad que ya
  // se pagó una vez: `libra-ui` consulta `GET /auth/demo` al montar y sólo
  // pinta el botón si la instancia contesta —con JSON— que es una demo. En la
  // instancia de un complejo no aparece nada.
  //
  // Al revés importa igual: sin esta línea, `demo.libraclub.com.ar` mostraría
  // el login normal pidiéndole credenciales a un visitante que no tiene
  // ninguna, con el endpoint contestando perfecto del otro lado. Es lo que les
  // pasó a las seis SPA de la familia el 2026-08-06 — el `POST /auth/demo` en
  // verde, y nadie podía entrar.
  demoPath: '/auth/demo',
})
