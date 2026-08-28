/** El cobro con QR de MercadoPago del mostrador.
 *
 * 🔑 **No hay ninguna imagen de QR que dibujar.** El QR es el cartel impreso de
 * la caja y no cambia nunca; lo que cambia es **cuánto cobra**. Esta pantalla
 * pone el monto, avisa que el cliente lo escanee, y poléa hasta que se acredita.
 *
 * ⚠️ **El monto lo decide el backend, y es el pendiente** —no el total del
 * turno—: `cobro_qr.total_a_cobrar` resta lo ya cobrado desde el 2026-08-28,
 * porque antes un turno con seña en efectivo se cobraba entero otra vez.
 *
 * 🔴 **Vive en su propio archivo desde el 2026-08-28**, y no adentro de
 * `DetalleDeReserva`. El humano reportó que eligiendo MercadoPago en la Caja
 * *"no me dirige para que la persona escanee el QR"*: el flujo existía, pero
 * sólo se llegaba desde el detalle del turno — que con la Caja convertida en el
 * punto de venta es justamente el camino que dejó de usarse.
 *
 * Sus tests siguen entrando por `DetalleDeReserva` (`CobroConQr.test.tsx`), y al
 * no tocarse son el control de que la extracción no cambió nada.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { cobroQr } from '@/lib/api'
import type { QrDisponible } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { buttonVariants } from '@/components/ui/button'

const POLL_MS = 3000

/** Cinco minutos: si el cliente no escaneó, el monto se baja del cartel. */
const ESPERA_MAXIMA_MS = 5 * 60 * 1000

/** Los estados en los que tiene sentido cobrar. Espeja `ESTADOS_COBRABLES` del
 *  backend: cobrar una reserva cancelada no es un caso de uso, es un error. */
const COBRABLES = ['confirmada', 'jugada']

type EstadoQr = 'idle' | 'poniendo' | 'esperando' | 'cobrado'

export function SeccionDeCobroConQr({ reservaId, estado, abierto, onCobrado }: {
  reservaId: number | null
  estado: string
  abierto: boolean
  onCobrado: () => void
}) {
  const [disponible, setDisponible] = useState<QrDisponible | null>(null)
  const [qr, setQr] = useState<EstadoQr>('idle')
  const [monto, setMonto] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<number | null>(null)

  const frenarPoll = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  // 🔴 **Depende de `reservaId`, no sólo de `abierto`.** En el diálogo del turno
  // daba lo mismo —un diálogo, una reserva—, pero en la Caja se cambia de cancha
  // sin cerrar nada: sin esto, el estado del QR anterior queda en pantalla y el
  // poll sigue preguntando por la reserva que ya no se está mirando. Se ve como
  // «Cobrado por QR» sobre una cancha que no cobró nada.
  useEffect(() => {
    if (!abierto) return
    frenarPoll()
    setQr('idle')
    setError(null)
    setMonto(null)
    cobroQr.estado()
      .then(setDisponible)
      // Sin respuesta, la sección no aparece: cobrar por QR es una forma más
      // de cobrar, no un requisito para operar el mostrador.
      .catch(() => setDisponible({ disponible: false, auto_facturar: false }))
  }, [abierto, reservaId, frenarPoll])

  // Sin esto el poll sigue corriendo contra un turno que ya no está en
  // pantalla: cada 3 segundos sale un request.
  useEffect(() => frenarPoll, [frenarPoll])

  if (reservaId === null || !disponible?.disponible || !COBRABLES.includes(estado)) {
    return null
  }

  async function bajar() {
    if (reservaId === null) return
    try {
      await cobroQr.bajar(reservaId)
    } catch {
      // Si falla, la orden queda en la caja y el encargado puede volver a
      // ponerla. Hacer fallar una cancelación por esto sería peor.
    }
  }

  async function cobrar() {
    if (reservaId === null) return
    setError(null)
    setQr('poniendo')
    try {
      setMonto((await cobroQr.poner(reservaId)).monto)
    } catch (e) {
      setError((e as Error).message)
      setQr('idle')
      return
    }
    setQr('esperando')
    const hasta = Date.now() + ESPERA_MAXIMA_MS
    pollRef.current = window.setInterval(async () => {
      let resultado
      try {
        resultado = await cobroQr.consultar(reservaId)
      } catch (e) {
        frenarPoll()
        setQr('idle')
        setError((e as Error).message)
        return
      }
      if (resultado.estado === 'aprobado') {
        frenarPoll()
        setQr('cobrado')
        // Refresca la agenda y, con ella, la sección de la factura que pudo
        // haber salido sola.
        onCobrado()
        return
      }
      if (resultado.estado === 'rechazado') {
        frenarPoll()
        setQr('idle')
        setError('El pago fue rechazado o cancelado en MercadoPago.')
        return
      }
      if (Date.now() > hasta) {
        frenarPoll()
        void bajar()
        setQr('idle')
        setError(
          'Se agotó la espera y se bajó el monto del QR. Si el cliente pagó '
          + 'igual, fijate en MercadoPago antes de volver a cobrar.',
        )
      }
    }, POLL_MS)
  }

  if (qr === 'cobrado') {
    return (
      <div className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm dark:bg-emerald-950/30">
        <div className="font-medium text-emerald-800 dark:text-emerald-400">
          Cobrado por QR de MercadoPago
        </div>
        {disponible.auto_facturar && (
          <div className="text-muted-foreground">La factura se emitió sola.</div>
        )}
      </div>
    )
  }

  if (qr === 'esperando') {
    return (
      <div className="space-y-2 rounded-md border px-3 py-2 text-sm">
        <p>
          El QR de la caja ya está cobrando{' '}
          <strong>{monto === null ? '' : pesos(monto)}</strong>. Pedile al
          cliente que lo escanee.
        </p>
        <button
          type="button"
          onClick={() => { frenarPoll(); void bajar(); setQr('idle') }}
          className="text-sm text-red-800 underline underline-offset-2"
        >
          Cancelar el cobro por QR
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <AvisoDeError mensaje={error} />
      <button
        type="button"
        disabled={qr === 'poniendo'}
        onClick={cobrar}
        className={buttonVariants({ variant: 'outline' })}
      >
        {qr === 'poniendo' ? 'Preparando el QR…' : 'Cobrar con QR'}
      </button>
      {/* ⚠️ **Decía «el total del turno» y era mentira desde el 2026-08-28.**
          Ese día `cobro_qr.total_a_cobrar` pasó a restar lo ya cobrado —un turno
          con seña se cobraba entero otra vez—, y este texto quedó atrás. Un
          cartel que dice cuánto va a cobrar y cobra otra cosa es peor que no
          decir nada. */}
      <p className="text-xs text-muted-foreground">
        Pone en el QR impreso del mostrador lo que falta cobrar del turno
        —cancha y buffet—
        {disponible.auto_facturar ? ', y factura solo al acreditarse' : ''}.
      </p>
    </div>
  )
}
