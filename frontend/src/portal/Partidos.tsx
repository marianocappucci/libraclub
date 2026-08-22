/** «Falta uno»: partidos que buscan jugadores.
 *
 * 🔴 **El listado no trae teléfonos y la pantalla no los pide.** El servidor los
 * manda `null` a quien no juega ahí; acá no hay ninguna rama que los muestre de
 * más, y el detalle se abre sólo al entrar a un partido.
 */
import { useCallback, useEffect, useState } from 'react'
import { Users } from 'lucide-react'

import { partidos as api } from '@/lib/api'
import type { PartidoAbierto, PartidoDetalle } from '@/lib/api'
import { fecha, hora } from '@/lib/fechas'
import { useJugador } from '@/portal/JugadorContext'
import { DialogoDePartido } from '@/portal/DialogoDePartido'
import { AvisoDeError } from '@/components/listado'

const DEPORTE: Record<string, string> = {
  padel: 'Pádel', futbol: 'Fútbol', tenis: 'Tenis',
  basquet: 'Básquet', voley: 'Vóley', hockey: 'Hockey', otro: '',
}

export function Partidos() {
  const { jugador } = useJugador()
  const [filas, setFilas] = useState<PartidoAbierto[]>([])
  const [mios, setMios] = useState<PartidoDetalle[]>([])
  const [abierto, setAbierto] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  const recargar = useCallback(() => {
    if (!jugador) {
      setCargando(false)
      return
    }
    setCargando(true)
    Promise.all([api.abiertos(), api.mios()])
      .then(([a, m]) => {
        setFilas(a)
        setMios(m)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [jugador])

  useEffect(recargar, [recargar])

  if (!jugador) {
    return (
      <p className="p-6 text-muted-foreground">
        Entrá a tu cuenta para ver los partidos que buscan jugadores.
      </p>
    )
  }
  if (cargando) return <p className="p-6 text-muted-foreground">Cargando…</p>

  const anotadoEn = new Set(mios.map((m) => m.id))
  // 🔑 Una sola vez y no dos. Estaba filtrado en el `length === 0` y otra
  // vez en el `.map`, y con el filtro duplicado sacar uno de los dos no
  // cambiaba nada: el otro tapaba el defecto. Ahora el que se repetiría
  // en las dos listas se ve — un mismo partido dos veces, y uno diciendo
  // «faltan 2» cuando ya estoy adentro.
  const paraSumarse = filas.filter((f) => !anotadoEn.has(f.id))

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <h1 className="text-lg font-semibold">Falta uno</h1>
      <p className="text-sm text-muted-foreground">
        Partidos ya reservados a los que les faltan jugadores. Cuando te sumás,
        se muestran los datos para coordinar; lo que le devolvés al que pagó la
        cancha lo arreglan entre ustedes.
      </p>

      <AvisoDeError mensaje={error} />

      {mios.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium">Estás anotado en</h2>
          <ul className="space-y-2">
            {mios.map((p) => (
              <Fila
                key={p.id}
                titulo={`${fecha(p.comienza_at)} · ${hora(p.comienza_at)}`}
                subtitulo={`${p.cancha} · organiza ${p.organizador}`}
                faltan={p.faltan}
                anotado
                onAbrir={() => setAbierto(p.id)}
              />
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-medium">Buscan jugadores</h2>
        {paraSumarse.length === 0 ? (
          <p className="rounded-md border bg-card p-4 text-sm text-muted-foreground">
            No hay partidos buscando jugadores por ahora. Si reservaste una cancha
            y te falta gente, publicalo desde «Mis reservas».
          </p>
        ) : (
          <ul className="space-y-2">
            {paraSumarse.map((p) => (
                <Fila
                  key={p.id}
                  titulo={`${fecha(p.comienza_at)} · ${hora(p.comienza_at)}`}
                  subtitulo={
                    `${DEPORTE[p.deporte] || p.deporte} · ${p.cancha} · organiza ${p.organizador}` +
                    (p.nota ? ` · ${p.nota}` : '')
                  }
                  faltan={p.faltan}
                  onAbrir={() => setAbierto(p.id)}
                />
              ))}
          </ul>
        )}
      </section>

      <DialogoDePartido
        partidoId={abierto}
        onCerrar={() => setAbierto(null)}
        onCambio={recargar}
      />
    </div>
  )
}

function Fila({
  titulo, subtitulo, faltan, anotado = false, onAbrir,
}: {
  titulo: string
  subtitulo: string
  faltan: number
  anotado?: boolean
  onAbrir: () => void
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onAbrir}
        className="flex w-full items-center justify-between gap-2 rounded-lg border bg-card p-3 text-left hover:border-primary"
      >
        <span>
          <span className="block font-medium">{titulo}</span>
          <span className="block text-sm text-muted-foreground">{subtitulo}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1 text-sm">
          <Users className="size-4" />
          {anotado ? 'Anotado' : `Faltan ${faltan}`}
        </span>
      </button>
    </li>
  )
}
