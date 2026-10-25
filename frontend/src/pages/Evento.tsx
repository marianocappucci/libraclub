import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Pencil, Plus, Trophy } from 'lucide-react'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import { canchas as apiCanchas, eventos as api } from '@/lib/api'
import type { Cancha, EventoConCategorias } from '@/lib/api'
import { useAuth } from '@/context/AuthContext'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { FormularioDeEvento } from '@/components/FormularioDeEvento'
import { FormularioDeTorneo } from '@/components/FormularioDeTorneo'
import { EstadoDelTorneo, comoSeJuega, nombreDelFormato } from '@/components/torneo'
import { fecha } from '@/lib/fechas'

/** Un evento: las categorías de un campeonato con sus fechas y sus canchas.
 *
 * Cada categoría es un torneo completo —con sus zonas, su grilla y su
 * campeón—; esta pantalla las junta para ver de un vistazo cómo va cada una. */
export function Evento() {
  const { id } = useParams()
  const eventoId = Number(id)
  const { user } = useAuth()
  const esAdmin = user?.role === 'admin'

  const [evento, setEvento] = useState<EventoConCategorias | null>(null)
  const [canchas, setCanchas] = useState<Cancha[]>([])
  const [editando, setEditando] = useState(false)
  const [agregando, setAgregando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  const recargar = useCallback(() => {
    if (!eventoId) return
    api
      .ver(eventoId)
      .then(setEvento)
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [eventoId])

  useEffect(recargar, [recargar])
  useEffect(() => {
    apiCanchas.listar().then(setCanchas).catch(() => setCanchas([]))
  }, [])

  if (cargando) return <p className="text-muted-foreground">Cargando…</p>
  if (!evento) {
    return (
      <div className="space-y-3">
        <AvisoDeError mensaje={error ?? 'No se encontró ese evento.'} />
        <Link to="/torneos" className="text-sm underline">Volver a torneos</Link>
      </div>
    )
  }

  const propias = canchas.filter((c) => c.sucursal_id === evento.sucursal_id && c.activa)
  const delEvento = propias.filter((c) => evento.cancha_ids.includes(c.id))

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
            <TituloPantalla icono={Trophy}>{evento.nombre}</TituloPantalla>
            <p className="text-sm text-muted-foreground">
              {fecha(evento.desde)}
              {evento.hasta ? ` al ${fecha(evento.hasta)}` : ''} ·{' '}
              {delEvento.length
                ? delEvento.map((c) => c.nombre).join(', ')
                : 'Cualquier cancha de la sucursal'}
            </p>
          </div>
          {esAdmin && (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => setEditando(true)}>
                <Pencil className="size-4" />
                Editar
              </Button>
              <Button onClick={() => setAgregando(true)}>
                <Plus className="size-4" />
                Nueva categoría
              </Button>
            </div>
          )}
        </div>
      </div>

      <AvisoDeError mensaje={error} />

      {evento.categorias.length === 0 ? (
        <p className="rounded-md border bg-card p-4 text-sm text-muted-foreground">
          Este evento todavía no tiene categorías.
          {esAdmin && ' Creá la primera: hereda las fechas y las canchas del evento.'}
        </p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {evento.categorias.map((categoria) => (
            <li key={categoria.id}>
              <Link
                to={`/torneos/${categoria.id}`}
                className="block h-full space-y-2 rounded-lg border bg-card p-3 hover:border-primary"
              >
                <div className="flex items-start justify-between gap-2">
                  <h2 className="font-semibold">{categoria.categoria}</h2>
                  <EstadoDelTorneo torneo={categoria} />
                </div>
                <p className="text-xs text-muted-foreground">
                  {nombreDelFormato(categoria)} · {comoSeJuega(categoria)}
                </p>
                <p className="text-sm">
                  {categoria.competidores} {categoria.competidores === 1 ? 'pareja' : 'parejas'}
                  {categoria.partidos > 0 && (
                    <span className="text-muted-foreground">
                      {' '}· {categoria.jugados} de {categoria.partidos} jugados
                    </span>
                  )}
                </p>
                {categoria.campeon && (
                  <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                    <Trophy className="mt-0.5 size-3 shrink-0" />
                    {categoria.campeon}
                  </p>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}

      <FormularioDeEvento
        abierto={editando}
        sucursalId={evento.sucursal_id}
        canchas={propias}
        evento={evento}
        onCerrar={() => setEditando(false)}
        onGuardado={() => {
          setEditando(false)
          recargar()
        }}
      />
      <FormularioDeTorneo
        abierto={agregando}
        sucursalId={evento.sucursal_id}
        evento={evento}
        onCerrar={() => setAgregando(false)}
        onCreado={() => {
          setAgregando(false)
          recargar()
        }}
      />
    </div>
  )
}
