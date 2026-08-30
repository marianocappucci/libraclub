/** Configuración de LibraClub.
 *
 *  El armado y las secciones comunes vienen de `libra-ui/Configuracion`, que
 *  desde la v0.47.0 es **la pantalla de Configuración de la familia entera** —
 *  la de Contalibra, con su barra de pestañas, la sub-navegación de
 *  Integraciones, el botón de *Backup rápido* y los tutoriales. Acá se declara
 *  sólo lo que corresponde a este producto.
 *
 *  🔴 **La copia única vive en el kit, no acá.** Hasta hoy este producto tenía
 *  su propia sección de MercadoPago —`ConfigMercadoPago.tsx`, que se va— con
 *  cuatro campos, mientras Contalibra tenía otra con siete. El comentario que
 *  estaba en este archivo decía que subirla al kit *"va a corresponder el día
 *  que sea la tercera copia y no la segunda"*: ese día llegó, y la decisión la
 *  tomó el humano el 2026-08-29.
 *
 *  ## Las tres integraciones
 *
 *  - **MercadoPago** lo sirve ahora `libracore.mp_config_router`. El token
 *    vuelve **enmascarado** —el endpoint propio lo devolvía en claro— y hay un
 *    botón que le pregunta a MercadoPago si sirve.
 *
 *    ⚠️ **`rutaWebhook` no es la de la familia.** El webhook de este producto
 *    vive en `/api/portal/webhook`, no en `/webhooks/mercadopago`: mostrar la
 *    URL equivocada haría que el complejo registre en MercadoPago una ruta que
 *    no existe, y **ninguna reserva pagada desde el portal se confirmaría**.
 *
 *  - **ARCA** dejó de pedir un *path del filesystem del servidor* y pasó a
 *    subir el certificado y la clave, validados antes de escribirse, con el
 *    vencimiento a la vista.
 *  - **Correo (SMTP)** suma el tutorial de la contraseña de aplicación de
 *    Gmail, que este producto no tenía.
 *
 *  ## El texto del interruptor de facturación automática
 *
 *  Acá lo que se cobra con el QR es un **turno** —cancha y buffet—, no una
 *  venta. El texto por defecto del kit habla de ventas porque salió de
 *  Contalibra; dejarlo así diría "ventas" en un complejo de pádel.
 */
import { Settings } from 'lucide-react'
import { createConfiguracion } from 'libra-ui/Configuracion'

export const Configuracion = createConfiguracion({
  // El icono que el sidebar de este producto le da a /configuracion.
  icono: Settings,
  // Sale en el tutorial de Gmail —es el nombre que hay que ponerle a la
  // contraseña de aplicación— y en el de Padrón A13.
  producto: 'LibraClub',
  integraciones: {
    mercadopago: {
      // Ver el docstring: el webhook de este producto NO está en la ruta de la
      // familia. La firma secreta que se carga acá es la que ese webhook
      // verifica, y sin ella no procesa nada — procesar sin verificar sería
      // dejar que cualquiera confirme turnos.
      rutaWebhook: '/api/portal/webhook',
      autoFacturar: {
        label: 'Facturar automáticamente los turnos cobrados por QR',
        ayuda: 'Al acreditarse el cobro se emite la factura con CAE y queda '
          + 'vinculada al turno. Sólo para los turnos cobrados con este QR: los '
          + 'demás se siguen facturando cuando alguien lo pide.',
      },
    },
    // 🔴 `empresa` es el slug de la fila de `arca_config`, el mismo que usa
    // `servicios/facturacion.py`. En una instancia sin fila, sin esto el primer
    // guardado la crearía como `default` — donde ese servicio no mira nunca.
    arca: { empresa: 'complejo' },
    email: true,
  },
})
