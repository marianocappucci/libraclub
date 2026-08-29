/** Un partido del torneo: cancha, horario y resultado.
 *
 * Los dos en el mismo diálogo porque son lo que se hace con un partido, y
 * separarlos obligaría a abrir dos veces la misma tarjeta.
 */
import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

import { torneos as api } from '@/lib/api'
import type { Cancha, PartidoDeTorneo, Torneo } from '@/lib/api'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { diaISO, fecha, hora } from '@/lib/fechas'
import { nombreDe } from '@/components/torneo'

/** Un parcial en carga. Texto y no número: un campo numérico vacío es `NaN`, y
 *  el operador tiene que poder borrarlo para escribir de nuevo. */
type Parcial = { a: string; b: string }

export function DialogoDePartidoDeTorneo({
  partido,
  torneo,
  canchas,
  onCerrar,
  onCambio,
}: {
  partido: PartidoDeTorneo | null
  torneo: Torneo
  canchas: Cancha[]
  onCerrar: () => void
  onCambio: () => void
}) {
  const [canchaId, setCanchaId] = useState(0)
  const [dia, setDia] = useState('')
  const [desde, setDesde] = useState('20:00')
  const [parciales, setParciales] = useState<Parcial[]>([])
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!partido) return
    setError(null)
    setCanchaId(canchas[0]?.id ?? 0)
    setDia(partido.comienza_at ? diaISO(partido.comienza_at) : torneo.desde)
    setDesde(partido.comienza_at ? hora(partido.comienza_at) : '20:00')
    setParciales(
      partido.parciales.length
        ? partido.parciales.map((p) => ({ a: String(p.puntos_a), b: String(p.puntos_b) }))
        : // Arranca con los parciales mínimos del torneo: en un pádel al mejor
          // de tres son dos, y el tercero se agrega si hizo falta jugarlo.
          Array.from({ length: torneo.sets_para_ganar }, () => ({ a: '', b: '' })),
    )
  }, [partido, canchas, torneo])

  if (!partido) return null

  const sinRivales = !partido.competidor_a_id || !partido.competidor_b_id

  async function accion(fn: () => Promise<unknown>) {
    setError(null)
    setEnviando(true)
    try {
      await fn()
      onCambio()
      onCerrar()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{partido.instancia}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 text-sm">
          <div className="rounded-md border bg-card p-3">
            <div className="font-medium">{nombreDe(partido.competidor_a)}</div>
            <div className="text-xs text-muted-foreground">contra</div>
            <div className="font-medium">{nombreDe(partido.competidor_b)}</div>
            {partido.comienza_at && (
              <div className="mt-2 text-xs text-muted-foreground">
                {fecha(partido.comienza_at)} · {hora(partido.comienza_at)} ·{' '}
                {partido.cancha}
              </div>
            )}
          </div>

          {sinRivales ? (
            // 🔑 No se ofrece nada: sin los dos rivales no se puede cargar un
            // resultado, y darle cancha a un cruce que no se sabe quién juega
            // ocuparía el turno para nada.
            <p className="text-muted-foreground">
              Falta que se definan los ganadores de la ronda anterior.
            </p>
          ) : (
            <>
              <section className="space-y-2">
                <h3 className="font-medium">Cancha y horario</h3>
                <div className="grid grid-cols-3 gap-2">
                  <select
                    className="h-9 rounded-md border bg-transparent px-2"
                    value={canchaId}
                    onChange={(e) => setCanchaId(Number(e.target.value))}
                  >
                    {canchas.map((c) => (
                      <option key={c.id} value={c.id}>{c.nombre}</option>
                    ))}
                  </select>
                  <Input type="date" value={dia} onChange={(e) => setDia(e.target.value)} />
                  <Input
                    type="time"
                    value={desde}
                    onChange={(e) => setDesde(e.target.value)}
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    disabled={enviando || partido.finalizado || !dia}
                    onClick={() =>
                      accion(() =>
                        api.programar(partido.id, {
                          cancha_id: canchaId,
                          // 🔴 Sin offset: el backend lo lee como hora **del
                          // complejo**. Mandar un ISO con la zona del navegador
                          // movería el partido si alguien carga desde otro huso.
                          comienza_at: `${dia}T${desde}:00`,
                        }),
                      )
                    }
                  >
                    {partido.comienza_at ? 'Mover' : 'Dar cancha'}
                  </Button>
                  {partido.reserva_id && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={enviando}
                      onClick={() => accion(() => api.liberar(partido.id))}
                    >
                      Liberar la cancha
                    </Button>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  Darle cancha ocupa ese turno en la agenda: nadie va a poder
                  alquilarla a esa hora.
                </p>
              </section>

              <section className="space-y-2">
                <h3 className="font-medium">Resultado</h3>
                {parciales.map((parcial, indice) => (
                  <div key={indice} className="flex items-center gap-2">
                    <span className="w-6 text-xs text-muted-foreground">
                      {torneo.sets_para_ganar === 1 ? '' : `${indice + 1}º`}
                    </span>
                    <Input
                      inputMode="numeric"
                      aria-label={`${nombreDe(partido.competidor_a)}, parcial ${indice + 1}`}
                      value={parcial.a}
                      onChange={(e) =>
                        setParciales((l) =>
                          l.map((p, n) => (n === indice ? { ...p, a: e.target.value } : p)),
                        )
                      }
                    />
                    <Input
                      inputMode="numeric"
                      aria-label={`${nombreDe(partido.competidor_b)}, parcial ${indice + 1}`}
                      value={parcial.b}
                      onChange={(e) =>
                        setParciales((l) =>
                          l.map((p, n) => (n === indice ? { ...p, b: e.target.value } : p)),
                        )
                      }
                    />
                  </div>
                ))}
                {/* Sólo hasta el máximo que puede durar el partido: en un al
                    mejor de tres, cuatro sets no existen y el backend los
                    rechaza. Mejor no ofrecer el botón que dar un 422. */}
                {parciales.length < torneo.sets_para_ganar * 2 - 1 && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setParciales((l) => [...l, { a: '', b: '' }])}
                  >
                    Agregar parcial
                  </Button>
                )}
                <div className="flex flex-wrap justify-end gap-2">
                  {partido.finalizado && (
                    <Button
                      variant="outline"
                      disabled={enviando}
                      onClick={() => accion(() => api.borrarResultado(partido.id))}
                    >
                      Borrar el resultado
                    </Button>
                  )}
                  <Button
                    disabled={enviando || parciales.some((p) => !p.a || !p.b)}
                    onClick={() =>
                      accion(() =>
                        api.cargarResultado(
                          partido.id,
                          parciales.map((p) => ({
                            puntos_a: Number(p.a),
                            puntos_b: Number(p.b),
                          })),
                        ),
                      )
                    }
                  >
                    {partido.finalizado ? 'Corregir' : 'Guardar resultado'}
                  </Button>
                </div>
              </section>
            </>
          )}

          <AvisoDeError mensaje={error} />

          <div className="flex justify-end">
            <Button variant="ghost" onClick={onCerrar}>Cerrar</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
