import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { MapPin, Plus } from 'lucide-react'

import { sucursales as api } from '@/lib/api'
import type { Sucursal } from '@/lib/api'
import { useSucursal } from '@/context/SucursalContext'
import { useAuth } from '@/context/AuthContext'
import { FormularioDeSucursal } from '@/components/FormularioDeSucursal'
import { AvisoDeError, columnaDeAcciones, filaInactiva } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

export function Sucursales() {
  // 🔴 Esta pantalla pide su **propia** lista, completa, y no usa la del
  // contexto. La del contexto está filtrada a las activas porque alimenta el
  // selector del menú — y con esa lista, una sucursal dada de baja desaparece
  // de acá y **no hay forma de volver a activarla**. Encontrado usándolo: se
  // dio de baja la que se estaba viendo y dejó de existir para la UI. El
  // `recargar` del contexto se sigue llamando, para que el selector se entere
  // de los cambios.
  const { actual, recargar: recargarSelector } = useSucursal()
  const { user } = useAuth()
  const [filas, setFilas] = useState<Sucursal[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editando, setEditando] = useState<Sucursal | null>(null)
  const [abierto, setAbierto] = useState(false)

  const puedeEscribir = user?.role === 'admin'

  const recargar = useCallback(() => {
    api.listar().then(setFilas).catch((e: Error) => setError(e.message))
    recargarSelector()
  }, [recargarSelector])

  useEffect(recargar, [recargar])

  const borrar = useCallback(
    async (sucursal: Sucursal) => {
      if (!confirm(`¿Borrar ${sucursal.nombre}? Si tiene canchas no se va a poder.`)) return
      setError(null)
      try {
        await api.borrar(sucursal.id)
        recargar()
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [recargar],
  )

  const columnas = useMemo<ColumnDef<Sucursal, unknown>[]>(() => {
    const base: ColumnDef<Sucursal, unknown>[] = [
      {
        accessorKey: 'nombre',
        header: sortableHeader('Nombre'),
        cell: ({ row }) => (
          <span className="font-medium">
            {row.original.nombre}
            {row.original.id === actual && (
              <span className="ml-2 text-xs text-muted-foreground">(la que estás viendo)</span>
            )}
            {!row.original.activa && (
              <span className="ml-2 text-xs text-muted-foreground">(de baja)</span>
            )}
          </span>
        ),
      },
      {
        accessorKey: 'localidad',
        header: sortableHeader('Localidad'),
        cell: ({ row }) => row.original.localidad ?? '—',
      },
      {
        accessorKey: 'telefono',
        header: 'Teléfono',
        cell: ({ row }) => row.original.telefono ?? '—',
      },
      {
        accessorKey: 'punto_venta_arca',
        header: 'Punto de venta',
        cell: ({ row }) =>
          row.original.punto_venta_arca ?? (
            // No es lo mismo "no tiene" que "tiene el 0": sin punto de venta la
            // sucursal no puede facturar, y conviene que se vea.
            <span className="text-amber-700 dark:text-amber-500">sin asignar</span>
          ),
      },
    ]
    if (!puedeEscribir) return base
    return [
      ...base,
      columnaDeAcciones<Sucursal>({
        onEditar: (s) => {
          setEditando(s)
          setAbierto(true)
        },
        onBorrar: borrar,
        nombreDe: (s) => s.nombre,
      }),
    ]
  }, [puedeEscribir, borrar, actual])

  return (
    <div className="space-y-3">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={MapPin}>Sucursales</TituloPantalla>}>
        {puedeEscribir && (
          <Button
            onClick={() => {
              setEditando(null)
              setAbierto(true)
            }}
          >
            <Plus className="size-4" />
            Nueva sucursal
          </Button>
        )}
      </EncabezadoDePantalla>

      <p className="text-sm text-muted-foreground">
        Una sucursal no es un cliente aparte: comparten base, usuarios y
        reportes. Un complejo que factura con otro CUIT va en otra instancia.
      </p>

      <AvisoDeError mensaje={error} />

      <DataTable
        columns={columnas}
        data={filas}
        getRowClassName={(s) => filaInactiva(s.activa)}
        emptyMessage="No hay ninguna sucursal. Sin una, la agenda no tiene dónde vivir."
        search={{
          campos: (s) => [s.nombre, s.localidad, s.telefono, s.punto_venta_arca],
          placeholder: 'Buscar por nombre, localidad o teléfono',
          ariaLabel: 'Buscar sucursal',
        }}
      />

      <FormularioDeSucursal
        abierto={abierto}
        sucursal={editando}
        onCerrar={() => setAbierto(false)}
        onGuardada={() => {
          setAbierto(false)
          recargar()
        }}
      />
    </div>
  )
}
