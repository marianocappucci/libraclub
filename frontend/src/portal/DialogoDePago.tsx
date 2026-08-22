/** El paso del pago: el turno está retenido y hay que pagarlo.
 *
 * 🔴 **Muestra el reloj, y no es decorativo.** El turno se retiene provisorio y
 * se libera solo: sin ver cuánto queda, el jugador completa la tarjeta sin saber
 * que se le está por caer. Y cuando llega a cero, la pantalla lo dice — no se
 * queda mostrando un botón que ya no va a funcionar.
 */
import { useEffect, useState } from 'react'
import { AlertTriangle, CreditCard } from 'lucide-react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

import { portal } from '@/lib/api'
import type { ReservaCreada } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'

/** Segundos que faltan para `vence_at`, o 0. */
function restante(vence: string): number {
  return Math.max(0, Math.round((new Date(vence).getTime() - Date.now()) / 1000))
}

function reloj(segundos: number): string {
  const m = Math.floor(segundos / 60)
  const s = segundos % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function DialogoDePago({
  reserva,
  onCerrar,
}: {
  reserva: ReservaCreada | null
  onCerrar: () => void
}) {
  const [quedan, setQuedan] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [pagando, setPagando] = useState(false)
  const [listo, setListo] = useState(false)
  /** Si esta instancia tiene el simulador (o sea, no es producción). */
  const [sePuedeSimular, setSePuedeSimular] = useState(false)

  useEffect(() => {
    if (!reserva) return
    setError(null)
    setListo(false)
    setQuedan(restante(reserva.vence_at))
    const t = setInterval(() => setQuedan(restante(reserva.vence_at)), 1000)
    return () => clearInterval(t)
  }, [reserva])

  useEffect(() => {
    if (!reserva) return
    // 🔑 Se pregunta al servidor si el simulador existe en vez de mirar una
    // variable de build: el bundle es el mismo en dev y en producción, así que
    // una bandera del frontend mostraría el botón donde no tiene que estar.
    // El 404 de producción es la respuesta.
    portal
      .simularPago(-1)
      .then(() => setSePuedeSimular(true))
      .catch((e: Error) => setSePuedeSimular(/pago/i.test(e.message)))
  }, [reserva])

  if (!reserva) return null

  const vencido = quedan <= 0

  async function simular(aprobado: boolean) {
    setError(null)
    setPagando(true)
    try {
      const r = await portal.simularPago(reserva!.pago_id, aprobado)
      if (r.reserva === 'confirmada') setListo(true)
      else setError('El pago no se aprobó. El turno sigue reservado hasta que venza.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPagando(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {listo ? '¡Listo, turno confirmado!' : 'Falta pagar para confirmar'}
          </DialogTitle>
        </DialogHeader>

        {listo ? (
          <div className="space-y-3 text-sm">
            <p>Tu turno quedó confirmado. Lo vas a ver en «Mis reservas».</p>
            <div className="flex justify-end">
              <Button onClick={onCerrar}>Listo</Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3 text-sm">
            <div className="rounded-md border bg-card p-3">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">A pagar</span>
                <span className="text-lg font-medium">{pesos(String(reserva.monto))}</span>
              </div>
            </div>

            {vencido ? (
              // 🔴 No se deja el botón de pagar: apretarlo daría un error del
              // servidor y el jugador no entendería qué pasó.
              <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                <span>
                  Se venció el tiempo para pagar y el turno volvió a estar
                  disponible. Podés elegirlo de nuevo si sigue libre.
                </span>
              </div>
            ) : (
              <p className="text-muted-foreground">
                Te guardamos el turno <strong>{reloj(quedan)}</strong> más. Si no
                se completa el pago, vuelve a quedar disponible para otro.
              </p>
            )}

            <AvisoDeError mensaje={error} />

            {!vencido && (
              reserva.url_de_pago ? (
                <Button asChild className="w-full">
                  <a href={reserva.url_de_pago}>
                    <CreditCard className="size-4" />
                    Pagar con Mercado Pago
                  </a>
                </Button>
              ) : (
                <div className="space-y-2">
                  {/* Sin credenciales cargadas no hay a dónde mandar al
                      jugador. Se dice, en vez de mostrar un botón muerto. */}
                  <p className="rounded-md border px-3 py-2 text-muted-foreground">
                    Este complejo todavía no tiene los pagos online configurados.
                  </p>
                  {sePuedeSimular && (
                    <div className="space-y-2 rounded-md border border-dashed p-3">
                      <p className="text-xs text-muted-foreground">
                        Instancia de prueba: se puede simular el pago para
                        recorrer el circuito completo.
                      </p>
                      <div className="flex gap-2">
                        <Button
                          disabled={pagando}
                          onClick={() => simular(true)}
                          className="flex-1"
                        >
                          Simular pago aprobado
                        </Button>
                        <Button
                          variant="outline"
                          disabled={pagando}
                          onClick={() => simular(false)}
                        >
                          Rechazado
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )
            )}

            <div className="flex justify-end">
              <Button variant="outline" onClick={onCerrar}>
                {vencido ? 'Cerrar' : 'Después'}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
