import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  agenda, buffet, cobroDelTurno, cobroQr, cuentaCorriente, facturacion, TIPO_DE_FACTURA,
} from '@/lib/api'
import type {
  Cancha, EstadoDeCobro, Factura, LineaDeConsumo, QrDisponible, Turno,
} from '@/lib/api'
import { useAuth } from '@/context/AuthContext'
import { fecha, hora, pesos } from '@/lib/fechas'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useMediosDePago } from '@/lib/medios-pago'
import { AvisoDeError } from '@/components/listado'
import { buttonVariants } from '@/components/ui/button'
import { DialogoDeConsumo } from '@/components/DialogoDeConsumo'

/**
 * Las transiciones que se ofrecen según el estado actual.
 *
 * 🔴 **Es un espejo de la máquina de estados del backend, no la fuente.** El
 * servidor rechaza con 409 cualquier transición que no corresponda —una reserva
 * jugada no se cancela— y eso sigue valiendo aunque esta tabla se equivoque. Lo
 * que hace acá es no ofrecerle al operador un botón que va a fallar.
 */
const ACCIONES: Record<string, { estado: string; texto: string; peligro?: boolean }[]> = {
  provisoria: [
    { estado: 'confirmada', texto: 'Confirmar' },
    { estado: 'cancelada', texto: 'Cancelar', peligro: true },
  ],
  pendiente_pago: [
    { estado: 'confirmada', texto: 'Confirmar' },
    { estado: 'cancelada', texto: 'Cancelar', peligro: true },
  ],
  confirmada: [
    { estado: 'jugada', texto: 'Marcar jugada' },
    { estado: 'ausente', texto: 'No vino' },
    { estado: 'cancelada', texto: 'Cancelar', peligro: true },
  ],
  bloqueo: [{ estado: 'cancelada', texto: 'Quitar bloqueo', peligro: true }],
  jugada: [],
  cancelada: [],
  ausente: [],
}

const NOMBRE: Record<string, string> = {
  provisoria: 'Provisoria',
  pendiente_pago: 'Pendiente de pago',
  confirmada: 'Confirmada',
  jugada: 'Jugada',
  cancelada: 'Cancelada',
  ausente: 'No vino',
  bloqueo: 'Bloqueo',
}

export function DetalleDeReserva({
  abierto,
  cancha,
  turno,
  onCerrar,
  onCambiada,
}: {
  abierto: boolean
  cancha: Cancha | null
  turno: Turno | null
  onCerrar: () => void
  onCambiada: () => void
}) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (abierto) {
      setMotivo('')
      setError(null)
    }
  }, [abierto])

  if (!cancha || !turno || turno.reserva_id === null) return null

  const estado = turno.estado ?? ''
  const acciones = ACCIONES[estado] ?? []

  async function accionar(nuevo: string, pideMotivo: boolean) {
    if (!turno?.reserva_id) return
    if (pideMotivo && !motivo.trim()) {
      // Una cancelación sin motivo es una discusión con un cliente dentro de un
      // mes que nadie va a poder reconstruir.
      setError('Poné el motivo antes de cancelar.')
      return
    }
    setEnviando(true)
    setError(null)
    try {
      await agenda.cambiarEstado(turno.reserva_id, nuevo, motivo.trim() || undefined)
      onCambiada()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  // `onOpenChange` recibe el estado NUEVO. Se llama a `onCerrar` sólo cuando
  // llega `false`: el padre es quien tiene el estado y quien decide. Hoy nunca
  // llega `true` —ninguno de estos diálogos tiene `DialogTrigger`, los abre el
  // padre—, así que el `if` es defensivo. Ver la nota en `dialogos.test.tsx`
  // sobre por qué no se puede cubrir con un test.
  return (
    <Dialog open={abierto} onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{estado === 'bloqueo' ? 'Bloqueo' : 'Reserva'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="rounded-md bg-muted px-3 py-2 text-sm">
            <div className="font-medium">{cancha.nombre}</div>
            <div className="text-muted-foreground">
              {fecha(turno.comienza_at)} · {hora(turno.comienza_at)} a{' '}
              {hora(turno.termina_at)}
            </div>
            <div className="text-muted-foreground">
              {turno.cliente ?? turno.motivo ?? '—'} · {NOMBRE[estado] ?? estado}
            </div>
          </div>

          <SeccionDeConsumo
            turno={turno}
            cancha={cancha}
            abierto={abierto}
            onCambio={onCambiada}
          />
          <SeccionDeCobroConQr
            reservaId={turno.reserva_id}
            estado={estado}
            abierto={abierto}
            onCobrado={onCambiada}
          />
          <SeccionDeCobro
            reservaId={turno.reserva_id}
            estado={estado}
            abierto={abierto}
            onCobrado={onCambiada}
          />
          <SeccionDeFactura reservaId={turno.reserva_id} abierto={abierto} />
          <SeccionDeCuentaCorriente turno={turno} abierto={abierto} />

          {acciones.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Una reserva {NOMBRE[estado]?.toLowerCase()} ya no se puede cambiar.
            </p>
          ) : (
            <>
              <label className="block space-y-1">
                <span className="text-sm font-medium">
                  Motivo <span className="text-muted-foreground">(obligatorio para cancelar)</span>
                </span>
                <Input
                  
                  value={motivo}
                  onChange={(e) => setMotivo(e.target.value)}
                />
              </label>

              <AvisoDeError mensaje={error} />

              <div className="flex flex-wrap justify-end gap-2">
                {acciones.map((a) => (
                  <button
                    key={a.estado}
                    type="button"
                    disabled={enviando}
                    onClick={() => accionar(a.estado, Boolean(a.peligro))}
                    className={`rounded-md px-3 py-2 text-sm disabled:opacity-50 ${
                      a.peligro
                        ? 'border border-red-300 text-red-800 hover:bg-red-50'
                        : 'bg-primary text-primary-foreground'
                    }`}
                  >
                    {a.texto}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}


/** Cobrar el turno con el QR de MercadoPago del mostrador.
 *
 * 🔑 **No hay ninguna imagen de QR acá, y no falta nada.** Es el modelo de QR
 * fijo por punto de venta: el cartel del mostrador no cambia nunca; lo que el
 * botón cambia es *cuánto cobra* cuando el cliente lo escanea. Lo que se cobra
 * es el turno entero — la cancha **más** el consumo de buffet.
 *
 * 🔴 **Cancelar baja el monto del cartel.** Una orden que queda puesta le sigue
 * cobrando ese monto a quien escanee, aunque el encargado haya cerrado el
 * diálogo hace media hora.
 */
const POLL_MS = 3000
/** Cinco minutos: pasado eso el cliente ya se fue del mostrador. */
const ESPERA_MAXIMA_MS = 5 * 60 * 1000

/** Los estados en los que tiene sentido cobrar. Espeja `ESTADOS_COBRABLES` del
 *  backend, que es quien decide de verdad: `jugada` entra porque en un complejo
 *  el grupo suele pagar al terminar. */
const COBRABLES = ['confirmada', 'jugada']

type EstadoQr = 'idle' | 'poniendo' | 'esperando' | 'cobrado'

function SeccionDeCobroConQr({ reservaId, estado, abierto, onCobrado }: {
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

  useEffect(() => {
    if (!abierto) return
    setQr('idle')
    setError(null)
    setMonto(null)
    cobroQr.estado()
      .then(setDisponible)
      // Sin respuesta, la sección no aparece: cobrar por QR es una forma más
      // de cobrar, no un requisito para operar el mostrador.
      .catch(() => setDisponible({ disponible: false, auto_facturar: false }))
  }, [abierto])

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
      <p className="text-xs text-muted-foreground">
        Pone el total del turno —cancha y buffet— en el QR impreso del mostrador
        {disponible.auto_facturar ? ' y factura solo al acreditarse' : ''}.
      </p>
    </div>
  )
}


/** La factura de la reserva: la muestra si existe, y si no ofrece emitirla.
 *
 * 🔑 **Se pide al abrir el diálogo y no al montar la grilla.** La agenda dibuja
 * cientos de turnos por semana; pedir el comprobante de cada uno serían cientos
 * de requests para un dato que casi nadie mira.
 *
 * ⚠️ Una factura **sin CAE no es un error**: existe, tiene número, y lo que
 * falta es que ARCA lo autorice. Sin certificado cargado en la instancia pasa
 * siempre — por eso se dice "pendiente de CAE" y no se muestra un error rojo,
 * que mandaría a buscar un problema que no está.
 */
/** Lo cobrado del turno, y el botón para cobrar lo que falta.
 *
 * 🔑 **Va acá y no en la pantalla de Caja** porque es el único lugar donde se
 * sabe de qué reserva es la plata. En Caja el cobro se carga como monto más
 * concepto libre: sirve para un ingreso suelto y deja el comprobante del turno
 * viéndose «sin cobrar», que es exactamente lo que este flujo viene a cerrar.
 *
 * El monto arranca en el pendiente y **se puede bajar**: una seña es un cobro
 * parcial, y es la mitad del modelo que `facturar_reserva` declara —la seña y el
 * saldo, dos movimientos contra la misma factura—.
 *
 * ⚠️ Si el complejo no tiene facturación configurada, el endpoint contesta 503 y
 * la sección **no aparece**: no es un error que mostrar, es que esta instancia
 * no lleva caja contra LibraCore.
 */
function SeccionDeCobro({ reservaId, estado, abierto, onCobrado }: {
  reservaId: number | null
  estado: string
  abierto: boolean
  onCobrado: () => void
}) {
  const [datos, setDatos] = useState<EstadoDeCobro | null>(null)
  const [monto, setMonto] = useState('')
  const [medio, setMedio] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { medios, etiqueta: etiquetaDeMedio } = useMediosDePago()

  useEffect(() => {
    if (!abierto || reservaId === null) return
    setError(null)
    cobroDelTurno
      .ver(reservaId)
      .then((d) => {
        setDatos(d)
        setMonto(d.pendiente > 0 ? String(d.pendiente) : '')
      })
      .catch(() => setDatos(null))
  }, [abierto, reservaId])

  // El medio por defecto espera a que la lista llegue: con `''` el cobro entra
  // sin medio y el arqueo por medio no cuadra. Mismo cuidado que en Caja.
  useEffect(() => {
    if (!medio && medios.length > 0) setMedio(medios[0].valor)
  }, [medio, medios])

  if (reservaId === null || datos === null) return null
  // Un bloqueo o una reserva cancelada no se cobran.
  if (!COBRABLES.includes(estado)) return null

  return (
    <div className="grid gap-2 rounded-lg border p-3">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">Cobro del turno</span>
        <span className={datos.pendiente > 0 ? 'text-muted-foreground' : 'text-emerald-700'}>
          {datos.pendiente > 0
            ? `Pendiente ${pesos(String(datos.pendiente))} de ${pesos(String(datos.total))}`
            : `Cobrado ${pesos(String(datos.cobrado))}`}
        </span>
      </div>

      {datos.cobros.length > 0 && (
        // `flex flex-col` y no `grid`: un grid implícito dimensiona su columna a
        // `max-content` y la fila se lleva el importe fuera del recuadro. Mismo
        // caso que la lista de movimientos de Caja, medido el 2026-08-28.
        <ul className="flex flex-col gap-0.5 text-sm text-muted-foreground">
          {datos.cobros.map((c) => (
            <li key={c.id} className="flex justify-between gap-2">
              <span className="truncate">
                {fecha(c.fecha)} · {etiquetaDeMedio(c.medio_pago)}
              </span>
              <span>{pesos(String(c.monto))}</span>
            </li>
          ))}
        </ul>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}

      {datos.pendiente > 0 && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="grid gap-1">
            <Label htmlFor="monto-cobro" className="text-xs">Monto</Label>
            <Input
              id="monto-cobro"
              className="h-8 w-28"
              inputMode="decimal"
              value={monto}
              onChange={(e) => setMonto(e.target.value)}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="medio-cobro" className="text-xs">Medio</Label>
            <select
              id="medio-cobro"
              className="h-8 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
              value={medio}
              onChange={(e) => setMedio(e.target.value)}
            >
              {medios.map((m) => (
                <option key={m.valor} value={m.valor}>{m.etiqueta}</option>
              ))}
            </select>
          </div>
          <button
            className={buttonVariants({ size: 'sm' })}
            disabled={enviando || !monto.trim() || !medio}
            onClick={async () => {
              setEnviando(true)
              setError(null)
              try {
                const d = await cobroDelTurno.registrar(reservaId, {
                  monto, medio_pago: medio,
                })
                setDatos(d)
                setMonto(d.pendiente > 0 ? String(d.pendiente) : '')
                onCobrado()
              } catch (e) {
                setError((e as Error).message)
              } finally {
                setEnviando(false)
              }
            }}
          >
            {enviando ? 'Cobrando…' : 'Cobrar'}
          </button>
        </div>
      )}
    </div>
  )
}


function SeccionDeFactura(
  { reservaId, abierto }: { reservaId: number | null; abierto: boolean },
) {
  const { user } = useAuth()
  const [factura, setFactura] = useState<Factura | null>(null)
  const [cargando, setCargando] = useState(false)
  const [emitiendo, setEmitiendo] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!abierto || reservaId === null) return
    setError(null)
    setCargando(true)
    facturacion
      .ver(reservaId)
      .then(setFactura)
      // Una instancia sin facturación configurada contesta 503. No es un error
      // que mostrar: es que este complejo no factura, y la sección no aparece.
      .catch(() => setFactura(null))
      .finally(() => setCargando(false))
  }, [abierto, reservaId])

  if (reservaId === null || cargando) return null

  if (factura) {
    const tipo = TIPO_DE_FACTURA[factura.tipo] ?? factura.tipo
    const numero = `${String(factura.punto_venta).padStart(4, '0')}-${String(factura.numero).padStart(8, '0')}`
    return (
      <div className="flex items-start justify-between gap-2 rounded-md border px-3 py-2 text-sm">
        <div>
          <div className="font-medium">Factura {tipo} {numero}</div>
          <div className="text-muted-foreground">
            {factura.cae
              ? `CAE ${factura.cae}`
              : 'Pendiente de CAE — la instancia todavía no tiene certificado de ARCA'}
          </div>
        </div>
        {/* El PDF también acá y no sólo en el listado: éste es el momento en que
            alguien lo quiere —se acaba de facturar el turno y hay que dárselo al
            cliente—.

            Sólo para admin, por el mismo motivo que el botón de emitir: el
            endpoint del PDF lleva `require_admin`, así que al encargado el link
            le daría 403. El bloque de arriba —el número y el CAE— sí lo ve,
            porque eso viene de `/api/reservas/{id}/factura`, que es de staff. */}
        {user?.role === 'admin' && (
          <a
            href={facturacion.urlDelPdf(factura.id)}
            target="_blank"
            rel="noreferrer"
            className={buttonVariants({ variant: 'outline', size: 'sm' })}
          >
            Ver PDF
          </a>
        )}
      </div>
    )
  }

  // 🔑 El botón sólo para admin: el backend lo gatea igual con 403, y ofrecerlo
  // a un encargado sería un botón que siempre falla.
  if (user?.role !== 'admin') return null

  async function emitir() {
    if (reservaId === null) return
    setError(null)
    setEmitiendo(true)
    try {
      setFactura(await facturacion.emitir(reservaId))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setEmitiendo(false)
    }
  }

  return (
    <div className="space-y-2">
      <AvisoDeError mensaje={error} />
      <button
        type="button"
        disabled={emitiendo}
        onClick={emitir}
        className={buttonVariants({ variant: 'outline' })}
      >
        {emitiendo ? 'Emitiendo…' : 'Facturar esta reserva'}
      </button>
    </div>
  )
}


/** Fiar la reserva: la carga a la cuenta corriente del cliente.
 *
 * El caso real: *"el grupo de los martes paga a fin de mes"*. La cancha se
 * juega igual, y la deuda queda registrada.
 *
 * 🔑 **No se pide nada al abrir el diálogo.** A diferencia de la factura, acá no
 * hay estado previo que mostrar: si el cliente ya tiene la reserva cargada,
 * volver a apretar el botón no le fía dos veces —la `referencia` lo hace
 * idempotente en el backend—, así que no hace falta una consulta para saberlo.
 *
 * El botón es de mostrador: decidir que alguien paga a fin de mes es parte de
 * atender. Un bloqueo o una reserva sin precio no se pueden fiar y el botón no
 * aparece — el backend las rechaza con 422 igual.
 */
function SeccionDeCuentaCorriente(
  { turno, abierto }: { turno: Turno; abierto: boolean },
) {
  const [saldo, setSaldo] = useState<number | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // El diálogo se remonta por turno, pero el estado de un fiado anterior no
  // tiene por qué sobrevivir a cerrarlo y abrirlo de nuevo.
  useEffect(() => {
    if (!abierto) { setSaldo(null); setError(null) }
  }, [abierto])

  if (turno.reserva_id === null || turno.cliente === null || turno.precio === null) return null

  if (saldo !== null) {
    return (
      <div className="rounded-md border px-3 py-2 text-sm">
        <div className="font-medium">Cargado a la cuenta de {turno.cliente}</div>
        <div className="text-muted-foreground">
          {saldo >= 0 ? `Debe ${pesos(String(saldo))}` : `A favor ${pesos(String(-saldo))}`}
        </div>
      </div>
    )
  }

  async function cargar() {
    if (turno.reserva_id === null) return
    setError(null)
    setEnviando(true)
    try {
      setSaldo((await cuentaCorriente.cargar(turno.reserva_id)).saldo)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="space-y-2">
      <AvisoDeError mensaje={error} />
      <button
        type="button"
        disabled={enviando}
        onClick={cargar}
        className={buttonVariants({ variant: 'outline' })}
      >
        {enviando ? 'Cargando…' : 'Cargar a la cuenta'}
      </button>
    </div>
  )
}


/** Lo consumido en el buffet durante ese turno, y el botón para cargar más.
 *
 * 🔑 **Va junto a la factura, y arriba de ella**: el consumo entra en ese
 * comprobante, así que el orden en la pantalla es el orden en que se hacen las
 * cosas — primero se carga lo que tomaron, después se factura todo junto.
 *
 * Una vez facturada la reserva **no se carga más**: no entraría en ese
 * comprobante y quedaría cobrado sin respaldo. El backend lo corta con 409 y
 * acá directamente no se ofrece.
 */
function SeccionDeConsumo({ turno, cancha, abierto, onCambio }: {
  turno: Turno
  cancha: Cancha
  abierto: boolean
  onCambio: () => void
}) {
  // 🔴 **La sucursal sale de la CANCHA, no del selector de arriba.** El stock es
  // por sucursal: descontar del depósito de la sucursal "activa" mandaría el
  // consumo al lugar equivocado en cuanto alguien mire una cancha de otra sede.
  // Además ataba este componente a `SucursalProvider`, que es lo que rompió el
  // test del diálogo — el defecto de diseño se manifestó ahí primero.
  const sucursalId = cancha.sucursal_id
  const [datos, setDatos] = useState<{ total: number; lineas: LineaDeConsumo[] } | null>(null)
  const [cargando, setCargando] = useState(false)
  const [facturada, setFacturada] = useState(false)
  const [agregando, setAgregando] = useState(false)

  const recargar = useCallback(() => {
    if (turno.reserva_id === null) return
    setCargando(true)
    buffet
      .consumosDe(turno.reserva_id)
      // Una instancia sin buffet configurado contesta 503: no es un error que
      // mostrar, es que este complejo no tiene buffet y la sección no aparece.
      .then(setDatos)
      .catch(() => setDatos(null))
      .finally(() => setCargando(false))
  }, [turno.reserva_id])

  useEffect(() => {
    if (!abierto || turno.reserva_id === null) return
    recargar()
    facturacion
      .ver(turno.reserva_id)
      .then((f) => setFacturada(f !== null))
      .catch(() => setFacturada(false))
  }, [abierto, turno.reserva_id, recargar])

  if (turno.reserva_id === null || turno.cliente === null || cargando || datos === null) {
    return null
  }

  return (
    <div className="space-y-2">
      {datos.lineas.length > 0 && (
        <div className="rounded-md border px-3 py-2 text-sm">
          <div className="font-medium">Consumido en el buffet</div>
          {datos.lineas.map((l, i) => (
            <div key={`${l.descripcion}-${i}`} className="flex justify-between text-muted-foreground">
              <span>
                {l.cantidad} × {l.descripcion}
              </span>
              <span>{pesos(String(l.importe))}</span>
            </div>
          ))}
          <div className="flex justify-between border-t pt-1 font-medium">
            <span>Total del buffet</span>
            <span>{pesos(String(datos.total))}</span>
          </div>
          {turno.precio !== null && (
            // El total con la cancha: es el número que se le dice al cliente, y
            // el que va a salir en la factura.
            <div className="flex justify-between text-muted-foreground">
              <span>Con la cancha</span>
              <span>{pesos(String(Number(turno.precio) + datos.total))}</span>
            </div>
          )}
        </div>
      )}

      {!facturada && (
        <>
          <button
            type="button"
            onClick={() => setAgregando(true)}
            className={buttonVariants({ variant: 'outline' })}
          >
            Cargar consumo
          </button>
          <DialogoDeConsumo
            abierto={agregando}
            sucursalId={sucursalId}
            reservaId={turno.reserva_id}
            onCerrar={() => setAgregando(false)}
            onCargado={() => {
              setAgregando(false)
              recargar()
              onCambio()
            }}
          />
        </>
      )}
    </div>
  )
}
