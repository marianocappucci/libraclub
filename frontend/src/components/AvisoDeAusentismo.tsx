import type { Reincidente } from '@/lib/api'
import { fecha } from '@/lib/fechas'

/**
 * «Faltó sin avisar 3 veces en los últimos 90 días». Sólo si es reincidente.
 *
 * `role="status"` y no `alert`: no es un error ni frena nada —el turno se toma
 * igual— y un `alert` competiría con el `AvisoDeError` del mismo diálogo, que sí
 * lo es.
 */
export function AvisoDeAusentismo({
  nombre,
  ausencia,
  dias,
}: {
  nombre?: string
  ausencia: Reincidente | undefined
  dias: number
}) {
  if (!ausencia) return null
  const quien = nombre ? `${nombre} faltó` : 'Faltó'
  return (
    <p
      role="status"
      className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
    >
      {/* Un solo nodo de texto: partida en varios, la frase no se puede leer
          entera ni con un lector de pantalla ni con un test. */}
      {`${quien} sin avisar ${ausencia.ausentes} veces en los últimos ${dias} días `
        + `(la última, el ${fecha(ausencia.ultimo_ausente_at)}). Se le puede reservar igual.`}
    </p>
  )
}
