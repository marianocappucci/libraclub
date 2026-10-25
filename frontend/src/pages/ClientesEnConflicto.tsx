import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { GitCompareArrows } from 'lucide-react'

import { edicionesDeClientes } from '@/lib/api'
import type { EdicionDeClienteEnConflicto } from '@/lib/api'
import { fechaHora } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'

/**
 * Los clientes que se corrigieron en la PC del club sin conexión y que alguien también cambió en la web (ADR-022, tercer
 * addendum). La PC no pisa lo de la web ni al revés: cada uno se revisa en su pantalla, donde se ven los dos valores y se
 * elige cuál queda.
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
        Estos clientes se corrigieron en la PC del club cuando no tenía conexión, pero alguien también cambió el mismo dato
        en la web. No se pisó nada: en cada uno vas a ver los dos cambios y elegís cuál queda.
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
            <div className="space-y-0.5">
              <p className="font-medium">{e.cliente_nombre}</p>
              <p className="text-xs text-muted-foreground">
                {e.en_conflicto === 1 ? '1 dato para elegir' : `${e.en_conflicto} datos para elegir`}
                {': '}
                {e.campos.filter((c) => c.estado === 'conflicto').map((c) => c.etiqueta).join(', ')}
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
