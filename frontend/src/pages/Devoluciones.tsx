/** Las devoluciones de seña que el complejo debe y todavía no hizo.
 *
 * 🔴 **Esta pantalla es lo que hace que `devolucion_pendiente` sirva para algo.**
 * Un estado que dice «le debemos plata a alguien» y que nadie puede ver es peor
 * que no tenerlo: la deuda existe, no se paga, y la única forma de enterarse es
 * que el jugador llame.
 *
 * Se llega acá por dos caminos, y los dos son normales: la instancia todavía no
 * tiene cargadas las credenciales de Mercado Pago, o MercadoPago rechazó la
 * devolución. El motivo de cada una se muestra en la fila — sin eso, la
 * respuesta a «¿por qué sigue pendiente?» es mirar los logs del contenedor.
 *
 * **Ver es de staff; reintentar es de admin.** El encargado tiene que poder
 * contestarle al jugador que llama sin poder mover plata hacia afuera.
 */
import { useCallback, useEffect, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { RotateCw, Undo2 } from 'lucide-react'

import { devoluciones as api } from '@/lib/api'
import type { DevolucionPendiente } from '@/lib/api'
import { useAuth } from '@/context/AuthContext'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { fechaHora, pesos } from '@/lib/fechas'

export function Devoluciones() {
  const { user } = useAuth()
  const puedeReintentar = user?.role === 'admin'

  const [filas, setFilas] = useState<DevolucionPendiente[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Qué fila se está reintentando. El id y no un booleano: con dos devoluciones
  // pendientes, un booleano deshabilitaría los dos botones a la vez.
  const [reintentando, setReintentando] = useState<number | null>(null)
  const [ultimo, setUltimo] = useState<string | null>(null)

  const recargar = useCallback(() => {
    setCargando(true)
    api
      .pendientes()
      .then(setFilas)
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [])

  useEffect(recargar, [recargar])

  async function reintentar(pago: DevolucionPendiente) {
    setReintentando(pago.id)
    setError(null)
    try {
      const r = await api.reintentar(pago.id)
      // El endpoint contesta 200 aunque siga pendiente: el texto es el
      // resultado, no un error. Mostrarlo es todo el punto de la pantalla.
      setUltimo(r.detalle)
      recargar()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setReintentando(null)
    }
  }

  const columnas: ColumnDef<DevolucionPendiente>[] = [
    {
      accessorKey: 'reserva_id',
      header: sortableHeader('Turno'),
      cell: ({ row }) => `#${row.original.reserva_id}`,
    },
    {
      accessorKey: 'monto',
      header: sortableHeader('Seña'),
      cell: ({ row }) => pesos(row.original.monto),
    },
    {
      accessorKey: 'created_at',
      header: sortableHeader('Cobrada'),
      cell: ({ row }) => fechaHora(row.original.created_at),
    },
    {
      accessorKey: 'detalle_devolucion',
      header: 'Por qué sigue pendiente',
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">
          {row.original.detalle_devolucion ?? '—'}
        </span>
      ),
    },
    {
      id: 'acciones',
      header: 'Acciones',
      cell: ({ row }) =>
        puedeReintentar ? (
          <Button
            variant="outline"
            size="sm"
            disabled={reintentando === row.original.id}
            onClick={() => reintentar(row.original)}
          >
            <RotateCw className="mr-1 h-3 w-3" />
            {reintentando === row.original.id ? 'Devolviendo…' : 'Reintentar'}
          </Button>
        ) : null,
    },
  ]

  return (
    <div className="space-y-4">
      <TituloPantalla icono={Undo2}>Devoluciones pendientes</TituloPantalla>

      <p className="text-sm text-muted-foreground">
        Señas que corresponde devolver y todavía no se devolvieron. Reintentar
        dos veces no devuelve dos veces: el pedido lleva una clave de
        idempotencia por pago.
      </p>

      <AvisoDeError mensaje={error} />
      {ultimo && (
        <p className="rounded-md bg-muted px-3 py-2 text-sm">{ultimo}</p>
      )}

      {!cargando && filas.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No hay devoluciones pendientes.
        </p>
      ) : (
        <DataTable columns={columnas} data={filas} />
      )}
    </div>
  )
}
