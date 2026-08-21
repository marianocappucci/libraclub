import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { Plus } from 'lucide-react'

import { canchas as apiCanchas, tarifas as api } from '@/lib/api'
import type { Cancha, Tarifa } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { useSucursal } from '@/context/SucursalContext'
import { useAuth } from '@/context/AuthContext'
import { FormularioDeTarifa } from '@/components/FormularioDeTarifa'
import { AvisoDeError, columnaDeAcciones, filaInactiva } from '@/components/listado'
import { Button } from '@/components/ui/button'

const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

/** Cómo se lee el alcance de una tarifa, en castellano. */
function alcance(t: Tarifa): string {
  if (t.alcance_dia === 'feriado') return 'Feriados'
  if (t.alcance_dia === 'dia_semana') return DIAS[t.dia_semana ?? 0]
  return 'Todos los días'
}

export function Tarifas() {
  const { actual } = useSucursal()
  const { user } = useAuth()
  const [filas, setFilas] = useState<Tarifa[]>([])
  const [canchas, setCanchas] = useState<Cancha[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editando, setEditando] = useState<Tarifa | null>(null)
  const [abierto, setAbierto] = useState(false)

  // Igual que en Canchas: el backend gatea con `require_admin` y la UI no
  // ofrece botones que van a dar 403. El permiso lo decide el servidor.
  const puedeEscribir = user?.role === 'admin'

  const recargar = useCallback(() => {
    Promise.all([api.listar(), apiCanchas.listar()])
      .then(([t, c]) => {
        setFilas(t)
        setCanchas(c)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(recargar, [recargar])

  const propias = filas.filter((t) => actual === null || t.sucursal_id === actual)
  const deLaSucursal = canchas.filter((c) => actual === null || c.sucursal_id === actual)

  const nombreCancha = useCallback(
    (id: number | null) =>
      id === null ? 'Toda la sucursal' : (canchas.find((c) => c.id === id)?.nombre ?? `#${id}`),
    [canchas],
  )

  const borrar = useCallback(
    async (tarifa: Tarifa) => {
      if (!confirm(`¿Borrar la tarifa "${tarifa.nombre}"?`)) return
      setError(null)
      try {
        await api.borrar(tarifa.id)
        recargar()
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [recargar],
  )

  const columnas = useMemo<ColumnDef<Tarifa, unknown>[]>(() => {
    const base: ColumnDef<Tarifa, unknown>[] = [
      {
        accessorKey: 'nombre',
        header: sortableHeader('Nombre'),
        cell: ({ row }) => (
          <span className="font-medium">
            {row.original.nombre}
            {!row.original.activa && (
              <span className="ml-2 text-xs text-muted-foreground">(inactiva)</span>
            )}
          </span>
        ),
      },
      { id: 'alcance', header: 'Aplica', cell: ({ row }) => alcance(row.original) },
      {
        id: 'cancha',
        header: 'Cancha',
        cell: ({ row }) => nombreCancha(row.original.cancha_id),
      },
      {
        id: 'franja',
        header: 'Franja',
        cell: ({ row }) =>
          `${row.original.hora_desde.slice(0, 5)} – ${row.original.hora_hasta.slice(0, 5)}`,
      },
      {
        accessorKey: 'precio',
        header: sortableHeader('Precio'),
        cell: ({ row }) => pesos(row.original.precio),
      },
      {
        accessorKey: 'sena_porcentaje',
        header: 'Seña',
        cell: ({ row }) =>
          row.original.sena_porcentaje > 0 ? `${row.original.sena_porcentaje}%` : '—',
      },
      { accessorKey: 'prioridad', header: sortableHeader('Prioridad') },
    ]
    if (!puedeEscribir) return base
    return [
      ...base,
      columnaDeAcciones<Tarifa>({
        onEditar: (t) => {
          setEditando(t)
          setAbierto(true)
        },
        onBorrar: borrar,
        nombreDe: (t) => t.nombre,
      }),
    ]
  }, [puedeEscribir, borrar, nombreCancha])

  return (
    <div className="space-y-3">
      <EncabezadoDePantalla titulo={<h1 className="text-lg font-semibold">Tarifas</h1>}>
        {puedeEscribir && actual !== null && (
          <Button
            onClick={() => {
              setEditando(null)
              setAbierto(true)
            }}
          >
            <Plus className="size-4" />
            Nueva tarifa
          </Button>
        )}
      </EncabezadoDePantalla>

      <p className="text-sm text-muted-foreground">
        Gana la de mayor prioridad; con la misma prioridad, la más específica:
        feriado antes que día de semana, y una cancha antes que toda la sucursal.
      </p>

      <AvisoDeError mensaje={error} />

      <DataTable
        columns={columnas}
        data={propias}
        getRowClassName={(t) => filaInactiva(t.activa)}
        emptyMessage="Sin tarifas cargadas. Una franja sin tarifa no se puede reservar."
        // 🔑 Se busca sobre lo que se VE, no sobre el dato crudo: la columna
        // Cancha guarda `cancha_id: 3` y muestra "Cancha 1", y quien busca
        // escribe lo segundo. Por eso van `alcance(t)` y `nombreCancha(...)`
        // y no los campos de los que salen.
        search={{
          campos: (t) => [t.nombre, alcance(t), nombreCancha(t.cancha_id)],
          placeholder: 'Buscar por nombre, día o cancha',
          ariaLabel: 'Buscar tarifa',
        }}
      />

      {actual !== null && (
        <FormularioDeTarifa
          abierto={abierto}
          tarifa={editando}
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
