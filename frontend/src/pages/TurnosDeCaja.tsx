/** El historial de turnos de caja: qué se cerró, cuándo y con cuánta diferencia.
 *
 * 🔴 **El endpoint existía desde el 2026-08-21 y no lo llamaba nadie.**
 * `GET /api/caja/turnos` estaba, y `caja.historial()` estaba escrito en
 * `lib/api.ts` — con **cero call sites** en todo el frontend. O sea que el
 * arqueo de ayer no se podía mirar: se cerraba la caja y el número se perdía de
 * vista. Lo detectó la medición contra [[contalibra]] del 2026-08-29.
 *
 * 🔑 **Quién ve qué lo decide el backend, no esta pantalla.** Un admin recibe
 * todos los turnos y un encargado sólo los suyos, filtrado en la consulta. Acá
 * no hay ningún `if` sobre el rol para esconder filas: filtrar en la pantalla
 * es cómo los datos ajenos igual viajan hasta el navegador.
 *
 * ⚠️ **No está en el sidebar, y es a propósito.** Contalibra la tiene ahí, pero
 * este producto ya lleva «Caja» (el turno abierto) y «Cajas» (los mostradores);
 * una tercera entrada con la palabra caja obliga a leer las tres para elegir.
 * Se llega desde la Caja, igual que `/caja/movimientos`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'
import { ArrowDownCircle, ArrowLeft, ArrowUpCircle, CheckCircle2, Eye, Wallet } from 'lucide-react'
import { DataTable, anchoColumnaAcciones, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { BadgeEstado } from 'libra-ui/badge-estado'

import { caja } from '@/lib/api'
import type { TurnoDeCaja } from '@/lib/api'
import { fechaHora, pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'

/** La diferencia del arqueo, con su signo y su color.
 *
 * 🔑 **Se calcula acá y no se pide al backend**, al revés que el resto de la
 * plata de este producto — pero es una resta de dos números que ya vinieron, no
 * una consulta. Lo que no se hace es sumar movimientos: eso sí es del backend.
 *
 * ⚠️ **El umbral de un centavo NO es protección contra floats** —eso ya lo hace
 * el `Math.round` de la línea de abajo, que devuelve `-0` para una diferencia
 * de una millonésima—. Es una **decisión de negocio**: contando efectivo, un
 * centavo para arriba o para abajo es cuadrar, no un faltante que alguien
 * tenga que ir a buscar.
 *
 * Lo dice acá porque el comentario anterior afirmaba lo primero y era falso; lo
 * delató una mutación que sacó el umbral y **ningún test se puso rojo**.
 */
export function DiferenciaDeArqueo({ esperado, declarado }: {
  esperado: number | null
  declarado: number | null
}) {
  if (esperado === null || declarado === null) {
    return <span className="text-muted-foreground">—</span>
  }
  const diferencia = Math.round((declarado - esperado) * 100) / 100
  if (diferencia > 0.01) {
    return (
      <span className="inline-flex items-center gap-1 font-medium text-emerald-700 dark:text-emerald-400">
        <ArrowUpCircle className="size-4" aria-hidden />
        sobró {pesos(diferencia)}
      </span>
    )
  }
  if (diferencia < -0.01) {
    return (
      <span className="inline-flex items-center gap-1 font-medium text-destructive">
        <ArrowDownCircle className="size-4" aria-hidden />
        faltó {pesos(Math.abs(diferencia))}
      </span>
    )
  }
  {/* 🔑 «Cuadró» y no un tilde a secas: el símbolo solo no lo lee un lector de
      pantalla, y en una columna de números un ✓ verde se confunde con «cobrado».
      Misma decisión que los movimientos anulados. */}
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground">
      <CheckCircle2 className="size-4" aria-hidden />
      cuadró
    </span>
  )
}

export function TurnosDeCaja() {
  const [turnos, setTurnos] = useState<TurnoDeCaja[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const navegar = useNavigate()

  const recargar = useCallback(() => {
    setCargando(true)
    caja
      .historial()
      .then(setTurnos)
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [])

  useEffect(recargar, [recargar])

  const columnas = useMemo<ColumnDef<TurnoDeCaja>[]>(
    () => [
      {
        accessorKey: 'id',
        header: 'N°',
        size: 60,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.id}</span>
        ),
      },
      {
        accessorKey: 'usuario_nombre',
        header: sortableHeader('Cajero'),
        meta: { stretch: true },
        cell: ({ row }) => (
          <span className="block truncate font-medium">{row.original.usuario_nombre}</span>
        ),
      },
      {
        accessorKey: 'caja_nombre',
        header: 'Mostrador',
        size: 140,
        // Los turnos anteriores al 2026-08-28 nacieron sin caja: quedaron en la
        // de por defecto y el motor no les guardó el nombre. Se dice, en vez de
        // dejar la celda en blanco.
        cell: ({ row }) => (
          <span className="block truncate">
            {row.original.caja_nombre || <span className="text-muted-foreground">sin mostrador</span>}
          </span>
        ),
      },
      {
        accessorKey: 'apertura',
        header: sortableHeader('Apertura'),
        size: 150,
        cell: ({ row }) => <span className="whitespace-nowrap">{fechaHora(row.original.apertura)}</span>,
      },
      {
        accessorKey: 'cierre',
        header: 'Cierre',
        size: 150,
        cell: ({ row }) => (
          <span className="whitespace-nowrap">
            {row.original.cierre ? fechaHora(row.original.cierre) : '—'}
          </span>
        ),
      },
      {
        accessorKey: 'monto_esperado_cierre',
        header: () => <div className="text-right">Esperado</div>,
        size: 120,
        cell: ({ row }) => (
          <div className="text-right">
            {row.original.monto_esperado_cierre === null
              ? '—'
              : pesos(row.original.monto_esperado_cierre)}
          </div>
        ),
      },
      {
        accessorKey: 'monto_declarado_cierre',
        header: () => <div className="text-right">Declarado</div>,
        size: 120,
        cell: ({ row }) => (
          <div className="text-right">
            {row.original.monto_declarado_cierre === null
              ? '—'
              : pesos(row.original.monto_declarado_cierre)}
          </div>
        ),
      },
      {
        id: 'diferencia',
        header: 'Diferencia',
        size: 140,
        cell: ({ row }) => (
          <DiferenciaDeArqueo
            esperado={row.original.monto_esperado_cierre}
            declarado={row.original.monto_declarado_cierre}
          />
        ),
      },
      {
        accessorKey: 'estado',
        header: 'Estado',
        size: 90,
        cell: ({ row }) => (
          <BadgeEstado tono={row.original.estado === 'abierto' ? 'ok' : 'neutro'}>
            {row.original.estado === 'abierto' ? 'Abierto' : 'Cerrado'}
          </BadgeEstado>
        ),
      },
      {
        id: 'acciones',
        header: () => <div className="text-right">Acciones</div>,
        size: anchoColumnaAcciones(1),
        cell: ({ row }) => (
          <div className="flex justify-end">
            <Button
              asChild
              size="icon"
              variant="outline"
              title={`Ver el turno ${row.original.id}`}
            >
              <Link to={`/caja/turnos/${row.original.id}`} aria-label={`Ver el turno ${row.original.id}`}>
                <Eye className="size-4" />
              </Link>
            </Button>
          </div>
        ),
      },
    ],
    [],
  )

  return (
    <div className="space-y-4">
      {/* El icono es el de la Caja: esta pantalla es una subpágina de /caja y no
          una sección propia del menú. Mismo criterio que Movimientos. */}
      <EncabezadoDePantalla
        titulo={<TituloPantalla icono={Wallet}>Turnos de caja</TituloPantalla>}
      >
        <Link
          to="/caja"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          <ArrowLeft className="size-4" /> Volver a la caja
        </Link>
      </EncabezadoDePantalla>
      <AvisoDeError mensaje={error} />

      {cargando ? (
        <p className="text-muted-foreground">Cargando…</p>
      ) : (
        <DataTable
          columns={columnas}
          data={turnos}
          onRowClick={(t) => navegar(`/caja/turnos/${t.id}`)}
          search={{
            // El número de turno entra en la búsqueda: es lo que uno tiene a
            // mano cuando viene de un comprobante o de un aviso.
            campos: (t: TurnoDeCaja) => [t.usuario_nombre, t.caja_nombre, String(t.id)],
            placeholder: 'Buscar por cajero o mostrador',
            ariaLabel: 'Buscar turno',
          }}
          emptyMessage="Todavía no se cerró ningún turno."
        />
      )}
    </div>
  )
}
