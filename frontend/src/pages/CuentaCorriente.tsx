/** La cobranza: quién debe y cuánto.
 *
 * Converge con el listado de cuenta corriente de Contalibra —`DataTable` con
 * buscador, pastilla de saldo y la tarjeta con el total por cobrar arriba— y el
 * extracto de cada cliente pasó a su propia ruta, `/cuenta-corriente/:id`.
 *
 * > Hasta el 2026-08-22 esto era **una sola pantalla partida al medio**, con la
 * > lista a la izquierda y el detalle a la derecha. El argumento era que el uso
 * > real es *"¿quién me debe?"* seguido de *"mostrame lo de éste"*. Sigue siendo
 * > cierto; lo que lo movió es que el resto de la familia abre el detalle en su
 * > propia ruta, y una pantalla que se ve distinta en cada producto obliga a
 * > reaprenderla en cada uno.
 *
 * 🔑 **El saldo y el total los calcula el backend y acá sólo se muestran.** Es
 * plata, y dos lugares sumando por su cuenta terminan mostrando números
 * distintos.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'
import { Eye, NotebookText } from 'lucide-react'
import { DataTable, anchoColumnaAcciones, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import { cuentaCorriente } from '@/lib/api'
import type { SaldoDeCuenta } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { BadgeDeSaldo } from '@/components/saldo'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

export function CuentaCorriente() {
  const [deudores, setDeudores] = useState<SaldoDeCuenta[]>([])
  const [totalDeuda, setTotalDeuda] = useState(0)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const navegar = useNavigate()

  const recargar = useCallback(() => {
    setCargando(true)
    cuentaCorriente
      .deudores()
      .then((datos) => {
        setDeudores(datos.deudores)
        setTotalDeuda(datos.total_deuda)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [])

  useEffect(recargar, [recargar])

  // No hay columna de CUIT/DNI, y no es un olvido: la trae `clients` de
  // LibraCore, donde este producto deja el `cuit_dni` **vacío a propósito**
  // (ver `servicios/cuenta_corriente.py`). Una columna que siempre dice "—"
  // invita a "arreglarla" espejando el documento, y eso abriría un segundo
  // camino al saldo que contaría cada deuda dos veces.
  const columnas = useMemo<ColumnDef<SaldoDeCuenta, unknown>[]>(
    () => [
      {
        accessorKey: 'cliente',
        header: sortableHeader('Cliente'),
        cell: ({ row }) => <span className="font-medium">{row.original.cliente}</span>,
      },
      {
        accessorKey: 'saldo',
        header: sortableHeader('Saldo'),
        cell: ({ row }) => <BadgeDeSaldo monto={row.original.saldo} />,
      },
      {
        id: 'acciones',
        header: '',
        size: anchoColumnaAcciones(1),
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex justify-end">
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Ver la cuenta de ${row.original.cliente}`}
              onClick={() => navegar(`/cuenta-corriente/${row.original.cliente_id}`)}
            >
              <Eye className="size-4" />
            </Button>
          </div>
        ),
      },
    ],
    [navegar],
  )

  if (cargando) return <p className="text-muted-foreground">Cargando…</p>

  return (
    <div className="space-y-4">
      <EncabezadoDePantalla
        titulo={<TituloPantalla icono={NotebookText}>Cuenta corriente</TituloPantalla>}
      />
      <AvisoDeError mensaje={error} />

      {/* Sólo si hay algo que cobrar: una tarjeta que dice "$0" ocupa el lugar
          más visible de la pantalla para no informar nada. */}
      {totalDeuda > 0 && (
        <Card className="border-0 bg-amber-50 dark:bg-amber-950/40">
          <CardContent className="py-3 text-center">
            <p className="text-sm text-muted-foreground">Total por cobrar</p>
            <p className="text-xl font-bold text-amber-800 dark:text-amber-400">
              {pesos(totalDeuda)}
            </p>
          </CardContent>
        </Card>
      )}

      <DataTable
        columns={columnas}
        data={deudores}
        // La fila entera abre la cuenta, igual que en Torneos. El botón del ojo
        // queda igual porque es lo que hace el resto de la familia y porque es
        // la única forma de llegar al detalle con el teclado.
        onRowClick={(d: SaldoDeCuenta) => navegar(`/cuenta-corriente/${d.cliente_id}`)}
        emptyMessage="Nadie tiene movimientos en cuenta corriente todavía. Las reservas se fían desde el detalle del turno, con «Cargar a la cuenta»."
        search={{
          campos: (d: SaldoDeCuenta) => [d.cliente],
          placeholder: 'Buscar cliente',
          ariaLabel: 'Buscar cliente',
        }}
      />
    </div>
  )
}
