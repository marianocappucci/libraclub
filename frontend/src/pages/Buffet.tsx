/** El buffet: qué hay, cuánto queda y qué se vende.
 *
 * Una sola pantalla porque en un complejo es una sola persona: el encargado
 * repone cuando llega el proveedor y vende cuando alguien se acerca al
 * mostrador. Partirlo en "catálogo" y "punto de venta" serían dos rutas para
 * dos clicks del mismo turno.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { AlertTriangle, CupSoda, Plus } from 'lucide-react'

import { buffet as api } from '@/lib/api'
import type { ProductoDeBuffet } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { useSucursal } from '@/context/SucursalContext'
import { useAuth } from '@/context/AuthContext'
import { FormularioDeProducto } from '@/components/FormularioDeProducto'
import { AvisoDeError, filaInactiva } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

export function Buffet() {
  const { actual } = useSucursal()
  const { user } = useAuth()
  const [filas, setFilas] = useState<ProductoDeBuffet[]>([])
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)
  const [editando, setEditando] = useState<ProductoDeBuffet | null>(null)
  const [abierto, setAbierto] = useState(false)

  const puedeEscribir = user?.role === 'admin'

  const recargar = useCallback(() => {
    if (actual === null) return
    setCargando(true)
    api
      .productos(actual)
      .then(setFilas)
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [actual])

  useEffect(recargar, [recargar])

  const reponer = useCallback(
    async (p: ProductoDeBuffet) => {
      const texto = prompt(
        `¿Cuántas unidades de ${p.nombre}? Un número negativo descuenta (rotura, vencido).`,
        '12',
      )
      if (texto === null) return
      const cantidad = Number(texto)
      if (!cantidad) return
      const motivo =
        cantidad > 0 ? 'Entrega del proveedor' : (prompt('¿Por qué se descuenta?') ?? 'Ajuste')
      setError(null)
      try {
        await api.ajustar(actual!, { item_id: p.item_id, cantidad: String(cantidad), motivo })
        recargar()
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [actual, recargar],
  )

  const bajos = useMemo(() => filas.filter((f) => f.bajo_minimo && f.activo), [filas])

  const columnas = useMemo<ColumnDef<ProductoDeBuffet, unknown>[]>(() => {
    const base: ColumnDef<ProductoDeBuffet, unknown>[] = [
      {
        accessorKey: 'nombre',
        header: sortableHeader('Producto'),
        cell: ({ row }) => (
          <span className="font-medium">
            {row.original.nombre}
            {!row.original.activo && (
              <span className="ml-2 text-xs text-muted-foreground">(inactivo)</span>
            )}
          </span>
        ),
      },
      {
        accessorKey: 'precio',
        header: sortableHeader('Precio'),
        cell: ({ row }) => pesos(String(row.original.precio)),
      },
      {
        accessorKey: 'stock',
        header: sortableHeader('Stock'),
        cell: ({ row }) => (
          // 🔑 El bajo mínimo se marca en la fila y no sólo en un contador
          // arriba: el que mira la tabla para reponer necesita ver CUÁL, no
          // cuántos.
          <span
            className={
              row.original.bajo_minimo ? 'font-medium text-amber-700 dark:text-amber-500' : ''
            }
          >
            {row.original.stock}
            {row.original.stock_minimo > 0 && (
              <span className="ml-1 text-xs text-muted-foreground">
                (mín. {row.original.stock_minimo})
              </span>
            )}
          </span>
        ),
      },
      // 🔑 **Una sola columna de acciones, con su título y los dos botones con
      // borde.** Hasta el 2026-08-28 eran DOS columnas —`reponer` y `editar`—,
      // las dos sin encabezado y con distinta variante: «Reponer» con borde y
      // «Editar» sin, uno al lado del otro en la misma fila. Es el caso más
      // visible de lo que el humano reportó el 2026-08-28.
      //
      // «Editar» sigue apareciendo sólo con permiso de escritura; lo que cambió
      // es que ahora comparte columna con «Reponer» en vez de agregar una
      // segunda sin nombre.
      {
        id: 'acciones',
        header: () => <div className="text-right">Acciones</div>,
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <Button variant="outline" size="sm" onClick={() => reponer(row.original)}>
              Reponer
            </Button>
            {puedeEscribir && (
              <Button
                variant="outline"
                size="sm"
                aria-label={`Editar ${row.original.nombre}`}
                onClick={() => {
                  setEditando(row.original)
                  setAbierto(true)
                }}
              >
                Editar
              </Button>
            )}
          </div>
        ),
      },
    ]
    return base
  }, [puedeEscribir, reponer])

  if (actual === null) {
    return <p className="text-muted-foreground">Elegí una sucursal para ver su buffet.</p>
  }
  if (cargando) return <p className="text-muted-foreground">Cargando…</p>

  return (
    <div className="space-y-3">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={CupSoda}>Buffet</TituloPantalla>}>
        {/* 🔴 **Acá no se vende.** El botón «Vender» estuvo hasta el
            2026-08-28 y se retiró por pedido del humano: *"para cobrar un turno
            o buffet de la cancha lo cobrás por caja pero algo de buffet solo va
            por buffet, no es práctico, todo tiene que ir por el mismo lado"*.
            La venta suelta se hace desde la Caja, que es la única pantalla
            donde entra plata; ésta quedó para lo que de verdad es —cargar
            productos y stock—, que es también por lo que vive en Maestros. */}
        {puedeEscribir && (
          <Button
            onClick={() => {
              setEditando(null)
              setAbierto(true)
            }}
          >
            <Plus className="size-4" />
            Nuevo producto
          </Button>
        )}
      </EncabezadoDePantalla>

      <p className="text-sm text-muted-foreground">
        El stock es <strong>por sucursal</strong>. Lo que se consume durante un
        turno se carga a la cancha desde el detalle de la reserva, y sale en la
        misma factura; lo que se vende acá se cobra en el acto, contra la caja
        del turno abierto.
      </p>

      {bajos.length > 0 && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>
            <span className="font-medium">Hay que reponer:</span>{' '}
            {bajos.map((b) => `${b.nombre} (${b.stock})`).join(', ')}.
          </span>
        </div>
      )}

      <AvisoDeError mensaje={error} />

      <DataTable
        columns={columnas}
        data={filas}
        getRowClassName={(p) => filaInactiva(p.activo)}
        emptyMessage="Sin productos. Cargá lo que se vende en el buffet."
        search={{
          campos: (p) => [p.nombre],
          placeholder: 'Buscar producto',
          ariaLabel: 'Buscar producto del buffet',
        }}
      />

      <FormularioDeProducto
        abierto={abierto}
        producto={editando}
        sucursalId={actual}
        onCerrar={() => setAbierto(false)}
        onGuardado={() => {
          setAbierto(false)
          recargar()
        }}
      />
    </div>
  )
}
