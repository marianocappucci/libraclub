import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { GitCompareArrows } from 'lucide-react'

import { edicionesDeClientes, ErrorDeApi } from '@/lib/api'
import type { CampoDeEdicionDeCliente, EdicionDeClienteEnConflicto } from '@/lib/api'
import { avisarCambio, textoDelValor } from '@/lib/clientes-en-conflicto'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'

type Eleccion = 'web' | 'pc'

/**
 * Un cliente con cambios que chocan (ADR-022, tercer addendum): por cada dato en conflicto, los dos valores lado a lado
 * —«Lo que está en la web» y «Lo que se cargó en la PC»— con el valor anterior de referencia, y se elige cuál queda. Los
 * datos que no chocaban se aplican solos al guardar.
 *
 * Si mientras tanto el cliente cambió otra vez en la web, el servidor no pisa nada (409): se muestra el aviso y se
 * recarga la pantalla con lo que hay ahora, para volver a elegir.
 */
export function ResolverConflictoDeCliente() {
  const { operacionId = '' } = useParams()
  const navegar = useNavigate()
  const [edicion, setEdicion] = useState<EdicionDeClienteEnConflicto | null>(null)
  const [elecciones, setElecciones] = useState<Record<string, Eleccion>>({})
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

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

  async function guardar() {
    if (!edicion) return
    setEnviando(true)
    setError(null)
    try {
      await edicionesDeClientes.resolver(edicion.operacion_id, {
        elecciones,
        vistos: Object.fromEntries(edicion.campos.map((c) => [c.campo, c.web])),
      })
      avisarCambio()
      navegar('/clientes/conflictos')
    } catch (e) {
      setError((e as Error).message)
      // El cliente cambió de nuevo en la web, o ya se resolvió: se recarga para no elegir sobre lo viejo.
      if (e instanceof ErrorDeApi && e.status === 409) await cargar()
    } finally {
      setEnviando(false)
    }
  }

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
              Se corrigió en la PC del club y alguien también lo cambió en la web. En cada dato, elegí cuál queda.
            </p>
          </section>

          {enConflicto.length === 0 && (
            <p className="rounded-md border px-3 py-3 text-sm">
              Ya no hay datos que choquen: al guardar se aplica lo que falta.
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
                Estos datos no cambiaron en la web: al guardar se pone lo que se cargó en la PC.
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

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => void guardar()} disabled={enviando || faltan.length > 0}>
              Guardar elección
            </Button>
            {faltan.length > 0 && (
              <span className="text-xs text-muted-foreground">
                Falta elegir en: {faltan.map((c) => c.etiqueta).join(', ')}.
              </span>
            )}
          </div>
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
