import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { agenda } from '@/lib/api'
import type { Cancha, Turno } from '@/lib/api'
import { fecha, hora } from '@/lib/fechas'

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
          <div className="rounded-md bg-slate-100 px-3 py-2 text-sm">
            <div className="font-medium">{cancha.nombre}</div>
            <div className="text-slate-600">
              {fecha(turno.comienza_at)} · {hora(turno.comienza_at)} a{' '}
              {hora(turno.termina_at)}
            </div>
            <div className="text-slate-600">
              {turno.cliente ?? turno.motivo ?? '—'} · {NOMBRE[estado] ?? estado}
            </div>
          </div>

          {acciones.length === 0 ? (
            <p className="text-sm text-slate-500">
              Una reserva {NOMBRE[estado]?.toLowerCase()} ya no se puede cambiar.
            </p>
          ) : (
            <>
              <label className="block space-y-1">
                <span className="text-sm text-slate-600">
                  Motivo <span className="text-slate-400">(obligatorio para cancelar)</span>
                </span>
                <input
                  className="w-full rounded-md border border-slate-300 px-3 py-2"
                  value={motivo}
                  onChange={(e) => setMotivo(e.target.value)}
                />
              </label>

              {error && (
                <p
                  role="alert"
                  className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
                >
                  {error}
                </p>
              )}

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
                        : 'bg-slate-900 text-white'
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
