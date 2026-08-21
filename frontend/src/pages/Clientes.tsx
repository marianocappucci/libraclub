import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { Plus } from 'lucide-react'

import { clientes as api } from '@/lib/api'
import type { Cliente } from '@/lib/api'
import { useAuth } from '@/context/AuthContext'
import { FormularioDeCliente } from '@/components/FormularioDeCliente'
import { AvisoDeError, columnaDeAcciones, filaInactiva } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'

export function Clientes() {
  const { user } = useAuth()
  const [filas, setFilas] = useState<Cliente[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editando, setEditando] = useState<Cliente | null>(null)
  const [abierto, setAbierto] = useState(false)
  const [verInactivos, setVerInactivos] = useState(false)

  // 🔑 Clientes es el ÚNICO maestro que un encargado puede escribir. El backend
  // lo gatea con `require_staff` y no con `require_admin`: si pidiera admin, no
  // se le podría tomar la reserva a alguien que llama por primera vez.
  const puedeEscribir = user?.role === 'admin' || user?.role === 'staff'

  const recargar = useCallback(() => {
    api.listar().then(setFilas).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(recargar, [recargar])

  // El único filtro que queda **fuera** de la tabla. La búsqueda por texto se
  // fue adentro (`search` de `DataTable`), que además busca por varios términos
  // en cualquier orden; esto no es una búsqueda sino un interruptor de qué
  // conjunto se mira.
  const visibles = useMemo(
    () => filas.filter((c) => verInactivos || c.activo),
    [filas, verInactivos],
  )

  const borrar = useCallback(
    async (cliente: Cliente) => {
      if (!confirm(`¿Borrar a ${cliente.nombre}? Si tiene reservas no se va a poder.`)) return
      setError(null)
      try {
        await api.borrar(cliente.id)
        recargar()
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [recargar],
  )

  const columnas = useMemo<ColumnDef<Cliente, unknown>[]>(() => {
    const base: ColumnDef<Cliente, unknown>[] = [
      {
        accessorKey: 'nombre',
        header: sortableHeader('Nombre'),
        cell: ({ row }) => (
          <span className="font-medium">
            {row.original.nombre}
            {!row.original.activo && (
              <span className="ml-2 text-xs text-muted-foreground">(de baja)</span>
            )}
          </span>
        ),
      },
      {
        accessorKey: 'telefono',
        header: 'Teléfono',
        cell: ({ row }) => row.original.telefono ?? '—',
      },
      {
        accessorKey: 'documento',
        header: 'Documento',
        cell: ({ row }) => row.original.documento ?? '—',
      },
      { accessorKey: 'cuit', header: 'CUIT', cell: ({ row }) => row.original.cuit ?? '—' },
    ]
    if (!puedeEscribir) return base
    return [
      ...base,
      columnaDeAcciones<Cliente>({
        onEditar: (c) => {
          setEditando(c)
          setAbierto(true)
        },
        onBorrar: borrar,
        nombreDe: (c) => c.nombre,
      }),
    ]
  }, [puedeEscribir, borrar])

  // 🔑 Se distingue por qué está vacía. Un listado vacío sin explicación se lee
  // como un error.
  //
  // Son **dos** casos y no tres: cuando lo que vació la tabla es la búsqueda,
  // `DataTable` ignora este mensaje y pone el suyo —«Sin resultados para
  // “...”»—, que además cita lo que se tecleó. Una tercera rama para ese caso
  // se escribió y resultó ser **código muerto**: no hay forma de que se
  // renderice. Lo delató un test que la esperaba y encontró el mensaje del kit.
  const mensajeVacio =
    filas.length === 0
      ? 'Todavía no hay clientes cargados.'
      : 'Todos los clientes están dados de baja. Marcá «Ver los dados de baja» para verlos.'

  return (
    <div className="space-y-3">
      <EncabezadoDePantalla titulo={<h1 className="text-lg font-semibold">Clientes</h1>}>
        {puedeEscribir && (
          <Button
            onClick={() => {
              setEditando(null)
              setAbierto(true)
            }}
          >
            <Plus className="size-4" />
            Nuevo cliente
          </Button>
        )}
      </EncabezadoDePantalla>

      <div className="flex flex-wrap items-center gap-3">
        <Label className="flex items-center gap-2 text-sm font-normal text-muted-foreground">
          <input
            type="checkbox"
            checked={verInactivos}
            onChange={(e) => setVerInactivos(e.target.checked)}
          />
          Ver los dados de baja
        </Label>
        <span className="text-sm text-muted-foreground">
          {filas.length} {filas.length === 1 ? 'cliente' : 'clientes'} en total
        </span>
      </div>

      <AvisoDeError mensaje={error} />

      {/* Un buscador y no paginación: en un complejo la lista crece a miles y lo
          que el encargado hace es teclear el nombre o el teléfono que le están
          dictando por el mostrador. */}
      <DataTable
        columns={columnas}
        data={visibles}
        getRowClassName={(c) => filaInactiva(c.activo)}
        emptyMessage={mensajeVacio}
        search={{
          campos: (c) => [c.nombre, c.telefono, c.documento, c.cuit],
          placeholder: 'Buscar por nombre, teléfono o documento',
          ariaLabel: 'Buscar cliente',
        }}
      />

      <FormularioDeCliente
        abierto={abierto}
        cliente={editando}
        onCerrar={() => setAbierto(false)}
        onGuardado={() => {
          setAbierto(false)
          recargar()
        }}
      />
    </div>
  )
}
