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
import { Loader2, QrCode } from 'lucide-react'

import { cobroQr } from '@/lib/api'
import type { QrDisponible } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { buttonVariants } from '@/components/ui/button'

/** Dos notas cortas, sintetizadas. Sin archivo de audio a propósito: no hay
 *  nada que descargar ni que sirva el backend, y suena igual sin internet.
 *
 *  🔴 **El `AudioContext` se crea con el click de «Cobrar con QR» y no al
 *  acreditar.** Los navegadores bloquean el audio que no nace de un gesto del
 *  usuario, y la acreditación llega desde un `setInterval`, que no cuenta como
 *  gesto. Crearlo en el lugar obvio —cuando suena— es exactamente lo que hace
 *  que no suene nunca, y en silencio.
 *
 *  📋 **Copiado de [[contalibra]]** (`frontend/src/pages/VentaDetalle.tsx`), que
 *  es el que el humano probó y da por bueno. Queda **duplicado a propósito**: es
 *  el segundo consumidor, o sea el momento en que corresponde evaluar mudarlo a
 *  `libra-ui` — pero mudarlo obliga a tocar Contalibra, que hoy anda, para no
 *  ganar nada visible. Se anota como candidato, no se hace de arrastre.
 */
function crearAudio(): AudioContext | null {
  try {
    const Ctor = window.AudioContext
      ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    return Ctor ? new Ctor() : null
  } catch {
    return null
  }
}

function sonarCampanita(ctx: AudioContext | null) {
  if (!ctx) return
  // Un contexto creado antes de cualquier gesto puede quedar suspendido.
  if (ctx.state === 'suspended') void ctx.resume()
  const notas = [
    { hz: 1318.5, en: 0 },      // mi6
    { hz: 1760.0, en: 0.13 },   // la6
  ]
  for (const { hz, en } of notas) {
    const osc = ctx.createOscillator()
    const vol = ctx.createGain()
    osc.type = 'sine'
    osc.frequency.value = hz
    const t = ctx.currentTime + en
    vol.gain.setValueAtTime(0.0001, t)
    vol.gain.exponentialRampToValueAtTime(0.28, t + 0.01)
    vol.gain.exponentialRampToValueAtTime(0.0001, t + 0.42)
    osc.connect(vol).connect(ctx.destination)
    osc.start(t)
    osc.stop(t + 0.45)
  }
}

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
  /** Si esta instancia monta el simulador (o sea, no es producción). */
  const [sePuedeSimular, setSePuedeSimular] = useState(false)
  const [simulando, setSimulando] = useState(false)
  const pollRef = useRef<number | null>(null)
  const audioRef = useRef<AudioContext | null>(null)

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
    setSePuedeSimular(false)
    cobroQr.estado()
      .then((estadoMp) => {
        setDisponible(estadoMp)
        // 🔑 **Sólo se sondea si faltan las credenciales.** Con MercadoPago
        // cargado el botón no se ofrece nunca, así que preguntar sería un 404
        // por cada turno que se abre en **toda instancia de producción** —la
        // única que no lo es tiene el simulador—. Ruido en el log, y de la
        // clase que después nadie sabe si importa.
        if (estadoMp.disponible) return
        // Se le pregunta al servidor y no se mira una variable de build: el
        // bundle es el mismo en dev y en producción, así que una bandera del
        // frontend mostraría este botón en la instancia de un complejo, donde
        // acredita cobros que nadie pagó. La ruta vive adentro del router del
        // simulador: **si no se montó, no existe**, y el 404 es la respuesta.
        return cobroQr.simulacionDisponible()
          .then(() => setSePuedeSimular(true))
          // Ante cualquier falla, no se ofrece. Esconder el botón en dev cuesta
          // un click; mostrarlo en producción cuesta un turno cerrado sin
          // cobrar. No se distingue el 404 del 500 a propósito.
          .catch(() => setSePuedeSimular(false))
      })
      // Sin respuesta, la sección no aparece: cobrar por QR es una forma más
      // de cobrar, no un requisito para operar el mostrador.
      .catch(() => setDisponible({ disponible: false, auto_facturar: false }))
  }, [abierto, reservaId, frenarPoll])

  // Sin esto el poll sigue corriendo contra un turno que ya no está en
  // pantalla: cada 3 segundos sale un request.
  useEffect(() => frenarPoll, [frenarPoll])

  if (reservaId === null || !COBRABLES.includes(estado)) return null

  // Todavía preguntando. No se dice nada: un cartel que aparece y desaparece
  // en cada apertura es peor que el medio segundo de nada.
  if (disponible === null) return null

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

  // 🔴 **Acá había un `return null` y ese era el bug.** Sin credenciales el
  // detalle del turno no mostraba **nada**: ni el botón ni el motivo. El humano
  // lo reportó el 2026-08-28 —*"pongo pagar con MercadoPago y no me dirige a
  // ningún lado"*— y tenía razón literal: la pantalla callaba.
  //
  // El mensaje vive acá y no en cada pantalla que use el componente: es este
  // módulo el que sabe si la instancia puede cobrar por QR, y dos copias del
  // texto es cómo una termina diciendo una cosa y la otra otra.
  if (!disponible.disponible) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">
          Para cobrar con el QR del mostrador faltan las credenciales de
          MercadoPago. Se cargan en Configuración → Mercado Pago.
        </p>
        {/* 🔴 **Sólo fuera de producción, y quien lo decide es el servidor.**
            Sin credenciales el circuito no se puede probar de punta a punta:
            `poner_en_el_qr` falla al crear la orden, así que no llega a existir
            el pago que después habría que sellar. Simular sólo la acreditación
            no serviría.

            📋 Misma redacción que el botón del portal
            (`portal/DialogoDePago.tsx`), que es el que el humano ya usó: dos
            textos distintos para lo mismo es cómo uno termina diciendo una cosa
            y el otro otra. */}
        {sePuedeSimular && (
          <div className="space-y-2 rounded-md border border-dashed p-3">
            <p className="text-xs text-muted-foreground">
              Instancia de prueba: se puede simular el pago para recorrer el
              circuito completo.
            </p>
            <AvisoDeError mensaje={error} />
            <button
              type="button"
              disabled={simulando}
              onClick={simular}
              className={buttonVariants({ variant: 'outline' })}
            >
              <QrCode className="size-4" />
              {simulando ? 'Simulando el pago…' : 'Simular pago aprobado'}
            </button>
          </div>
        )}
      </div>
    )
  }

  async function simular() {
    if (reservaId === null) return
    setError(null)
    setSimulando(true)
    try {
      await cobroQr.simular(reservaId)
    } catch (e) {
      // El 409 de "ya está cobrado" o de "no hay caja abierta" llega acá con el
      // mismo texto que le sale al cobro real, que es lo que se quiere probar.
      setError((e as Error).message)
      return
    } finally {
      setSimulando(false)
    }
    // Lo mismo que hace el poll cuando acredita de verdad: el cobro ya ocurrió
    // del lado del servidor, así que la agenda —y con ella la sección de la
    // factura que pudo haber salido sola— tienen que refrescarse.
    setQr('cobrado')
    onCobrado()
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
    // Acá, con el click todavía en curso, es el único momento en que el
    // navegador deja abrir el audio.
    audioRef.current = audioRef.current ?? crearAudio()
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
        sonarCampanita(audioRef.current)
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

  if (qr === 'esperando') {
    return (
      <div className="space-y-2 rounded-md border px-3 py-2 text-sm">
        {/* El spinner no es decoración: es lo que distingue «está esperando» de
            «se colgó». Mismo cartel que Contalibra. */}
        <p className="flex items-center gap-1.5 font-medium text-amber-700 dark:text-amber-400">
          <Loader2 className="size-3.5 animate-spin" /> Esperando el pago…
        </p>
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
        <QrCode className="size-4" />
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
