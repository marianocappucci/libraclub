import { useCallback, useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { agenda, buffet, cuentaCorriente, facturacion, TIPO_DE_FACTURA } from '@/lib/api'
import type { Cancha, Factura, LineaDeConsumo, Turno } from '@/lib/api'
import { useAuth } from '@/context/AuthContext'
import { fecha, hora, pesos } from '@/lib/fechas'
import { Input } from '@/components/ui/input'
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
      <div className="rounded-md border px-3 py-2 text-sm">
        <div className="font-medium">Factura {tipo} {numero}</div>
        <div className="text-muted-foreground">
          {factura.cae
            ? `CAE ${factura.cae}`
            : 'Pendiente de CAE — la instancia todavía no tiene certificado de ARCA'}
        </div>
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
