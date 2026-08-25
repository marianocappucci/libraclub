/** El extracto de un cliente, y el cobro.
 *
 * La contraparte de `/cuenta-corriente`: se llega desde el listado de cobranza.
 * Converge con `CuentaCorrienteDetalle` de Contalibra — pastilla de saldo en el
 * título, las tres tarjetas de totales, el extracto en `DataTable` y el pago en
 * un diálogo.
 *
 * 🔑 **El saldo lo trae el backend; los dos totales se suman acá y no es lo
 * mismo.** «Total cargado» y «Total abonado» son la suma de lo que está en la
 * tabla de abajo: si se calcularan del otro lado podrían no coincidir con las
 * filas que el cliente tiene enfrente. El saldo, que es el número que se
 * reclama, sigue viniendo del motor.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'
import {
  ArrowDownCircle, ArrowLeft, ArrowUpCircle, CircleDollarSign, NotebookText,
} from 'lucide-react'
import { DataTable } from 'libra-ui/data-table'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import { cuentaCorriente } from '@/lib/api'
import { useMediosDePago } from '@/lib/medios-pago'
import type { MovimientoDeCuenta, SaldoDeCuenta } from '@/lib/api'
import { diaISO, fecha as formatearFecha, pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { BadgeDeSaldo } from '@/components/saldo'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Cuenta = SaldoDeCuenta & { movimientos: MovimientoDeCuenta[] }

// La etiqueta sale del hook, que la pide al backend: acá había un mapa
// armado sobre la copia local de la lista.

export function CuentaCorrienteDetalle() {
  const { id } = useParams<{ id: string }>()
  const clienteId = Number(id)
  const { etiqueta: etiquetaDeMedio } = useMediosDePago()

  const [cuenta, setCuenta] = useState<Cuenta | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pagoAbierto, setPagoAbierto] = useState(false)

  const recargar = useCallback(() => {
    cuentaCorriente
      .ver(clienteId)
      .then(setCuenta)
      .catch((e: Error) => setError(e.message))
  }, [clienteId])

  useEffect(recargar, [recargar])

  const totales = useMemo(() => {
    let cargado = 0
    let abonado = 0
    for (const m of cuenta?.movimientos ?? []) {
      // 🔑 Por `tipo` y no por el signo del número: el motor manda el `monto`
      // siempre positivo, así que sumar por signo pondría los pagos del lado
      // de la deuda y los dos totales darían lo mismo.
      if (m.tipo === 'debito') cargado += m.monto
      else abonado += m.monto
    }
    return { cargado, abonado }
  }, [cuenta])

  const columnas = useMemo<ColumnDef<MovimientoDeCuenta, unknown>[]>(
    () => [
      {
        accessorKey: 'fecha',
        header: 'Fecha',
        cell: ({ row }) => (
          <span className="whitespace-nowrap">{formatearFecha(row.original.fecha)}</span>
        ),
      },
      {
        accessorKey: 'tipo',
        header: 'Tipo',
        cell: ({ row }) =>
          row.original.tipo === 'debito' ? (
            <BadgeEstado tono="negativo">
              <ArrowUpCircle />
              Cargo
            </BadgeEstado>
          ) : (
            <BadgeEstado tono="ok">
              <ArrowDownCircle />
              Abono
            </BadgeEstado>
          ),
      },
      { accessorKey: 'concepto', header: 'Concepto' },
      {
        accessorKey: 'usuario_nombre',
        header: 'Usuario',
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.usuario_nombre || '—'}
          </span>
        ),
      },
      {
        accessorKey: 'referencia',
        header: 'Referencia / Medio',
        cell: ({ row }) => (
          <span className="flex flex-wrap items-center gap-1 text-muted-foreground">
            {row.original.referencia || '—'}
            {/* El medio de pago es una categoría, no un estado: por eso queda
                como `Badge` y no como pastilla de estado — ver el criterio en
                `identidad-visual-suite-libra`. */}
            {row.original.medio && (
              <Badge variant="outline">
                {etiquetaDeMedio(row.original.medio)}
              </Badge>
            )}
          </span>
        ),
      },
      {
        accessorKey: 'monto',
        header: () => <div className="text-right">Monto</div>,
        // Una sola columna con signo, como en Contalibra, y no un Debe/Haber.
        // El `+`/`−` y el color salen de `tipo`, nunca del signo del número:
        // el motor lo manda siempre positivo.
        cell: ({ row }) => (
          <div
            className={`whitespace-nowrap text-right font-semibold ${
              row.original.tipo === 'debito'
                ? 'text-destructive'
                : 'text-emerald-700 dark:text-emerald-400'
            }`}
          >
            {row.original.tipo === 'debito' ? '+' : '−'} {pesos(row.original.monto)}
          </div>
        ),
      },
    ],
    [],
  )

  if (cuenta === null) {
    return (
      <div className="space-y-4">
        <AvisoDeError mensaje={error} />
        {error === null && <p className="text-muted-foreground">Cargando…</p>}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <EncabezadoDePantalla
        titulo={
          <TituloPantalla icono={NotebookText}>
            {cuenta.cliente}
            <BadgeDeSaldo monto={cuenta.saldo} />
          </TituloPantalla>
        }
      >
        <Button onClick={() => setPagoAbierto(true)}>
          <CircleDollarSign className="size-4" />
          Registrar pago
        </Button>
        <Button asChild variant="outline">
          <Link to="/cuenta-corriente">
            <ArrowLeft className="size-4" />
            Volver
          </Link>
        </Button>
      </EncabezadoDePantalla>

      <AvisoDeError mensaje={error} />

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader>
            <CardDescription>Total cargado</CardDescription>
            <CardTitle className="text-xl text-destructive">
              {pesos(totales.cargado)}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Total abonado</CardDescription>
            <CardTitle className="text-xl text-emerald-700 dark:text-emerald-400">
              {pesos(totales.abonado)}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            {/* La pastilla ya está en el título: repetirla acá es el mismo dato
                dos veces. Lo que agrega la tarjeta es la comparación con las
                otras dos, y para eso alcanza el número. Sí se conserva la regla
                de no mostrar un negativo — lo dice la descripción. */}
            <CardDescription>
              {cuenta.saldo < 0 ? 'Saldo a favor' : 'Saldo actual'}
            </CardDescription>
            <CardTitle
              className={
                cuenta.saldo > 0
                  ? 'text-xl text-amber-800 dark:text-amber-400'
                  : 'text-xl text-emerald-700 dark:text-emerald-400'
              }
            >
              {pesos(Math.abs(cuenta.saldo))}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      <DataTable
        columns={columnas}
        data={cuenta.movimientos}
        emptyMessage="Sin movimientos."
      />

      <DialogoDePago
        abierto={pagoAbierto}
        clienteId={clienteId}
        nombre={cuenta.cliente}
        saldo={cuenta.saldo}
        onCerrar={() => setPagoAbierto(false)}
        onRegistrado={() => {
          setPagoAbierto(false)
          recargar()
        }}
      />
    </div>
  )
}

/** El cobro a cuenta.
 *
 * El pago entra a la caja del **turno abierto**: sin turno, el backend contesta
 * 409 y el mensaje lo dice. El diálogo no se esconde por eso — abrir la caja es
 * lo que hay que hacer, y esconder el formulario no lo explica.
 */
function DialogoDePago({ abierto, clienteId, nombre, saldo, onCerrar, onRegistrado }: {
  abierto: boolean
  clienteId: number
  nombre: string
  saldo: number
  onCerrar: () => void
  onRegistrado: () => void
}) {
  const [monto, setMonto] = useState('')
  const [fecha, setFecha] = useState('')
  const [concepto, setConcepto] = useState('')
  const { medios } = useMediosDePago()
  const [medio, setMedio] = useState<string>('')
  const [referencia, setReferencia] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    // Precargado con lo que debe, que es el caso normal: viene a saldar. Se
    // puede editar para una entrega parcial o una seña.
    setMonto(saldo > 0 ? String(saldo) : '')
    // 🔴 `diaISO` y no `toISOString().slice(0,10)`: ese da el día en UTC, así
    // que después de las 21:00 de Argentina el pago nacería fechado mañana —
    // y esa es justo la franja en la que un complejo cobra.
    setFecha(diaISO(new Date()))
    setConcepto('')
    setMedio(medios[0]?.valor ?? '')
    setReferencia('')
  }, [abierto, saldo])

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      await cuentaCorriente.pagar(clienteId, {
        monto,
        medio_pago: medio,
        fecha,
        concepto,
        referencia,
      })
      onRegistrado()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Dialog open={abierto} onOpenChange={(o) => !o && onCerrar()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CircleDollarSign className="size-4" />
            Registrar pago — {nombre}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={enviar} className="grid gap-3">
          {saldo > 0 && (
            <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm dark:border-amber-900 dark:bg-amber-950/40">
              Saldo pendiente: <strong>{pesos(saldo)}</strong>
            </p>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="monto-cc">Monto</Label>
              <Input
                id="monto-cc"
                inputMode="decimal"
                value={monto}
                onChange={(e) => setMonto(e.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="fecha-cc">Fecha</Label>
              <Input
                id="fecha-cc"
                type="date"
                value={fecha}
                onChange={(e) => setFecha(e.target.value)}
              />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="concepto-cc">Concepto</Label>
            <Input
              id="concepto-cc"
              value={concepto}
              onChange={(e) => setConcepto(e.target.value)}
              placeholder="Pago a cuenta"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="medio-cc">Medio</Label>
              {/* `<select>` nativo y no el `Select` de shadcn: es lo que usan
                  los diez formularios de este producto. Copiar el de Contalibra
                  acá dejaría este diálogo como el único distinto adentro de
                  LibraClub, que es lo contrario de normalizar. */}
              <select
                id="medio-cc"
                className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
                value={medio}
                onChange={(e) => setMedio(e.target.value)}
              >
                {medios.map((m) => (
                  <option key={m.valor} value={m.valor}>
                    {m.etiqueta}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="referencia-cc">
                Referencia{' '}
                <span className="font-normal text-muted-foreground">(opcional)</span>
              </Label>
              <Input
                id="referencia-cc"
                value={referencia}
                onChange={(e) => setReferencia(e.target.value)}
                placeholder="N° transferencia, cheque…"
              />
            </div>
          </div>
          <AvisoDeError mensaje={error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onCerrar}>
              Cancelar
            </Button>
            <Button type="submit" disabled={enviando || !monto.trim()}>
              <CircleDollarSign className="size-4" />
              {enviando ? 'Registrando…' : 'Registrar pago'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
