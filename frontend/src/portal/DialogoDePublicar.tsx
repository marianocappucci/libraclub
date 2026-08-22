/** «Me faltan jugadores»: publicar un partido desde una reserva propia.
 *
 * Se entra desde «Mis reservas» y no desde la pantalla de partidos: el
 * organizador ya tiene su turno reservado y lo que quiere es completarlo, no
 * buscar uno.
 */
import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

import { partidos as api } from '@/lib/api'
import type { ReservaDelJugador } from '@/lib/api'
import { fecha, hora } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function DialogoDePublicar({
  reserva,
  onCerrar,
  onPublicado,
}: {
  reserva: ReservaDelJugador | null
  onCerrar: () => void
  onPublicado: () => void
}) {
  const [faltan, setFaltan] = useState('2')
  const [nota, setNota] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [listo, setListo] = useState(false)

  useEffect(() => {
    setError(null)
    setListo(false)
    setFaltan('2')
    setNota('')
  }, [reserva])

  if (!reserva) return null

  async function publicar() {
    setError(null)
    setEnviando(true)
    try {
      await api.publicar(reserva!.id, { faltan: Number(faltan), nota })
      setListo(true)
      onPublicado()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{listo ? 'Publicado' : '¿Cuántos faltan?'}</DialogTitle>
        </DialogHeader>

        {listo ? (
          <div className="space-y-3 text-sm">
            <p>
              Tu partido ya aparece en «Falta uno». Cuando alguien se sume, vas a
              ver cómo contactarlo.
            </p>
            <div className="flex justify-end">
              <Button onClick={onCerrar}>Listo</Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3 text-sm">
            <div className="rounded-md border bg-card p-3">
              <div className="font-medium">
                {fecha(reserva.comienza_at)} · {hora(reserva.comienza_at)}
              </div>
              <div className="text-muted-foreground">{reserva.cancha}</div>
            </div>

            <label className="block space-y-1">
              <span className="font-medium">Jugadores que faltan</span>
              <Input
                inputMode="numeric"
                value={faltan}
                onChange={(e) => setFaltan(e.target.value)}
              />
              {/* Lo dice el organizador y no se deduce del deporte: en un fútbol
                  5 pueden faltar dos o pueden faltar siete. */}
              <span className="text-xs text-muted-foreground">
                Los que necesitás para completar el partido.
              </span>
            </label>

            <label className="block space-y-1">
              <span className="font-medium">
                Nota <span className="text-muted-foreground">(opcional)</span>
              </span>
              <Input
                value={nota}
                onChange={(e) => setNota(e.target.value)}
                placeholder="Nivel intermedio, traer paletas…"
              />
            </label>

            <p className="text-muted-foreground">
              Tu nombre va a ser visible para quien mire los partidos. Tu teléfono
              lo ven <strong>sólo los que se anoten</strong>.
            </p>

            <AvisoDeError mensaje={error} />

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={onCerrar}>
                Cancelar
              </Button>
              <Button
                disabled={enviando || !Number(faltan)}
                onClick={publicar}
              >
                {enviando ? 'Publicando…' : 'Publicar'}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
