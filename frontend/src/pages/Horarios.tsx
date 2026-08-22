/** El horario de atención: qué turnos existen y cuáles no se ofrecen.
 *
 * 🔴 **Sin ninguna franja cargada rige 8:00 a 00:00**, que es lo que el producto
 * tenía hardcodeado antes de que esta pantalla existiera. Se dice en un cartel y
 * no en la documentación: un complejo que abre a las 16 y nunca entró acá está
 * ofreciendo ocho horas de turnos que no da, y no tiene cómo enterarse.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { Clock, Plus } from 'lucide-react'

import { canchas as apiCanchas, horarios as api } from '@/lib/api'
import type { Cancha, Franja } from '@/lib/api'
import { useSucursal } from '@/context/SucursalContext'
import { useAuth } from '@/context/AuthContext'
import { FormularioDeHorario } from '@/components/FormularioDeHorario'
import { AvisoDeError, columnaDeAcciones, filaInactiva } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

function alcance(f: Franja): string {
  if (f.alcance_dia === 'feriado') return 'Feriados'
  if (f.alcance_dia === 'dia_semana') return DIAS[f.dia_semana ?? 0]
  return 'Todos los días'
}

/** `16:00 – 02:00 (+1)`. El `(+1)` es lo que evita que se lea como un error. */
export function rango(f: Franja): string {
  const abre = f.abre.slice(0, 5)
  const cierra = f.cierra.slice(0, 5)
  return cierra <= abre ? `${abre} – ${cierra} (+1)` : `${abre} – ${cierra}`
}

export function Horarios() {
  const { actual } = useSucursal()
  const { user } = useAuth()
  const [filas, setFilas] = useState<Franja[]>([])
  const [canchas, setCanchas] = useState<Cancha[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editando, setEditando] = useState<Franja | null>(null)
  const [abierto, setAbierto] = useState(false)

  const puedeEscribir = user?.role === 'admin'

  const recargar = useCallback(() => {
    Promise.all([api.listar(), apiCanchas.listar()])
      .then(([h, c]) => {
        setFilas(h)
        setCanchas(c)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(recargar, [recargar])

  const propias = filas.filter((f) => actual === null || f.sucursal_id === actual)
  const deLaSucursal = canchas.filter((c) => actual === null || c.sucursal_id === actual)

  const nombreCancha = useCallback(
    (id: number | null) =>
      id === null ? 'Toda la sucursal' : (canchas.find((c) => c.id === id)?.nombre ?? `#${id}`),
    [canchas],
  )

  const borrar = useCallback(
    async (franja: Franja) => {
      if (!confirm(`¿Borrar el horario ${rango(franja)} de ${alcance(franja).toLowerCase()}?`))
        return
      setError(null)
      try {
        await api.borrar(franja.id)
        recargar()
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [recargar],
  )

  const columnas = useMemo<ColumnDef<Franja, unknown>[]>(() => {
    const base: ColumnDef<Franja, unknown>[] = [
      {
        id: 'alcance',
        header: 'Aplica',
        cell: ({ row }) => (
          <span className="font-medium">
            {alcance(row.original)}
            {!row.original.activa && (
              <span className="ml-2 text-xs text-muted-foreground">(inactivo)</span>
            )}
          </span>
        ),
      },
      {
        id: 'cancha',
        header: 'Cancha',
        cell: ({ row }) => nombreCancha(row.original.cancha_id),
      },
      { id: 'rango', header: sortableHeader('Horario'), cell: ({ row }) => rango(row.original) },
    ]
    if (!puedeEscribir) return base
    return [
      ...base,
      columnaDeAcciones<Franja>({
        onEditar: (f) => {
          setEditando(f)
          setAbierto(true)
        },
        onBorrar: borrar,
        nombreDe: (f) => `${alcance(f)} ${rango(f)}`,
      }),
    ]
  }, [puedeEscribir, borrar, nombreCancha])

  return (
    <div className="space-y-3">
      <EncabezadoDePantalla
        titulo={<TituloPantalla icono={Clock}>Horario de atención</TituloPantalla>}
      >
        {puedeEscribir && actual !== null && (
          <Button
            onClick={() => {
              setEditando(null)
              setAbierto(true)
            }}
          >
            <Plus className="size-4" />
            Nuevo horario
          </Button>
        )}
      </EncabezadoDePantalla>

      <p className="text-sm text-muted-foreground">
        La agenda sólo ofrece turnos dentro de estas franjas, y una reserva fuera
        de horario no se puede cargar. Se puede abrir dos veces el mismo día
        —mañana y tarde— cargando dos franjas. Gana la más específica: feriado
        antes que día de semana, y una cancha antes que toda la sucursal.
      </p>

      {propias.length === 0 && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          <span className="font-medium">Esta sucursal no tiene horario cargado.</span>{' '}
          Mientras tanto la agenda ofrece turnos de <strong>08:00 a 00:00, todos
          los días</strong>. Si el complejo abre en otro horario, cargalo acá:
          hasta entonces se están ofreciendo turnos que no se dan.
        </div>
      )}

      <AvisoDeError mensaje={error} />

      <DataTable
        columns={columnas}
        data={propias}
        getRowClassName={(f) => filaInactiva(f.activa)}
        emptyMessage="Sin horarios cargados. Rige 08:00 a 00:00 todos los días."
        search={{
          campos: (f) => [alcance(f), nombreCancha(f.cancha_id), rango(f)],
          placeholder: 'Buscar por día, cancha u horario',
          ariaLabel: 'Buscar horario',
        }}
      />

      {actual !== null && (
        <FormularioDeHorario
          abierto={abierto}
          franja={editando}
          canchas={deLaSucursal}
          sucursalId={actual}
          onCerrar={() => setAbierto(false)}
          onGuardada={() => {
            setAbierto(false)
            recargar()
          }}
        />
      )}
    </div>
  )
}
