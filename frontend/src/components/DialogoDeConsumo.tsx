/** El buffet que se vende: el mismo carrito, en un panel o en un diálogo.
 *
 * 🔑 **Uno solo, y la diferencia es `reservaId`.** Con reserva el consumo se
 * carga a la cancha y **no se cobra** —se cobra al facturar el turno—; sin
 * reserva es una venta de mostrador y pide medio de pago. Duplicar la pantalla
 * habría duplicado también el carrito y el redondeo.
 *
 * 🔴 **Y desde el 2026-09-08 la venta suelta NO va en diálogo.** El humano lo
 * reportó así: *"en Caja, Venta Suelta hay que hacer clic en vender del buffet y
 * la pantalla queda sin nada… debería aparecer todo eso en vez del modal"*.
 * Tenía razón: esa pestaña **es** el punto de venta del buffet, así que pedir un
 * click para tapar la pestaña vacía con una ventana encima es un paso que no
 * decide nada. El diálogo queda para el otro caso, donde sí hay algo abajo que
 * no se puede tapar: la cuenta de la cancha desde la que se carga el consumo.
 *
 * Por eso hay dos exportaciones y un solo cuerpo:
 *
 * | | Quién lo usa | Qué muestra |
 * |---|---|---|
 * | `PanelDeConsumo` | la pestaña «Venta suelta» de la Caja | el carrito, inline |
 * | `DialogoDeConsumo` | la cuenta de una cancha («Cargar buffet») | el mismo carrito, en una ventana |
 *
 * 🔴 **Con «MercadoPago» elegido, la venta de mostrador se cobra por el QR de la
 * caja, no anotando un movimiento a mano.** Hasta el 2026-09-08 «MercadoPago»
 * era acá un medio de pago como cualquier otro: se apretaba «Cobrar», entraba a
 * la caja y nadie escaneaba nada — el mismo agujero que el detalle del turno
 * tenía hasta el 2026-08-28, reportado por el humano con las mismas palabras
 * (*"elijo pagar mercadopago y me tiene que aparecer la opción de QR"*).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, Minus, Plus, QrCode, Trash2 } from 'lucide-react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { buffet, cobroQr, cobroQrBuffet } from '@/lib/api'
import { useMediosDePago } from '@/lib/medios-pago'
import type { ProductoDeBuffet, QrDisponible, VentaConQr } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { buttonVariants } from '@/components/ui/button'
import {
  ESPERA_MAXIMA_MS, POLL_MS, crearAudio, sonarCampanita,
} from '@/components/CobroConQr'

/** El medio que dispara el QR. Es la clave del backend (`cobro_qr.MEDIO`), la
 *  misma que mira la Caja para el cobro del turno. */
const MEDIO_QR = 'mercadopago'

type EstadoQr = 'idle' | 'poniendo' | 'esperando'

export function PanelDeConsumo({
  sucursalId,
  reservaId = null,
  activo = true,
  onCargado,
  onCerrar,
}: {
  sucursalId: number
  /** `null` = venta de mostrador: se cobra en el acto. */
  reservaId?: number | null
  /** Si la vista está a la vista. En el panel inline es siempre `true`; el
   *  diálogo pasa su `abierto` para no pedir productos con la ventana cerrada. */
  activo?: boolean
  onCargado: () => void
  /** Sólo el diálogo lo pasa. Sin él no se dibuja «Cancelar»: en un panel
   *  inline no hay nada que cerrar, y un botón que no hace nada es peor que
   *  ninguno. */
  onCerrar?: () => void
}) {
  const [productos, setProductos] = useState<ProductoDeBuffet[]>([])
  const [carrito, setCarrito] = useState<Record<number, number>>({})
  const { medios } = useMediosDePago()
  const [medio, setMedio] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  // 🔴 El medio por defecto **espera a que la lista llegue**. Antes se
  // inicializaba con `MEDIOS_DE_PAGO[0]`, una constante que estaba siempre; con
  // la lista pedida al backend eso es imposible hasta que conteste, y dejarlo en
  // `''` haría que el consumo viaje **sin medio de pago** — entra a la caja como
  // un movimiento sin medio y el cierre no lo reparte.
  useEffect(() => {
    if (!medio && medios.length > 0) setMedio(medios[0].valor)
  }, [medio, medios])

  const cargarProductos = useCallback(() => {
    return buffet
      .productos(sucursalId)
      .then((p) => setProductos(p.filter((x) => x.activo)))
      .catch((e: Error) => setError(e.message))
  }, [sucursalId])

  useEffect(() => {
    if (!activo) return
    setError(null)
    setCarrito({})
    void cargarProductos()
  }, [activo, cargarProductos])

  const total = useMemo(
    () =>
      Object.entries(carrito).reduce((suma, [id, cant]) => {
        const p = productos.find((x) => x.item_id === Number(id))
        return suma + (p ? p.precio * cant : 0)
      }, 0),
    [carrito, productos],
  )

  function sumar(itemId: number, delta: number) {
    setCarrito((c) => {
      const cant = (c[itemId] ?? 0) + delta
      const { [itemId]: _, ...resto } = c
      return cant > 0 ? { ...resto, [itemId]: cant } : resto
    })
  }

  const lineas = Object.entries(carrito)
  const esMostrador = reservaId === null

  // ── El cobro por QR de la venta de mostrador ──────────────────────────
  const [qrDeLaInstancia, setQrDeLaInstancia] = useState<QrDisponible | null>(null)
  const [sePuedeSimular, setSePuedeSimular] = useState(false)
  const [simulando, setSimulando] = useState(false)
  const [qr, setQr] = useState<EstadoQr>('idle')
  const [enElQr, setEnElQr] = useState<VentaConQr | null>(null)
  const pollRef = useRef<number | null>(null)
  const audioRef = useRef<AudioContext | null>(null)
  /** La venta que quedó puesta en el cartel, para poder bajarla al desmontar.
   *  Un ref y no el estado: el cleanup del efecto ve el ref, no la clausura. */
  const pendienteRef = useRef<number | null>(null)

  const frenarPoll = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const porQr = esMostrador && medio === MEDIO_QR

  // Si este complejo puede cobrar por QR. Se pregunta al montar y no al elegir
  // el medio: así el botón no titila entre «Cobrar» y «Cobrar con QR» justo
  // cuando el cajero acaba de elegir.
  useEffect(() => {
    if (!activo || !esMostrador) return
    setQr('idle')
    setEnElQr(null)
    setSePuedeSimular(false)
    cobroQr.estado()
      .then((estado) => {
        setQrDeLaInstancia(estado)
        // 🔑 **Sólo se sondea el simulador si faltan las credenciales.** Con
        // MercadoPago cargado el botón de simular no se ofrece nunca, así que
        // preguntar sería un 404 por cada venta en toda instancia de producción.
        // Mismo criterio que `SeccionDeCobroConQr`.
        if (estado.disponible) return
        return cobroQrBuffet.simulacionDisponible()
          .then(() => setSePuedeSimular(true))
          .catch(() => setSePuedeSimular(false))
      })
      // Sin respuesta, no se ofrece: cobrar por QR es una forma más de cobrar,
      // no un requisito para vender una gaseosa.
      .catch(() => setQrDeLaInstancia({ disponible: false, auto_facturar: false }))
  }, [activo, esMostrador])

  const bajarDelQr = useCallback(async (ventaId: number) => {
    pendienteRef.current = null
    try {
      await cobroQrBuffet.bajar(ventaId)
    } catch {
      // Si falla, la orden queda en la caja y el encargado puede volver a
      // ponerla. Hacer fallar un cierre por esto sería peor.
    }
  }, [])

  /** 🔴 Al desmontar se frena el poll **y se baja el monto del cartel.**
   *
   * Inline esto pasó a importar mucho más que en el diálogo: cambiar de pestaña
   * —a «Canchas», a «Otro»— desmonta el panel sin que nadie apriete nada. Sin
   * esto, el cartel se queda cobrando esa venta y el próximo que escanee paga
   * las gaseosas de otro.
   */
  useEffect(() => () => {
    frenarPoll()
    const pendiente = pendienteRef.current
    if (pendiente !== null) void cobroQrBuffet.bajar(pendiente).catch(() => {})
  }, [frenarPoll])

  /** Lo que hace el panel cuando una venta se cerró: refrescar y volver a cero.
   *
   * El stock se recarga porque **acá se ve**: quedaba mostrando 24 gaseosas
   * después de vender dos. En el diálogo no se notaba —se cierra— y por eso el
   * panel inline es el que lo necesita. */
  const alTerminarUnaVenta = useCallback(() => {
    setCarrito({})
    setEnElQr(null)
    setQr('idle')
    pendienteRef.current = null
    void cargarProductos()
    onCargado()
  }, [cargarProductos, onCargado])

  const cerrar = useCallback(() => {
    frenarPoll()
    if (qr === 'esperando' && enElQr !== null) void bajarDelQr(enElQr.venta_id)
    setQr('idle')
    setEnElQr(null)
    onCerrar?.()
  }, [bajarDelQr, enElQr, frenarPoll, onCerrar, qr])

  function lineasParaCobrar() {
    return lineas.map(([id, cant]) => ({ item_id: Number(id), cantidad: String(cant) }))
  }

  async function cargar() {
    setError(null)
    setEnviando(true)
    try {
      await buffet.consumir(sucursalId, {
        lineas: lineasParaCobrar(),
        reserva_id: reservaId,
        medio_pago: esMostrador ? medio : null,
      })
      alTerminarUnaVenta()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  async function cobrarConQr() {
    // Acá, con el click todavía en curso, es el único momento en que el
    // navegador deja abrir el audio: la acreditación llega desde un
    // `setInterval`, que no cuenta como gesto del usuario.
    audioRef.current = audioRef.current ?? crearAudio()
    setError(null)
    setQr('poniendo')
    let puesta: VentaConQr
    try {
      puesta = await cobroQrBuffet.poner(sucursalId, { lineas: lineasParaCobrar() })
    } catch (e) {
      setError((e as Error).message)
      setQr('idle')
      return
    }
    setEnElQr(puesta)
    pendienteRef.current = puesta.venta_id
    setQr('esperando')
    const hasta = Date.now() + ESPERA_MAXIMA_MS
    pollRef.current = window.setInterval(async () => {
      let resultado
      try {
        resultado = await cobroQrBuffet.consultar(puesta.venta_id)
      } catch (e) {
        frenarPoll()
        setQr('idle')
        setError((e as Error).message)
        return
      }
      if (resultado.estado === 'aprobado') {
        frenarPoll()
        sonarCampanita(audioRef.current)
        // La venta ya está confirmada y la plata anotada del lado del servidor.
        alTerminarUnaVenta()
        return
      }
      if (resultado.estado === 'rechazado') {
        frenarPoll()
        setQr('idle')
        setEnElQr(null)
        pendienteRef.current = null
        setError('El pago fue rechazado o cancelado en MercadoPago.')
        return
      }
      if (Date.now() > hasta) {
        frenarPoll()
        void bajarDelQr(puesta.venta_id)
        setQr('idle')
        setEnElQr(null)
        setError(
          'Se agotó la espera y se bajó el monto del QR. Si el cliente pagó '
          + 'igual, fijate en MercadoPago antes de volver a cobrar.',
        )
      }
    }, POLL_MS)
  }

  async function simular() {
    setError(null)
    setSimulando(true)
    try {
      await cobroQrBuffet.simular(sucursalId, { lineas: lineasParaCobrar() })
    } catch (e) {
      // El 409 de "no hay caja abierta" llega acá con el mismo texto que le sale
      // al cobro real, que es lo que se quiere probar.
      setError((e as Error).message)
      return
    } finally {
      setSimulando(false)
    }
    alTerminarUnaVenta()
  }

  const etiquetaDelBoton = () => {
    if (enviando) return 'Cargando…'
    if (!esMostrador) return 'Cargar'
    if (!porQr) return 'Cobrar'
    return qr === 'poniendo' ? 'Preparando el QR…' : 'Cobrar con QR'
  }

  return (
    <div className="space-y-3">
      <AvisoDeError mensaje={error} />

      {productos.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No hay productos cargados en el buffet.
        </p>
      ) : (
        <div className="grid max-h-64 grid-cols-2 gap-2 overflow-y-auto">
          {productos.map((p) => (
            <button
              key={p.item_id}
              type="button"
              onClick={() => sumar(p.item_id, 1)}
              className="rounded-md border p-2 text-left text-sm hover:bg-muted"
            >
              <div className="font-medium">{p.nombre}</div>
              <div className="flex items-center justify-between text-muted-foreground">
                <span>{pesos(String(p.precio))}</span>
                {/* 🔑 El stock se muestra al vender, no sólo en la pantalla de
                    stock: el encargado tiene que ver que quedan dos antes de
                    prometer cuatro. */}
                <span className={p.stock <= 0 ? 'text-amber-700 dark:text-amber-500' : ''}>
                  {p.stock} en stock
                </span>
              </div>
            </button>
          ))}
        </div>
      )}

      {lineas.length > 0 && (
        <div className="space-y-1 rounded-md border p-2 text-sm">
          {lineas.map(([id, cant]) => {
            const p = productos.find((x) => x.item_id === Number(id))!
            return (
              <div key={id} className="flex items-center justify-between gap-2">
                <span className="truncate">{p.nombre}</span>
                <span className="flex items-center gap-1">
                  <button
                    type="button"
                    aria-label={`Quitar uno de ${p.nombre}`}
                    onClick={() => sumar(p.item_id, -1)}
                    className="rounded border p-1"
                  >
                    {cant === 1 ? <Trash2 className="size-3" /> : <Minus className="size-3" />}
                  </button>
                  <span className="w-6 text-center tabular-nums">{cant}</span>
                  <button
                    type="button"
                    aria-label={`Agregar uno de ${p.nombre}`}
                    onClick={() => sumar(p.item_id, 1)}
                    className="rounded border p-1"
                  >
                    <Plus className="size-3" />
                  </button>
                  <span className="w-20 text-right">{pesos(String(p.precio * cant))}</span>
                </span>
              </div>
            )
          })}
          <div className="flex justify-between border-t pt-1 font-medium">
            <span>Total</span>
            <span>{pesos(String(total))}</span>
          </div>
        </div>
      )}

      {esMostrador ? (
        <label className="block space-y-1">
          <span className="text-sm font-medium">Cobrar con</span>
          <select
            className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
            value={medio}
            onChange={(e) => setMedio(e.target.value)}
            disabled={qr === 'esperando'}
          >
            {medios.map((m) => (
              <option key={m.valor} value={m.valor}>{m.etiqueta}</option>
            ))}
          </select>
        </label>
      ) : (
        <p className="text-sm text-muted-foreground">
          Se carga a la cancha: se cobra y se factura junto con el turno.
        </p>
      )}

      {/* 🔴 **Con MercadoPago elegido y sin credenciales, la pantalla lo DICE.**
          El bug de la Caja del 2026-08-28 fue exactamente éste: un `return null`
          dejaba el camino sin botón y sin motivo, y el humano lo reportó como
          *"no me dirige a ningún lado"*. Mismo texto que `SeccionDeCobroConQr` a
          propósito: dos redacciones distintas para lo mismo es cómo una termina
          diciendo otra cosa. */}
      {porQr && qrDeLaInstancia !== null && !qrDeLaInstancia.disponible && (
        <div className="space-y-2 rounded-md border border-dashed p-3">
          <p className="text-sm text-muted-foreground">
            Para cobrar con el QR del mostrador faltan las credenciales de
            MercadoPago. Se cargan en Configuración → Mercado Pago.
          </p>
          {sePuedeSimular && (
            <>
              <p className="text-xs text-muted-foreground">
                Instancia de prueba: se puede simular el pago para recorrer el
                circuito completo.
              </p>
              <button
                type="button"
                disabled={simulando || lineas.length === 0}
                onClick={simular}
                className={buttonVariants({ variant: 'outline' })}
              >
                <QrCode className="size-4" />
                {simulando ? 'Simulando el pago…' : 'Simular pago aprobado'}
              </button>
            </>
          )}
        </div>
      )}

      {qr === 'esperando' ? (
        <div className="space-y-2 rounded-md border px-3 py-2 text-sm">
          {/* El spinner no es decoración: es lo que distingue «está esperando»
              de «se colgó». */}
          <p className="flex items-center gap-1.5 font-medium text-amber-700 dark:text-amber-400">
            <Loader2 className="size-3.5 animate-spin" /> Esperando el pago…
          </p>
          <p>
            El QR de la caja ya está cobrando{' '}
            <strong>{enElQr === null ? '' : pesos(enElQr.monto)}</strong>. Pedile
            al cliente que lo escanee.
          </p>
          <button
            type="button"
            onClick={() => {
              frenarPoll()
              if (enElQr !== null) void bajarDelQr(enElQr.venta_id)
              setQr('idle')
              setEnElQr(null)
            }}
            className="text-sm text-red-800 underline underline-offset-2"
          >
            Cancelar el cobro por QR
          </button>
        </div>
      ) : (
        <div className="flex justify-end gap-2">
          {onCerrar !== undefined && (
            <button
              type="button"
              onClick={cerrar}
              className={buttonVariants({ variant: 'outline' })}
            >
              Cancelar
            </button>
          )}
          <button
            type="button"
            // Con el QR elegido y sin credenciales el botón no se ofrece
            // habilitado: sólo podría fallar. Lo que sí se ofrece —arriba— es el
            // motivo, y en dev el simulador.
            disabled={
              enviando
              || lineas.length === 0
              || qr === 'poniendo'
              || (porQr && !qrDeLaInstancia?.disponible)
            }
            onClick={porQr ? cobrarConQr : cargar}
            className={buttonVariants()}
          >
            {etiquetaDelBoton()}
          </button>
        </div>
      )}
    </div>
  )
}

/** El mismo carrito, en una ventana. Para cargar consumo a la cuenta de una
 *  cancha: ahí abajo hay una cuenta abierta que no se puede tapar con una
 *  navegación, y el diálogo es lo que deja volver a ella. */
export function DialogoDeConsumo({
  abierto,
  sucursalId,
  reservaId = null,
  onCerrar,
  onCargado,
}: {
  abierto: boolean
  sucursalId: number
  reservaId?: number | null
  onCerrar: () => void
  onCargado: () => void
}) {
  return (
    <Dialog open={abierto} onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {reservaId === null ? 'Venta de buffet' : 'Cargar consumo a la cancha'}
          </DialogTitle>
        </DialogHeader>
        <PanelDeConsumo
          sucursalId={sucursalId}
          reservaId={reservaId}
          activo={abierto}
          onCargado={onCargado}
          onCerrar={onCerrar}
        />
      </DialogContent>
    </Dialog>
  )
}
