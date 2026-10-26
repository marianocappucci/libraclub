import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { GitCompareArrows } from 'lucide-react'

import { edicionesDeClientes } from '@/lib/api'
import type { EdicionDeClienteEnConflicto } from '@/lib/api'
import { fechaHora } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'

/**
 * Los clientes que se corrigieron en la PC del club sin conexión y esperan a alguien (ADR-022, tercer y cuarto addendum):
 *
 * - los que **chocan**: alguien también cambió en la web el mismo dato. La PC no pisa lo de la web ni al revés: cada uno se
 *   revisa en su pantalla, donde se ven los dos valores y se elige cuál queda;
 * - los que **ya no chocan**: el dato de la web volvió a como estaba y no hay nada que elegir. Se marcan aparte y en su
 *   pantalla se aplican o se descartan.
 */
export function ClientesEnConflicto() {
  const [lista, setLista] = useState<EdicionDeClienteEnConflicto[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const cargar = useCallback(() => {
    edicionesDeClientes
      .listar()
      .then((l) => setLista(Array.isArray(l) ? l : []))
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(cargar, [cargar])

  return (
    <div className="space-y-3">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={GitCompareArrows}>Clientes por revisar</TituloPantalla>} />
      <p className="text-sm text-muted-foreground">
        Estos clientes se corrigieron en la PC del club cuando no tenía conexión y todavía no se aplicó el cambio. Si
        alguien también cambió el mismo dato en la web, no se pisó nada: vas a ver los dos cambios y elegís cuál queda. Si
        el dato de la web volvió a como estaba, ya no choca: lo aplicás o lo descartás.
      </p>
      <AvisoDeError mensaje={error} />
      {lista !== null && lista.length === 0 && (
        <p className="rounded-md border px-3 py-6 text-center text-sm text-muted-foreground">
          No hay cambios de clientes para revisar.
        </p>
      )}
      <ul className="space-y-2">
        {(lista ?? []).map((e) => (
          <li
            key={e.operacion_id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-3"
          >
            <div className="space-y-1">
              <p className="flex flex-wrap items-center gap-2 font-medium">
                {e.cliente_nombre}
                {e.ya_no_choca ? (
                  <BadgeEstado tono="ok">Ya no choca: se puede aplicar</BadgeEstado>
                ) : (
                  <BadgeEstado tono="atencion">Hay que elegir</BadgeEstado>
                )}
              </p>
              <p className="text-xs text-muted-foreground">
                {resumen(e)}
                {e.recibida_at ? ` · llegó el ${fechaHora(e.recibida_at)}` : ''}
              </p>
            </div>
            <Button asChild size="sm" variant="outline">
              <Link to={`/clientes/conflictos/${encodeURIComponent(e.operacion_id)}`}>Revisar</Link>
            </Button>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Qué hay en la edición: los datos para elegir, o lo que se aplica si ya no choca. */
function resumen(e: EdicionDeClienteEnConflicto): string {
  if (!e.ya_no_choca) {
    const datos = e.campos.filter((c) => c.estado === 'conflicto').map((c) => c.etiqueta).join(', ')
    return `${e.en_conflicto === 1 ? '1 dato para elegir' : `${e.en_conflicto} datos para elegir`}: ${datos}`
  }
  const seAplican = e.campos.filter((c) => c.estado === 'se_aplica')
  if (seAplican.length === 0) return 'Ya está todo igual en la web'
  const datos = seAplican.map((c) => c.etiqueta).join(', ')
  return `${seAplican.length === 1 ? '1 dato para aplicar' : `${seAplican.length} datos para aplicar`}: ${datos}`
}
