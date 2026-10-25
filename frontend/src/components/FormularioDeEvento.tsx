import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

import { eventos as api } from '@/lib/api'
import type { Cancha, Evento } from '@/lib/api'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { diaISO } from '@/lib/fechas'

/** Alta y edición de un evento: un campeonato con varias categorías.
 *
 * Lo que el evento fija para todas sus categorías son **las fechas y las
 * canchas**. Las fechas se copian a cada categoría —y al editarlas acá cambian
 * en todas—; las canchas son las únicas que se ofrecen al darle cancha a un
 * partido. Sin ninguna tildada, vale cualquiera de la sucursal.
 */
export function FormularioDeEvento({
  abierto,
  sucursalId,
  canchas,
  evento = null,
  onCerrar,
  onGuardado,
}: {
  abierto: boolean
  sucursalId: number
  /** Las canchas activas de la sucursal. */
  canchas: Cancha[]
  /** Si viene, se edita; si no, se crea. */
  evento?: Evento | null
  onCerrar: () => void
  onGuardado: (evento: Evento) => void
}) {
  const [nombre, setNombre] = useState('')
  const [desde, setDesde] = useState(diaISO(new Date()))
  const [hasta, setHasta] = useState('')
  const [elegidas, setElegidas] = useState<number[]>([])
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    setNombre(evento?.nombre ?? '')
    setDesde(evento?.desde ?? diaISO(new Date()))
    setHasta(evento?.hasta ?? '')
    setElegidas(evento?.cancha_ids ?? [])
  }, [abierto, evento])

  function alternar(id: number) {
    setElegidas((l) => (l.includes(id) ? l.filter((c) => c !== id) : [...l, id]))
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setEnviando(true)
    try {
      const cuerpo = {
        nombre: nombre.trim(),
        desde,
        hasta: hasta || null,
        observaciones: evento?.observaciones ?? null,
        cancha_ids: elegidas,
      }
      onGuardado(
        evento
          ? await api.editar(evento.id, cuerpo)
          : await api.crear({ ...cuerpo, sucursal_id: sucursalId }),
      )
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  if (!abierto) return null

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{evento ? 'Editar el evento' : 'Nuevo evento'}</DialogTitle>
        </DialogHeader>

        <form onSubmit={enviar} className="space-y-3 text-sm">
          <label className="block space-y-1">
            <span className="font-medium">Nombre</span>
            <Input
              autoFocus
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              placeholder="Americano de primavera"
            />
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="block space-y-1">
              <span className="font-medium">Desde</span>
              <Input type="date" value={desde} onChange={(e) => setDesde(e.target.value)} />
            </label>
            <label className="block space-y-1">
              <span className="font-medium">
                Hasta <span className="text-muted-foreground">(opcional)</span>
              </span>
              <Input type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} />
            </label>
          </div>
          {evento && (
            <p className="text-xs text-muted-foreground">
              Si cambiás las fechas, cambian en todas las categorías del evento.
            </p>
          )}

          <fieldset className="space-y-1">
            <legend className="font-medium">Canchas del evento</legend>
            <p className="text-xs text-muted-foreground">
              Los partidos de todas las categorías se juegan en estas canchas. Sin
              ninguna tildada, vale cualquiera de la sucursal.
            </p>
            <div className="grid grid-cols-2 gap-2 pt-1">
              {canchas.map((cancha) => (
                <label
                  key={cancha.id}
                  className="flex cursor-pointer items-center gap-2 rounded-md border bg-card p-2"
                >
                  <input
                    type="checkbox"
                    checked={elegidas.includes(cancha.id)}
                    onChange={() => alternar(cancha.id)}
                  />
                  <span>{cancha.nombre}</span>
                </label>
              ))}
              {!canchas.length && (
                <p className="col-span-2 text-xs text-muted-foreground">
                  Esta sucursal todavía no tiene canchas cargadas.
                </p>
              )}
            </div>
          </fieldset>

          <AvisoDeError mensaje={error} />

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onCerrar}>
              Cancelar
            </Button>
            <Button type="submit" disabled={enviando || !nombre.trim() || !desde}>
              {enviando ? 'Guardando…' : evento ? 'Guardar' : 'Crear evento'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
