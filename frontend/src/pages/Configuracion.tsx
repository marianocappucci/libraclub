/** Configuración de LibraClub.
 *
 *  Hasta hoy este producto **no tenía ninguna pantalla de configuración**: los
 *  datos del complejo no se podían cargar, el logo no se podía subir, el SMTP
 *  sólo entraba por el backoffice de la suite y el backup era exclusivamente
 *  por CLI — aunque su router estaba montado desde el primer día.
 *
 *  El armado y las secciones vienen de `libra-ui/Configuracion`; acá se declara
 *  **lo que corresponde a este producto**.
 *
 *  🔑 **`SECCION_ARCA` entró el 2026-08-21**, cuando aparecieron los endpoints
 *  del otro lado (`GET`/`PUT /config/arca`). Antes estaba deliberadamente
 *  afuera: una pestaña que guarda un certificado que nadie usa es peor que no
 *  tenerla.
 *
 *  ⚠️ Lo que la pestaña de ARCA hace es **guardar la configuración**: qué CUIT
 *  emite, con qué punto de venta y con qué certificado. En una instancia sin
 *  `LIBRACLUB_LIBRACORE_DATABASE_URL` contesta 503 diciendo exactamente qué
 *  falta, en vez de un error genérico.
 *
 *  🔑 **Mercado Pago entró el 2026-08-23**, con el cobro con QR del mostrador.
 *  Es una sección propia y no de `libra-ui`: VentaLibra tiene la equivalente en
 *  su propio archivo y Contalibra adentro de su `Config.tsx`. Subirla al motor
 *  es lo que va a corresponder el día que sea la tercera copia y no la segunda.
 */
import { Settings } from 'lucide-react'
import { QrCode } from 'lucide-react'
import {
  SECCIONES_BASE, SECCION_ARCA, createConfiguracion,
} from 'libra-ui/Configuracion'

import { ConfigMercadoPago } from './ConfigMercadoPago'

export const Configuracion = createConfiguracion({
  // El icono que el sidebar de este producto le da a /configuracion.
  icono: Settings,
  // Empresa (+ logo), Correo (SMTP), Datos / Backup, ARCA y Mercado Pago.
  secciones: [
    ...SECCIONES_BASE,
    SECCION_ARCA,
    {
      clave: 'mercadopago',
      label: 'Mercado Pago',
      icono: QrCode,
      contenido: <ConfigMercadoPago />,
    },
  ],
})
