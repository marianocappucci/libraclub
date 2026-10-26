import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { GitCompareArrows } from 'lucide-react'

import { edicionesDeClientes, ErrorDeApi } from '@/lib/api'
import type { CampoDeEdicionDeCliente, EdicionDeClienteEnConflicto } from '@/lib/api'
import { avisarCambio, textoDelValor } from '@/lib/clientes-en-conflicto'
import { AvisoDeError } from '@/components/listado'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { Button } from '@/components/ui/button'

type Eleccion = 'web' | 'pc'

/**
 * Un cliente con cambios cargados en la PC del club que esperan a alguien (ADR-022, tercer y cuarto addendum):
 *
 * - si **chocan**, por cada dato en conflicto se ven los dos valores lado a lado —«Lo que está en la web» y «Lo que se
 *   cargó en la PC»— con el valor anterior de referencia, y se elige cuál queda. Los datos que no chocaban se aplican
 *   solos al guardar;
 * - si **ya no chocan** (la web volvió al valor anterior), no hay nada que elegir: se ve lo que se va a aplicar y lo que ya
 *   está igual, y se puede «Aplicar cambios de la PC» o «Descartar» (con confirmación: no tiene vuelta atrás).
 *
 * Si mientras tanto el cliente cambió otra vez en la web, el servidor no pisa nada (409): se muestra el aviso y se
 * recarga la pantalla con lo que hay ahora —si volvió a chocar, la elección por campo—, para decidir de nuevo.
 */
export function ResolverConflictoDeCliente() {
  const { operacionId = '' } = useParams()
  const navegar = useNavigate()
  const [edicion, setEdicion] = useState<EdicionDeClienteEnConflicto | null>(null)
  const [elecciones, setElecciones] = useState<Record<string, Eleccion>>({})
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [descartando, setDescartando] = useState(false)

  const cargar = useCallback(() => {
    return edicionesDeClientes
      .ver(operacionId)
      .then((e) => {
        setEdicion(e)
        setElecciones({})
      })
      .catch((e: Error) => {
        // Ya la resolvió otra persona, o no existe: no hay nada que mostrar acá.
        if (e instanceof ErrorDeApi && (e.status === 404 || e.status === 409)) {
          avisarCambio()
          navegar('/clientes/conflictos', { replace: true })
          return
        }
        setError(e.message)
      })
  }, [operacionId, navegar])

  useEffect(() => {
    void cargar()
  }, [cargar])

  const enConflicto = edicion?.campos.filter((c) => c.estado === 'conflicto') ?? []
  const seAplican = edicion?.campos.filter((c) => c.estado === 'se_aplica') ?? []
  const yaIguales = edicion?.campos.filter((c) => c.estado === 'igual') ?? []
  const faltan = enConflicto.filter((c) => !elecciones[c.campo])

  const yaNoChoca = edicion !== null && enConflicto.length === 0

  /** Manda la decisión con lo que la pantalla vio de la web. Un 409 (cambió de nuevo, o ya la resolvió otra persona)
   *  recarga para no decidir sobre lo viejo. */
  async function enviar(accion: (e: EdicionDeClienteEnConflicto, vistos: Record<string, string | boolean | null>) => Promise<unknown>) {
    if (!edicion) return
    setEnviando(true)
    setError(null)
    try {
      await accion(edicion, Object.fromEntries(edicion.campos.map((c) => [c.campo, c.web])))
      avisarCambio()
      navegar('/clientes/conflictos')
    } catch (e) {
      setError((e as Error).message)
      if (e instanceof ErrorDeApi && e.status === 409) await cargar()
    } finally {
      setEnviando(false)
    }
  }

  const guardar = () => enviar((e, vistos) => edicionesDeClientes.resolver(e.operacion_id, { elecciones, vistos }))
  const descartar = () => enviar((e, vistos) => edicionesDeClientes.descartar(e.operacion_id, { vistos }))

  return (
    <div className="space-y-4">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={GitCompareArrows}>Clientes por revisar</TituloPantalla>} />
      <p className="text-sm">
        <Link to="/clientes/conflictos" className="text-muted-foreground underline">
          Volver a la lista
        </Link>
      </p>
      <AvisoDeError mensaje={error} />
      {edicion && (
        <>
          <section className="space-y-1">
            <h2 className="text-lg font-semibold">{edicion.cliente_nombre}</h2>
            <p className="text-sm text-muted-foreground">
              {yaNoChoca
                ? 'Se corrigió en la PC del club y todavía no se aplicó el cambio.'
                : 'Se corrigió en la PC del club y alguien también lo cambió en la web. En cada dato, elegí cuál queda.'}
            </p>
          </section>

          {yaNoChoca && (
            <p className="rounded-md border border-exito bg-exito/10 px-3 py-3 text-sm text-exito">
              <strong>Ya no choca.</strong> El dato de la web volvió a como estaba: no hay nada que elegir. Podés aplicar los
              cambios de la PC o descartarlos.
            </p>
          )}

          {enConflicto.map((c) => (
            <fieldset key={c.campo} className="space-y-2 rounded-md border p-3">
              <legend className="px-1 text-sm font-semibold">{c.etiqueta}</legend>
              <p className="text-xs text-muted-foreground">Antes: {textoDelValor(c, c.antes)}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                <OpcionDeValor campo={c} lado="web" titulo="Lo que está en la web" elegida={elecciones[c.campo]}
                  onElegir={() => setElecciones((p) => ({ ...p, [c.campo]: 'web' }))} />
                <OpcionDeValor campo={c} lado="pc" titulo="Lo que se cargó en la PC" elegida={elecciones[c.campo]}
                  onElegir={() => setElecciones((p) => ({ ...p, [c.campo]: 'pc' }))} />
              </div>
            </fieldset>
          ))}

          {seAplican.length > 0 && (
            <section className="space-y-1 rounded-md border bg-muted/40 p-3">
              <h3 className="text-sm font-semibold">Se aplican</h3>
              <p className="text-xs text-muted-foreground">
                Estos datos no cambiaron en la web: al {yaNoChoca ? 'aplicar' : 'guardar'} se pone lo que se cargó en la PC.
              </p>
              <ul className="text-sm">
                {seAplican.map((c) => (
                  <li key={c.campo}>
                    <strong>{c.etiqueta}:</strong> {textoDelValor(c, c.web)} → {textoDelValor(c, c.pc)}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {yaIguales.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Ya están así en la web: {yaIguales.map((c) => c.etiqueta).join(', ')}.
            </p>
          )}

          {yaNoChoca && seAplican.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No hay nada para cambiar: al aplicar, el cambio de la PC se da por resuelto.
            </p>
          )}

          <div className="flex flex-wrap items-center gap-3">
            {yaNoChoca ? (
              <>
                <Button onClick={() => void guardar()} disabled={enviando}>
                  Aplicar cambios de la PC
                </Button>
                <Button variant="outline" onClick={() => setDescartando(true)} disabled={enviando}>
                  Descartar
                </Button>
              </>
            ) : (
              <>
                <Button onClick={() => void guardar()} disabled={enviando || faltan.length > 0}>
                  Guardar elección
                </Button>
                {faltan.length > 0 && (
                  <span className="text-xs text-muted-foreground">
                    Falta elegir en: {faltan.map((c) => c.etiqueta).join(', ')}.
                  </span>
                )}
              </>
            )}
          </div>

          <ConfirmDialog
            open={descartando}
            onOpenChange={setDescartando}
            title="Descartar los cambios de la PC"
            description={`Los cambios que se cargaron en la PC del club para ${edicion.cliente_nombre} no se van a aplicar y el cliente queda como está en la web. No se puede deshacer.`}
            confirmLabel="Descartar"
            onConfirm={() => void descartar()}
          />
        </>
      )}
    </div>
  )
}

function OpcionDeValor({ campo, lado, titulo, elegida, onElegir }: {
  campo: CampoDeEdicionDeCliente
  lado: Eleccion
  titulo: string
  elegida: Eleccion | undefined
  onElegir: () => void
}) {
  const activa = elegida === lado
  return (
    <label
      className={`flex cursor-pointer items-start gap-2 rounded-md border p-3 text-sm ${
        activa ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'hover:bg-muted/40'
      }`}
    >
      <input type="radio" name={`eleccion-${campo.campo}`} checked={activa} onChange={onElegir} className="mt-1" />
      <span className="space-y-0.5">
        <span className="block text-xs text-muted-foreground">{titulo}</span>
        <span className="block break-words font-medium">{textoDelValor(campo, campo[lado])}</span>
      </span>
    </label>
  )
}
