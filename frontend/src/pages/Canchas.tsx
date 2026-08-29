import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { LayoutGrid, Plus } from 'lucide-react'

import { canchas as api, NOMBRE_DE_DEPORTE } from '@/lib/api'
import type { Cancha } from '@/lib/api'
import { useSucursal } from '@/context/SucursalContext'
import { useAuth } from '@/context/AuthContext'
import { FormularioDeCancha } from '@/components/FormularioDeCancha'
import { AvisoDeError, columnaDeAcciones, filaInactiva } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

export function Canchas() {
  const { actual } = useSucursal()
  const { user } = useAuth()
  const [filas, setFilas] = useState<Cancha[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editando, setEditando] = useState<Cancha | null>(null)
  const [abierto, setAbierto] = useState(false)

  // 🔴 El alta, la edición y la baja de canchas son de **admin**: el backend las
  // gatea con `require_admin`. La UI esconde los botones en vez de mostrarlos y
  // dejar que fallen con 403 — un botón que siempre da error es peor que no
  // tenerlo. Lo que la UI **no** hace es decidir el permiso: si esta condición
  // se equivocara, el servidor sigue rechazando igual.
  const puedeEscribir = user?.role === 'admin'

  const recargar = useCallback(() => {
    api.listar().then(setFilas).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(recargar, [recargar])

  const propias = filas.filter((c) => actual === null || c.sucursal_id === actual)

  const borrar = useCallback(
    async (cancha: Cancha) => {
      if (!confirm(`¿Borrar ${cancha.nombre}? Si tiene reservas no se va a poder.`)) return
      setError(null)
      try {
        await api.borrar(cancha.id)
        recargar()
      } catch (e) {
        // El 409 del backend ya explica qué hacer —darla de baja en vez de
        // borrarla— porque la FK de reservas es RESTRICT y no CASCADE. Se
        // muestra tal cual viene.
        setError((e as Error).message)
      }
    },
    [recargar],
  )

  const columnas = useMemo<ColumnDef<Cancha, unknown>[]>(() => {
    const base: ColumnDef<Cancha, unknown>[] = [
      {
        accessorKey: 'nombre',
        header: sortableHeader('Nombre'),
        cell: ({ row }) => (
          <span className="font-medium">
            {row.original.nombre}
            {!row.original.activa && (
              <span className="ml-2 text-xs text-muted-foreground">(de baja)</span>
            )}
          </span>
        ),
      },
      {
        accessorKey: 'deporte',
        header: sortableHeader('Deporte'),
        cell: ({ row }) =>
          NOMBRE_DE_DEPORTE[row.original.deporte] ?? row.original.deporte,
      },
      {
        accessorKey: 'duracion_turno_min',
        header: sortableHeader('Turno'),
        cell: ({ row }) => `${row.original.duracion_turno_min} min`,
      },
      {
        accessorKey: 'techada',
        header: 'Techada',
        cell: ({ row }) => (row.original.techada ? 'Sí' : 'No'),
      },
      {
        accessorKey: 'activa',
        header: 'Estado',
        cell: ({ row }) => (row.original.activa ? 'Activa' : 'De baja'),
      },
    ]
    if (!puedeEscribir) return base
    return [
      ...base,
      columnaDeAcciones<Cancha>({
        onEditar: (c) => {
          setEditando(c)
          setAbierto(true)
        },
        onBorrar: borrar,
        nombreDe: (c) => c.nombre,
      }),
    ]
  }, [puedeEscribir, borrar])

  return (
    <div className="space-y-3">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={LayoutGrid}>Canchas</TituloPantalla>}>
        {puedeEscribir && actual !== null && (
          <Button
            onClick={() => {
              setEditando(null)
              setAbierto(true)
            }}
          >
            <Plus className="size-4" />
            Nueva cancha
          </Button>
        )}
      </EncabezadoDePantalla>

      <AvisoDeError mensaje={error} />

      <DataTable
        columns={columnas}
        data={propias}
        getRowClassName={(c) => filaInactiva(c.activa)}
        emptyMessage="Esta sucursal todavía no tiene canchas."
        search={{
          campos: (c) => [c.nombre, c.deporte, c.superficie],
          placeholder: 'Buscar por nombre, deporte o superficie',
          ariaLabel: 'Buscar cancha',
        }}
      />

      {actual !== null && (
        <FormularioDeCancha
          abierto={abierto}
          cancha={editando}
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
