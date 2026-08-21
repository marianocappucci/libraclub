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
 *  🔑 **Sin `SECCION_ARCA`, y no es un olvido.** LibraClub todavía no factura:
 *  `pyproject.toml` trae `libracore` sólo por `respaldo`, y el propio comentario
 *  ahí dice que su alcance crece en F3 con ARCA. La pestaña existe en el kit y
 *  se suma **el día que haya endpoints del otro lado** — ponerla antes daría una
 *  pantalla que guarda un certificado que nadie usa.
 */
import { SECCIONES_BASE, createConfiguracion } from 'libra-ui/Configuracion'

export const Configuracion = createConfiguracion({
  // Empresa (+ logo), Correo (SMTP) y Datos / Backup.
  secciones: SECCIONES_BASE,
})
