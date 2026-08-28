import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Dices, Plus, Swords, Trash2, Trophy } from 'lucide-react'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import { canchas as apiCanchas, NOMBRE_DE_DEPORTE, torneos as api } from '@/lib/api'
import type {
  Cancha, Competidor, Fixture as DatosDelFixture, PartidoDeTorneo, TablaDeZona, Torneo as UnTorneo,
} from '@/lib/api'
import { useAuth } from '@/context/AuthContext'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Fixture } from '@/components/Fixture'
import { TablaDePosiciones } from '@/components/TablaDePosiciones'
import { FormularioDeCompetidor } from '@/components/FormularioDeCompetidor'
import { DialogoDePartidoDeTorneo } from '@/components/DialogoDePartidoDeTorneo'
import { EstadoDelTorneo, NOMBRE_DE_FORMATO } from '@/components/torneo'
import { fecha } from '@/lib/fechas'

export function Torneo() {
  const { id } = useParams()
  const torneoId = Number(id)
  const { user } = useAuth()
  const esAdmin = user?.role === 'admin'

  const [torneo, setTorneo] = useState<UnTorneo | null>(null)
  const [competidores, setCompetidores] = useState<Competidor[]>([])
  const [fixture, setFixture] = useState<DatosDelFixture>({ rondas: 0, partidos: [] })
  const [tablas, setTablas] = useState<TablaDeZona[]>([])
  const [canchas, setCanchas] = useState<Cancha[]>([])
  const [abierto, setAbierto] = useState<PartidoDeTorneo | null>(null)
  const [inscribiendo, setInscribiendo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  const recargar = useCallback(() => {
    if (!torneoId) return
    Promise.all([
      api.ver(torneoId),
      api.competidores(torneoId),
      api.fixture(torneoId),
      api.posiciones(torneoId),
    ])
      .then(([t, c, f, p]) => {
        setTorneo(t)
        setCompetidores(c)
        setFixture(f)
        setTablas(p)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [torneoId])

  useEffect(recargar, [recargar])
  useEffect(() => {
    apiCanchas.listar().then(setCanchas).catch(() => setCanchas([]))
  }, [])

  if (cargando) return <p className="p-6 text-muted-foreground">Cargando…</p>
  if (!torneo) {
    return (
      <div className="space-y-3 p-6">
        <AvisoDeError mensaje={error ?? 'No se encontró ese torneo.'} />
        <Link to="/torneos" className="text-sm underline">Volver a torneos</Link>
      </div>
    )
  }

  const jugados = fixture.partidos.filter((p) => p.finalizado).length
  const propias = canchas.filter((c) => c.sucursal_id === torneo.sucursal_id && c.activa)
  // El playoff se puede largar cuando terminaron todos los partidos de grupos y
  // todavía no hay llaves. El backend lo valida igual; acá sólo decide si el
  // botón se ofrece.
  const grupos = fixture.partidos.filter((p) => p.etapa === 'grupos')
  const puedeLargarPlayoff =
    torneo.formato === 'zonas' &&
    torneo.estado === 'sorteado' &&
    grupos.length > 0 &&
    grupos.every((p) => p.finalizado) &&
    !fixture.partidos.some((p) => p.etapa === 'llaves')

  async function accion(fn: () => Promise<unknown>) {
    setError(null)
    try {
      await fn()
      recargar()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Link
          to="/torneos"
          className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Torneos
        </Link>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            {/* El mismo icono que la entrada «Torneos» del sidebar: el icono
                del título es lo que confirma dónde estás parado, y el detalle
                sigue siendo esa sección. Lo sostiene el guard de
                `titulos-con-icono`. */}
            <TituloPantalla icono={Trophy}>
              {torneo.nombre}
              <EstadoDelTorneo torneo={{ estado: torneo.estado, jugados }} />
            </TituloPantalla>
            <p className="text-sm text-muted-foreground">
              {NOMBRE_DE_FORMATO[torneo.formato]} · {NOMBRE_DE_DEPORTE[torneo.deporte] ?? torneo.deporte} ·{' '}
              {fecha(torneo.desde)}
              {torneo.hasta ? ` al ${fecha(torneo.hasta)}` : ''}
              {torneo.semilla !== null && (
                <>
                  {' · '}
                  {/* 🔑 La semilla a la vista: con ella y la lista de
                      inscriptos, cualquiera reproduce el sorteo. Es lo que
                      convierte «salió así» en algo verificable. */}
                  <span title="Con este número el sorteo se puede reproducir">
                    sorteo #{torneo.semilla}
                  </span>
                </>
              )}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            {torneo.estado === 'armado' && (
              <>
                <Button variant="outline" onClick={() => setInscribiendo(true)}>
                  <Plus className="size-4" />
                  Inscribir
                </Button>
                {esAdmin && (
                  <Button
                    disabled={competidores.length < 2}
                    onClick={() => {
                      if (
                        !confirm(
                          `Sortear ${torneo.nombre} con ${competidores.length} ` +
                            'competidores. Después no se pueden agregar ni sacar.',
                        )
                      )
                        return
                      accion(() => api.sortear(torneo.id))
                    }}
                  >
                    <Dices className="size-4" />
                    Sortear
                  </Button>
                )}
              </>
            )}
            {puedeLargarPlayoff && esAdmin && (
              <Button onClick={() => accion(() => api.playoff(torneo.id))}>
                <Swords className="size-4" />
                Largar el playoff
              </Button>
            )}
            {esAdmin && torneo.estado !== 'cancelado' && (
              <Button
                variant="outline"
                onClick={() => {
                  if (
                    !confirm(
                      'Cancelar el torneo libera todas las canchas que tenía ' +
                        'tomadas. No se puede deshacer.',
                    )
                  )
                    return
                  accion(() => api.cancelar(torneo.id))
                }}
              >
                Cancelar torneo
              </Button>
            )}
          </div>
        </div>
      </div>

      <AvisoDeError mensaje={error} />

      <Tabs defaultValue={torneo.estado === 'armado' ? 'competidores' : 'fixture'}>
        <TabsList>
          <TabsTrigger value="competidores">
            Competidores ({competidores.length})
          </TabsTrigger>
          <TabsTrigger value="fixture">Fixture</TabsTrigger>
          {/* La pestaña de posiciones sólo existe si hay tabla. En un cuadro de
              eliminación no hay nada que mostrar ahí, y una pestaña vacía hace
              que el encargado la abra buscando algo. */}
          {tablas.length > 0 && <TabsTrigger value="posiciones">Posiciones</TabsTrigger>}
        </TabsList>

        <TabsContent value="competidores" className="pt-3">
          <Competidores
            competidores={competidores}
            editable={torneo.estado === 'armado'}
            onBajar={(competidor) => {
              if (!confirm(`¿Sacar a ${competidor.nombre} del torneo?`)) return
              accion(() => api.bajar(competidor.id))
            }}
          />
        </TabsContent>

        <TabsContent value="fixture" className="pt-3">
          <Fixture fixture={fixture} onAbrir={setAbierto} />
        </TabsContent>

        {tablas.length > 0 && (
          <TabsContent value="posiciones" className="pt-3">
            <TablaDePosiciones
              tablas={tablas}
              clasifican={torneo.clasifican_por_zona}
            />
          </TabsContent>
        )}
      </Tabs>

      <FormularioDeCompetidor
        abierto={inscribiendo}
        torneoId={torneo.id}
        deporte={torneo.deporte}
        onCerrar={() => setInscribiendo(false)}
        onInscripto={recargar}
      />
      <DialogoDePartidoDeTorneo
        partido={abierto}
        torneo={torneo}
        canchas={propias}
        onCerrar={() => setAbierto(null)}
        onCambio={recargar}
      />
    </div>
  )
}

function Competidores({
  competidores,
  editable,
  onBajar,
}: {
  competidores: Competidor[]
  editable: boolean
  onBajar: (competidor: Competidor) => void
}) {
  if (!competidores.length) {
    return (
      <p className="rounded-md border bg-card p-4 text-sm text-muted-foreground">
        Todavía no hay inscriptos. Cargalos antes de sortear.
      </p>
    )
  }
  return (
    <ul className="space-y-2">
      {competidores.map((competidor) => (
        <li
          key={competidor.id}
          className="flex items-start justify-between gap-2 rounded-lg border bg-card p-3"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              {competidor.siembra !== null && (
                <span
                  className="flex size-5 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-medium"
                  title={`Cabeza de serie ${competidor.siembra}`}
                >
                  {competidor.siembra}
                </span>
              )}
              <span className="truncate font-medium">{competidor.nombre}</span>
              {competidor.zona && (
                <span className="shrink-0 text-xs text-muted-foreground">
                  {competidor.zona}
                </span>
              )}
            </div>
            {competidor.integrantes.length > 0 && (
              <p className="truncate text-xs text-muted-foreground">
                {competidor.integrantes
                  .map((i) => (i.telefono ? `${i.nombre} (${i.telefono})` : i.nombre))
                  .join(' · ')}
              </p>
            )}
          </div>
          {editable && (
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Sacar a ${competidor.nombre}`}
              onClick={() => onBajar(competidor)}
            >
              <Trash2 className="size-4" />
            </Button>
          )}
        </li>
      ))}
      {!editable && (
        <li className="flex items-center gap-2 text-xs text-muted-foreground">
          <Trophy className="size-3" />
          El torneo ya está sorteado: los competidores no se tocan más.
        </li>
      )}
    </ul>
  )
}
