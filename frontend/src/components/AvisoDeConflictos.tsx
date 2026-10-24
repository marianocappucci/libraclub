import { useCallback, useEffect, useState } from 'react'
import { conflictos } from '@/lib/api'
import type { ConflictoDeReserva } from '@/lib/api'
import { fechaHora, hora } from '@/lib/fechas'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { AvisoDeError } from '@/components/listado'

/**
 * Las reservas que se dieron en el club sin conexión y chocaron con otra que llegó antes al central (ADR-022).
 *
 * Una sola pieza mínima: lista cada conflicto con la reserva que ganó y deja resolverlo —**mover** a otro horario
 * libre o **cancelar**—. La pantalla de verdad (bandeja, estados «provisoria» y «en conflicto» del kit) es del PR 13
 * en libra-ui; esto es lo que hace falta para que el conflicto no quede invisible.
 *
 * Sin conflictos no dibuja nada. En el equipo del local (`se_puede_resolver` falso) los muestra sin botones: el
 * conflicto baja por el espejo y se resuelve desde el central.
 *
 * `role="status"` y no `alert`: no frena nada, la cancha está tomada por la reserva que ganó.
 */
export function AvisoDeConflictos({
  sucursalId,
  onResuelto,
}: {
  sucursalId: number | null
  onResuelto?: () => void
}) {
  const [lista, setLista] = useState<ConflictoDeReserva[]>([])
  const [error, setError] = useState<string | null>(null)
  const [moviendo, setMoviendo] = useState<number | null>(null)
  const [nuevoHorario, setNuevoHorario] = useState('')
  const [enviando, setEnviando] = useState(false)

  const cargar = useCallback(() => {
    if (sucursalId === null) return
    conflictos
      .listar(sucursalId)
      .then((l) => setLista(Array.isArray(l) ? l : []))
      // Un aviso que no carga no tiene que tirar abajo la agenda: se queda sin dibujar.
      .catch(() => setLista([]))
  }, [sucursalId])

  useEffect(cargar, [cargar])

  async function resolver(accion: () => Promise<unknown>) {
    setEnviando(true)
    setError(null)
    try {
      await accion()
      setMoviendo(null)
      setNuevoHorario('')
      cargar()
      onResuelto?.()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  if (lista.length === 0) return null

  return (
    <section
      role="status"
      aria-label="Reservas en conflicto"
      className="space-y-3 rounded-md border border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40 px-3 py-3 text-sm text-amber-900 dark:text-amber-200"
    >
      <p className="font-medium">
        {lista.length === 1
          ? 'Hay 1 reserva en conflicto'
          : `Hay ${lista.length} reservas en conflicto`}
      </p>
      <p>
        Se dieron en el club sin conexión y la cancha ya la había tomado otra reserva que llegó antes.
        No ocupan la cancha: hay que llamar al cliente y moverlas o cancelarlas.
      </p>
      <AvisoDeError mensaje={error} />
      <ul className="space-y-3">
        {lista.map((c) => (
          <li key={c.reserva.id} className="space-y-2 rounded border border-amber-200 bg-background/60 p-2">
            <p>
              <strong>{c.cliente_nombre ?? 'Sin cliente'}</strong>
              {` · ${c.cancha_nombre ?? 'Cancha'} · ${fechaHora(c.reserva.comienza_at)} a ${hora(c.reserva.termina_at)}`}
            </p>
            <p className="text-xs">
              {c.ganadora
                ? `Se quedó con la cancha ${c.ganadora.cliente_nombre ?? 'otra reserva'} `
                  + `(${fechaHora(c.ganadora.comienza_at)} a ${hora(c.ganadora.termina_at)}, ${c.ganadora.estado}).`
                : 'La reserva que ganó ya no se encuentra.'}
            </p>
            {c.se_puede_resolver ? (
              moviendo === c.reserva.id ? (
                <form
                  className="flex flex-wrap items-end gap-2"
                  onSubmit={(e) => {
                    e.preventDefault()
                    // Sin zona: el backend lo toma como hora local del complejo.
                    void resolver(() =>
                      conflictos.mover(c.reserva.id, nuevoHorario ? { comienza_at: nuevoHorario } : {}))
                  }}
                >
                  <label className="space-y-1 text-xs">
                    <span>Nuevo horario (vacío: el mismo, si ya se liberó)</span>
                    <Input
                      type="datetime-local"
                      value={nuevoHorario}
                      onChange={(e) => setNuevoHorario(e.target.value)}
                    />
                  </label>
                  <Button type="submit" size="sm" disabled={enviando}>
                    Mover
                  </Button>
                  <Button type="button" size="sm" variant="outline" onClick={() => setMoviendo(null)}>
                    Volver
                  </Button>
                </form>
              ) : (
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" disabled={enviando} onClick={() => setMoviendo(c.reserva.id)}>
                    Mover de horario
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={enviando}
                    onClick={() => void resolver(() => conflictos.cancelar(c.reserva.id))}
                  >
                    Cancelar reserva
                  </Button>
                </div>
              )
            ) : (
              <p className="text-xs">Se resuelve desde el central, cuando haya conexión.</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
