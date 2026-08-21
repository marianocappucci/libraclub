// La identidad visual de LibraClub: el logo y cómo se escribe el nombre.
//
// Vive en un archivo propio porque lo usan las DOS superficies que lo muestran
// —el login y la sidebar— y son shims distintos sobre `libra-ui`. Con la
// definición repetida en cada uno, alcanza con tocar una para que las dos
// pantallas dejen de coincidir, que es el tipo de divergencia que nadie reporta
// porque nunca se ven juntas. Mismo patrón que LibraDesk.
import logoLibraClub from '@/assets/logo-libraclub.png'

export const LOGO = logoLibraClub

/**
 * El verde de LibraClub.
 *
 * 🔑 **No se inventó acá**: es el `--brand` de la landing del producto
 * (`libraclub_web`), que a su vez lo genera `libra-web-kit` desde
 * `site_css_tokens.py`. Ese es el lugar donde vive la identidad de cada sitio
 * de la familia, así que la aplicación usa exactamente el mismo verde que la
 * web pública en vez de uno parecido.
 *
 * Es un color literal y no un token del tema **a propósito**: es el color de la
 * marca, no el del texto de la interfaz. Si LibraClub alguna vez prende modo
 * oscuro, esto hay que decidirlo — que es preferible a que el nombre del
 * producto cambie de color solo cuando alguien toque la paleta.
 */
export const MARCA = '#017b4b'

/**
 * Cómo se escribe «LibraClub» al lado del logo: Montserrat Bold `#2d2d2d`.
 *
 * Es el estándar de la familia y no una elección de este producto — los ocho
 * lo escriben igual, y el color no es el de la marca (`MARCA`) sino el gris
 * del wordmark. Va acá por el mismo motivo que el logo: el login y la sidebar
 * **nunca se ven juntos**, así que dos copias que diverjan no las reporta
 * nadie.
 *
 * 🔴 El tamaño NO va acá: lo pone cada superficie (72/22 px en el login,
 * 36/15 px en la sidebar), y el interlineado va pegado al tamaño.
 */
export const WORDMARK = 'font-montserrat font-bold text-[#2d2d2d]'
