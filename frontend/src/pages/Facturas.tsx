/** Los comprobantes emitidos por el complejo.
 *
 * La pantalla que faltaba: hasta hoy una factura sólo se veía desde el turno que
 * la originó, así que *"¿qué facturé este mes?"* no tenía dónde preguntarse.
 *
 * 🔑 **No es la pantalla de Contalibra ni la de Restolibra.** Aquellas montan
 * `libra-ui/FacturaDetalle`, que trae autorizar, cobrar, mandar por mail,
 * duplicar y el circuito de notas de crédito y débito. LibraClub no tiene
 * ninguno de esos endpoints —una factura nace de una reserva y no se emite a
 * mano—, así que reusarla obligaría a inventar seis rutas que no existen. Lo que
 * sí se comparte es lo que de verdad es común: la tabla, la pastilla de estado y
 * el título.
 *
 * ⚠️ **Sin columna de cobrado**, y es deliberado: el motor calcula lo cobrado
 * cruzando `caja_movimientos.factura_id`, y en este producto ese campo lo llena
 * únicamente el cobro por QR. Una columna así diría "pendiente" para todo lo
 * cobrado en efectivo. Ver `app/routers/facturas.py`.
 *
 * El detalle de un comprobante sigue siendo el diálogo de la reserva. Acá el
 * único camino hacia adentro es el PDF, que es lo que el cliente pide.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { ChevronLeft, ChevronRight, FileDown, Receipt, Search, X } from 'lucide-react'
import { anchoColumnaAcciones, DataTable, sortableHeader } from 'libra-ui/data-table'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import { facturacion, facturas as apiFacturas, TIPO_DE_FACTURA } from '@/lib/api'
import type { FacturaDeListado } from '@/lib/api'
import { fecha, pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

/** `0003-00000042`, que es como se nombra un comprobante en cualquier papel. */
function numeroDeComprobante(f: FacturaDeListado): string {
  return `${String(f.punto_venta).padStart(4, '0')}-${String(f.numero).padStart(8, '0')}`
}

export function Facturas() {
  const [pagina, setPagina] = useState<FacturaDeListado[]>([])
  const [total, setTotal] = useState(0)
  const [totalPaginas, setTotalPaginas] = useState(1)
  const [page, setPage] = useState(1)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Lo tecleado y lo aplicado son dos estados distintos: la consulta sale al
  // apretar Buscar o Enter, no en cada letra. Con `q` disparando el efecto,
  // escribir "González" serían ocho requests y la lista saltando abajo del dedo.
  const [q, setQ] = useState('')
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [filtros, setFiltros] = useState({ q: '', desde: '', hasta: '' })

  const buscar = useCallback(() => {
    setPage(1)
    setFiltros({ q, desde, hasta })
  }, [q, desde, hasta])

  function limpiar() {
    setQ('')
    setDesde('')
    setHasta('')
    setPage(1)
    setFiltros({ q: '', desde: '', hasta: '' })
  }

  useEffect(() => {
    setCargando(true)
    setError(null)
    apiFacturas
      .listar({ ...filtros, page })
      .then((datos) => {
        setPagina(datos.items)
        setTotal(datos.total)
        setTotalPaginas(datos.total_pages)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [filtros, page])

  const columnas = useMemo<ColumnDef<FacturaDeListado, unknown>[]>(
    () => [
      {
        accessorKey: 'fecha',
        header: sortableHeader('Fecha'),
        size: 110,
        // `fecha()` y no `toLocaleDateString`: la columna es un `aaaa-mm-dd`
        // pelado —un día del calendario— y convertirlo de zona lo corre uno
        // para atrás siempre.
        cell: ({ row }) => fecha(row.original.fecha),
      },
      {
        accessorKey: 'numero',
        header: sortableHeader('Comprobante'),
        size: 190,
        cell: ({ row }) => (
          <span className="font-mono text-sm">
            {/* El tipo va pegado al número porque juntos son la identidad del
                comprobante: la numeración de ARCA es por (tipo, punto de venta). */}
            {TIPO_DE_FACTURA[row.original.tipo] ?? row.original.tipo}{' '}
            {numeroDeComprobante(row.original)}
          </span>
        ),
      },
      {
        accessorKey: 'cliente_razon',
        header: sortableHeader('Cliente'),
        cell: ({ row }) => (
          <span className="font-medium">
            {/* Un complejo le factura a Consumidor Final sin CUIT todo el
                tiempo, así que la fila sin nombre es un caso normal. */}
            {row.original.cliente_razon || 'Consumidor Final'}
          </span>
        ),
      },
      {
        accessorKey: 'total',
        header: sortableHeader('Total'),
        size: 130,
        cell: ({ row }) => <span className="tabular-nums">{pesos(row.original.total)}</span>,
      },
      {
        id: 'cae',
        header: 'CAE',
        size: 150,
        enableSorting: false,
        // 🔑 Sin CAE **no es un error**: la factura existe y tiene número, y lo
        // que falta es que ARCA la autorice. Sin certificado cargado en la
        // instancia pasa siempre — por eso `atencion` y no `negativo`, que
        // mandaría a buscar un problema que no está.
        cell: ({ row }) =>
          row.original.cae ? (
            <BadgeEstado tono="ok" title={`CAE ${row.original.cae}`}>
              Autorizada
            </BadgeEstado>
          ) : (
            <BadgeEstado tono="atencion" title="La instancia todavía no tiene certificado de ARCA">
              Pendiente de CAE
            </BadgeEstado>
          ),
      },
      {
        id: 'acciones',
        header: '',
        size: anchoColumnaAcciones(1),
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex justify-end">
            <Button asChild variant="ghost" size="icon">
              {/* Un `<a>` y no un `onClick`: el PDF se abre en una pestaña, se
                  imprime y se cierra, que es lo que hace falta en un mostrador. */}
              <a
                href={facturacion.urlDelPdf(row.original.id)}
                target="_blank"
                rel="noreferrer"
                aria-label={`Ver el PDF del comprobante ${numeroDeComprobante(row.original)}`}
              >
                <FileDown className="size-4" />
              </a>
            </Button>
          </div>
        ),
      },
    ],
    [],
  )

  const hayFiltros = Boolean(filtros.q || filtros.desde || filtros.hasta)

  return (
    <div className="grid gap-4">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={Receipt}>Comprobantes</TituloPantalla>}>
        {/* Sin botón de "Nuevo": en este producto una factura nace de una
            reserva y se emite desde su turno. Ofrecer un alta acá sería
            prometer un circuito que no existe. */}
        <span className="text-sm text-muted-foreground">
          {total} comprobante{total === 1 ? '' : 's'}
        </span>
      </EncabezadoDePantalla>

      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 py-3">
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && buscar()}
            placeholder="Buscar por número o cliente…"
            aria-label="Buscar comprobantes"
            className="min-w-48 flex-1"
          />
          {/* `type="date"` sin tocar: el input maneja ISO y el `dd-mm-aaaa` es
              cosa de la presentación. */}
          <Input
            type="date"
            value={desde}
            onChange={(e) => setDesde(e.target.value)}
            aria-label="Desde"
            className="w-40"
          />
          <Input
            type="date"
            value={hasta}
            onChange={(e) => setHasta(e.target.value)}
            aria-label="Hasta"
            className="w-40"
          />
          <Button variant="outline" size="icon" aria-label="Buscar" onClick={buscar}>
            <Search className="size-4" />
          </Button>
          {(q || desde || hasta) && (
            <Button variant="outline" size="icon" aria-label="Limpiar filtros" onClick={limpiar}>
              <X className="size-4" />
            </Button>
          )}
        </CardContent>
      </Card>

      <AvisoDeError mensaje={error} />

      <Card>
        <CardContent>
          {cargando ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Cargando…</p>
          ) : (
            <DataTable
              columns={columnas}
              data={pagina}
              emptyMessage={
                hayFiltros
                  ? 'No hay comprobantes con ese criterio.'
                  : 'Todavía no se emitió ningún comprobante. Se facturan desde el turno, en la Agenda.'
              }
            />
          )}
        </CardContent>
      </Card>

      {totalPaginas > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="icon"
            aria-label="Página anterior"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <span className="text-sm text-muted-foreground">
            Página {page} de {totalPaginas}
          </span>
          <Button
            variant="outline"
            size="icon"
            aria-label="Página siguiente"
            disabled={page >= totalPaginas}
            onClick={() => setPage((p) => p + 1)}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      )}
    </div>
  )
}
