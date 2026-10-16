/** La consulta de un CUIT en el padrón de ARCA: `GET /api/consultar-cuit/:cuit` (el router del motor,
 *  `libracore.consultar_cuit_router`).
 *
 *  Devuelve `{nombre, domicilio, iva_condition, estado}`, o `{error}` con un estado que dice qué pasó:
 *  400 (CUIT mal), 404 (no está en el padrón), 403 (el certificado no tiene delegado el servicio de Padrón A13),
 *  503 (la instancia no cargó los certificados de ARCA) y 502/500 (ARCA o el servidor fallaron).
 *
 *  `fetch` a mano y no el cliente de `libra-ui`: el cuerpo de error es `{error}` y no el `{detail}` de FastAPI,
 *  igual que en los formularios de cliente del kit. */

export type DatosDeArca = {
  nombre?: string
  domicilio?: string
  /** El texto de ARCA: «Responsable Inscripto», «Monotributista», «IVA Exento», «Consumidor Final»… */
  iva_condition?: string
  estado?: string
}

export type ResultadoDeConsulta =
  | { ok: true; datos: DatosDeArca }
  | {
      ok: false
      mensaje: string
      /** El estado HTTP, o `null` si ni siquiera se pudo hablar con el servidor. */
      estado: number | null
      /** El error se arregla habilitando el servicio de Padrón en ARCA (403) o cargando los certificados (503). */
      pideElTutorial: boolean
    }

/** Dónde está «¿Qué servicio debo habilitar para consultar datos de clientes por CUIT?»: la pestaña General de
 *  ARCA en Configuración → Integraciones. El ancla la usa el kit para abrir el tutorial. */
export const URL_TUTORIAL_PADRON = '/configuracion?seccion=integraciones&integracion=arca#tutorial-padron-a13'

export const soloDigitos = (valor: unknown): string => String(valor ?? '').replace(/\D/g, '')

export async function consultarCuit(cuit: string): Promise<ResultadoDeConsulta> {
  const digitos = soloDigitos(cuit)
  if (digitos.length !== 11) {
    return { ok: false, mensaje: 'Ingresá un CUIT de 11 dígitos antes de consultar.', estado: null, pideElTutorial: false }
  }
  try {
    const resp = await fetch(`/api/consultar-cuit/${digitos}`, { credentials: 'include' })
    const cuerpo = await resp.json().catch(() => ({})) as DatosDeArca & { error?: string; detail?: unknown }
    if (!resp.ok || cuerpo.error) {
      // `error` es el cuerpo del router del motor; un `detail` es de otra capa (la sesión, el módulo apagado) y no
      // tiene nada que ver con el padrón: ahí el tutorial no ayuda.
      const delMotor = typeof cuerpo.error === 'string'
      return {
        ok: false, estado: resp.status,
        mensaje: (delMotor ? cuerpo.error : typeof cuerpo.detail === 'string' ? cuerpo.detail : '') || 'Error al consultar ARCA.',
        pideElTutorial: delMotor && (resp.status === 403 || resp.status === 503),
      }
    }
    return { ok: true, datos: cuerpo }
  } catch {
    return { ok: false, mensaje: 'No se pudo conectar con ARCA.', estado: null, pideElTutorial: false }
  }
}
