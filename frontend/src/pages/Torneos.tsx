import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { Plus, Trophy } from 'lucide-react'

import { NOMBRE_DE_DEPORTE, torneos as api } from '@/lib/api'
import type { TorneoEnLista } from '@/lib/api'
import { useSucursal } from '@/context/SucursalContext'
import { useAuth } from '@/context/AuthContext'
import { FormularioDeTorneo } from '@/components/FormularioDeTorneo'
import { EstadoDelTorneo, NOMBRE_DE_FORMATO } from '@/components/torneo'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { fecha } from '@/lib/fechas'

export function Torneos() {
  const { actual } = useSucursal()
  const { user } = useAuth()
  const navegar = useNavigate()
  const [filas, setFilas] = useState<TorneoEnLista[]>([])
  const [error, setError] = useState<string | null>(null)
  const [abierto, setAbierto] = useState(false)

  // Crear un torneo es de admin: el backend lo gatea con `require_admin`. La
  // pantalla esconde el botón en vez de mostrarlo y dejar que falle con 403.
  const puedeEscribir = user?.role === 'admin'

  const recargar = useCallback(() => {
    if (actual === null) return
    api.listar(actual).then(setFilas).catch((e: Error) => setError(e.message))
  }, [actual])

  useEffect(recargar, [recargar])

  const columnas = useMemo<ColumnDef<TorneoEnLista, unknown>[]>(
    () => [
      {
        accessorKey: 'nombre',
        header: sortableHeader('Torneo'),
        cell: ({ row }) => (
          <span>
            <span className="block font-medium">{row.original.nombre}</span>
            <span className="block text-xs text-muted-foreground">
              {NOMBRE_DE_FORMATO[row.original.formato]} · {NOMBRE_DE_DEPORTE[row.original.deporte] ?? row.original.deporte}
            </span>
          </span>
        ),
      },
      {
        accessorKey: 'desde',
        header: sortableHeader('Fecha'),
        cell: ({ row }) =>
          row.original.hasta
            ? `${fecha(row.original.desde)} al ${fecha(row.original.hasta)}`
            : fecha(row.original.desde),
      },
      {
        accessorKey: 'competidores',
        header: 'Inscriptos',
        cell: ({ row }) => row.original.competidores,
      },
      {
        id: 'avance',
        header: 'Jugados',
        // 🔑 Se calcula en el servidor y no se guarda: un contador persistido
        // hay que acordarse de mover en cada resultado, y el día que alguien se
        // olvide la lista miente. Ver `TorneoEnLista` en el backend.
        cell: ({ row }) =>
          row.original.partidos
            ? `${row.original.jugados} de ${row.original.partidos}`
            : '—',
      },
      {
        id: 'pendiente',
        header: 'Sin programar',
        cell: ({ row }) =>
          row.original.sin_programar > 0 ? (
            <span className="text-muted-foreground">
              {row.original.sin_programar} sin cancha
            </span>
          ) : (
            ''
          ),
      },
      {
        accessorKey: 'estado',
        header: 'Estado',
        cell: ({ row }) => (
          <span className="flex items-center gap-2">
            <EstadoDelTorneo torneo={row.original} />
            {row.original.campeon && (
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <Trophy className="size-3" />
                {row.original.campeon}
              </span>
            )}
          </span>
        ),
      },
    ],
    [],
  )

  return (
    <div className="space-y-3">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={Trophy}>Torneos</TituloPantalla>}>
        {puedeEscribir && actual !== null && (
          <Button onClick={() => setAbierto(true)}>
            <Plus className="size-4" />
            Nuevo torneo
          </Button>
        )}
      </EncabezadoDePantalla>

      <AvisoDeError mensaje={error} />

      <DataTable
        columns={columnas}
        data={filas}
        // La fila entera abre el torneo: el detalle es todo lo que hay para
        // hacer con él, así que una columna de acciones con un solo botón sería
        // ruido.
        onRowClick={(t: TorneoEnLista) => navegar(`/torneos/${t.id}`)}
        getRowClassName={(t: TorneoEnLista) =>
          t.estado === 'cancelado' ? 'opacity-50' : undefined
        }
        emptyMessage="Esta sucursal todavía no tiene torneos."
        search={{
          campos: (t: TorneoEnLista) => [t.nombre, t.deporte, t.campeon],
          placeholder: 'Buscar por nombre, deporte o campeón',
          ariaLabel: 'Buscar torneo',
        }}
      />

      {actual !== null && (
        <FormularioDeTorneo
          abierto={abierto}
          sucursalId={actual}
          onCerrar={() => setAbierto(false)}
          onCreado={(torneo) => {
            setAbierto(false)
            // Directo al detalle: lo primero que hay que hacer con un torneo
            // recién creado es inscribir, y está ahí adentro.
            navegar(`/torneos/${torneo.id}`)
          }}
        />
      )}
    </div>
  )
}
