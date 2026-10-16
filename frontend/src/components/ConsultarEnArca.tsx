/** «Consultar en ARCA»: completa el alta de un cliente con el padrón de ARCA a partir del CUIT.
 *
 *  Es el mismo botón y el mismo mapeo que traen los formularios de cliente del kit (`libra-ui/comercio/Clientes`,
 *  `ClienteDetalle`): razón social, domicilio fiscal y condición frente al IVA. La diferencia, a propósito: el kit
 *  pisa lo que haya; acá **lo que el usuario ya escribió no se pisa sin preguntar**. Los campos vacíos se completan;
 *  si ARCA informa algo distinto de lo que ya hay en un campo, se muestra y se ofrece reemplazarlo.
 *
 *  Si el error es el de «el certificado no tiene acceso al servicio de Padrón» (403) o el de «Configurá los
 *  certificados ARCA» (503), el mensaje lleva un enlace al tutorial de Configuración que explica cómo habilitarlo. */
import { Loader2, Search } from 'lucide-react'
import { useState } from 'react'

import { consultarCuit, URL_TUTORIAL_PADRON, type DatosDeArca } from '@/lib/consultar-cuit'
import { Button } from '@/components/ui/button'

/** A qué campo del formulario va cada dato de ARCA. Los que no estén, no se tocan. */
export type DestinoDeArca = {
  nombre?: { campo: string; etiqueta: string }
  domicilio?: { campo: string; etiqueta: string }
  iva?: { campo: string; etiqueta: string }
}

type Props = {
  /** El CUIT tal como está en el formulario (con o sin guiones). */
  cuit: unknown
  /** Los valores actuales del formulario, por nombre de campo. */
  valores: object
  destino: DestinoDeArca
  /** De «Responsable Inscripto» (ARCA) al valor que guarda este formulario; `undefined` si no tiene equivalente. */
  ivaDe?: (condicionDeArca: string) => string | undefined
  /** Los valores con que arrancó un alta. Un campo que todavía vale lo mismo que el valor inicial no lo eligió nadie
   *  (la condición de IVA arranca en «Consumidor final»): cuenta como vacío. Al editar una fila existente no se pasa. */
  porDefecto?: Record<string, unknown>
  /** Recibe los campos a cambiar, ya con el valor que va en el formulario. */
  alAplicar: (cambios: Record<string, string>) => void
}

const vacio = (v: unknown) => v === null || v === undefined || String(v).trim() === ''
const igual = (a: unknown, b: unknown) =>
  String(a).trim().replace(/\s+/g, ' ').toLowerCase() === String(b).trim().replace(/\s+/g, ' ').toLowerCase()

/** Lo que ARCA informa, en el vocabulario del formulario: `[campo, etiqueta, valor]` de cada dato que viene con contenido. */
function propuestas(datos: DatosDeArca, destino: DestinoDeArca, ivaDe?: Props['ivaDe']) {
  const lista: { campo: string; etiqueta: string; valor: string }[] = []
  if (destino.nombre && datos.nombre) lista.push({ ...destino.nombre, valor: datos.nombre })
  if (destino.domicilio && datos.domicilio) lista.push({ ...destino.domicilio, valor: datos.domicilio })
  if (destino.iva && datos.iva_condition) {
    const valor = ivaDe?.(datos.iva_condition)
    if (valor) lista.push({ ...destino.iva, valor })
  }
  return lista
}

type Mensaje =
  | { tipo: 'ok' | 'error'; texto: string; tutorial?: boolean }
  | null

export function ConsultarEnArca({ cuit, valores, destino, ivaDe, porDefecto, alAplicar }: Props) {
  const [consultando, setConsultando] = useState(false)
  const [mensaje, setMensaje] = useState<Mensaje>(null)
  /** Lo que ARCA informa distinto de lo que ya hay: espera una respuesta del usuario. */
  const [distintos, setDistintos] = useState<{ campo: string; etiqueta: string; valor: string; mostrado: string }[]>([])

  async function consultar() {
    setConsultando(true)
    setMensaje(null)
    setDistintos([])
    const r = await consultarCuit(String(cuit ?? ''))
    setConsultando(false)
    if (!r.ok) {
      setMensaje({ tipo: 'error', texto: r.mensaje, tutorial: r.pideElTutorial })
      return
    }
    const cambios: Record<string, string> = {}
    const aparte: typeof distintos = []
    for (const p of propuestas(r.datos, destino, ivaDe)) {
      const actual = (valores as Record<string, unknown>)[p.campo]
      const sinElegir = vacio(actual) || (porDefecto !== undefined && p.campo in porDefecto && igual(actual, porDefecto[p.campo]))
      if (sinElegir) cambios[p.campo] = p.valor
      else if (!igual(actual, p.valor)) {
        // `mostrado`: el valor tal como lo informó ARCA (la condición de IVA se guarda con otro nombre).
        const crudo = p.campo === destino.iva?.campo ? r.datos.iva_condition ?? p.valor : p.valor
        aparte.push({ ...p, mostrado: crudo })
      }
    }
    if (Object.keys(cambios).length > 0) alAplicar(cambios)
    setDistintos(aparte)
    const estado = r.datos.estado ? ` — Estado: ${r.datos.estado}` : ''
    setMensaje({
      tipo: 'ok',
      texto: Object.keys(cambios).length > 0 || aparte.length > 0
        ? `Datos importados desde ARCA${estado}.`
        : `ARCA no informó datos para completar${estado}.`,
    })
  }

  function reemplazar() {
    alAplicar(Object.fromEntries(distintos.map((d) => [d.campo, d.valor])))
    setDistintos([])
  }

  return (
    <div className="grid gap-2">
      <div>
        <Button type="button" size="sm" variant="outline" disabled={consultando} onClick={() => void consultar()}
                className="max-lg:h-11">
          {consultando ? <Loader2 className="animate-spin" /> : <Search />}
          {consultando ? 'Consultando…' : 'Consultar en ARCA'}
        </Button>
      </div>
      {mensaje?.tipo === 'ok' && <p role="status" className="text-muted-foreground text-xs">{mensaje.texto}</p>}
      {mensaje?.tipo === 'error' && (
        <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">
          {mensaje.texto}
          {mensaje.tutorial && (
            <>
              {' '}
              <a href={URL_TUTORIAL_PADRON} target="_blank" rel="noreferrer"
                 className="text-primary font-medium hover:underline">
                Cómo habilitar el servicio de Padrón en ARCA
              </a>
            </>
          )}
        </p>
      )}
      {distintos.length > 0 && (
        <div role="group" aria-label="Datos de ARCA distintos de los cargados"
             className="grid gap-2 rounded border p-3 text-sm">
          <p>ARCA informa otros datos que los que ya cargaste:</p>
          <ul className="text-muted-foreground list-disc pl-5">
            {distintos.map((d) => <li key={d.campo}>{d.etiqueta}: <strong>{d.mostrado}</strong></li>)}
          </ul>
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" onClick={reemplazar} className="max-lg:h-11">Reemplazar con los de ARCA</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setDistintos([])} className="max-lg:h-11">
              Dejar los míos
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
