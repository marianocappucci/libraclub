/** Las reservas del jugador: qué tiene, qué pagó y qué puede cancelar. */
import { useCallback, useEffect, useState } from 'react'
import { CalendarX } from 'lucide-react'

import { portal } from '@/lib/api'
import type { ReservaDelJugador } from '@/lib/api'
import { fecha, hora, pesos } from '@/lib/fechas'
import { useJugador } from '@/portal/JugadorContext'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'

/** Cómo se le cuenta al jugador en qué anda su turno.
 *
 * 🔑 **Se traduce el par (estado, pago), no el estado solo.** Una reserva
 * `provisoria` con pago `pendiente` es «te falta pagar»; la misma provisoria con
 * el pago `vencido` es «se te venció». Mostrar el estado crudo obligaría al
 * jugador a deducir cuál de las dos es.
 */
function comoSeCuenta(r: ReservaDelJugador): { texto: string; tono: string } {
  if (r.estado === 'cancelada') return { texto: 'Cancelada', tono: 'text-muted-foreground' }
  if (r.estado === 'confirmada' || r.estado === 'jugada') {
    return { texto: 'Confirmada', tono: 'text-emerald-600 dark:text-emerald-500' }
  }
  if (r.pago === 'vencido' || r.estado === 'ausente') {
    return { texto: 'Se venció sin pagar', tono: 'text-muted-foreground' }
  }
  return { texto: 'Falta pagar', tono: 'text-amber-700 dark:text-amber-500' }
}

function esFutura(r: ReservaDelJugador): boolean {
  return new Date(r.comienza_at).getTime() > Date.now()
}

export function MisReservas() {
  const { jugador } = useJugador()
  const [filas, setFilas] = useState<ReservaDelJugador[]>([])
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  const recargar = useCallback(() => {
    if (!jugador) {
      setCargando(false)
      return
    }
    setCargando(true)
    portal
      .misReservas()
      .then(setFilas)
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [jugador])

  useEffect(recargar, [recargar])

  async function cancelar(r: ReservaDelJugador) {
    if (!confirm(`¿Cancelar el turno del ${fecha(r.comienza_at)} a las ${hora(r.comienza_at)}?`))
      return
    setError(null)
    try {
      await portal.cancelar(r.id)
      recargar()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (!jugador) {
    return (
      <p className="p-6 text-muted-foreground">
        Entrá a tu cuenta para ver tus reservas.
      </p>
    )
  }
  if (cargando) return <p className="p-6 text-muted-foreground">Cargando…</p>

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-4">
      <h1 className="text-lg font-semibold">Mis reservas</h1>
      <AvisoDeError mensaje={error} />

      {filas.length === 0 ? (
        <p className="rounded-md border bg-card p-4 text-sm text-muted-foreground">
          Todavía no reservaste ningún turno.
        </p>
      ) : (
        <ul className="space-y-2">
          {filas.map((r) => {
            const estado = comoSeCuenta(r)
            return (
              <li
                key={r.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card p-3"
              >
                <div>
                  <div className="font-medium">
                    {fecha(r.comienza_at)} · {hora(r.comienza_at)} a {hora(r.termina_at)}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {r.cancha}
                    {r.precio !== null && ` · ${pesos(String(r.precio))}`}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`text-sm ${estado.tono}`}>{estado.texto}</span>
                  {/* Sólo las futuras se pueden cancelar: la del martes pasado
                      ya se jugó, y ofrecer cancelarla sería ofrecer algo que el
                      servidor rechaza. */}
                  {esFutura(r) && r.estado !== 'cancelada' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Cancelar el turno del ${fecha(r.comienza_at)}`}
                      onClick={() => cancelar(r)}
                    >
                      <CalendarX className="size-4" />
                      Cancelar
                    </Button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
