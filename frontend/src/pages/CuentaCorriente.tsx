/** La cobranza: quién debe, cuánto, y el extracto de cada uno.
 *
 * Una sola pantalla con la lista a la izquierda y el detalle a la derecha: el
 * uso real es *"¿quién me debe?"* seguido de *"mostrame lo de éste"*, y partirlo
 * en dos rutas obligaría a volver atrás en cada cliente.
 *
 * 🔑 **El saldo lo calcula el backend y acá sólo se muestra.** Es plata, y dos
 * lugares sumando por su cuenta terminan mostrando números distintos.
 */
import { useCallback, useEffect, useState } from 'react'
import { EncabezadoDePantalla } from 'libra-ui/acciones'

import { MEDIOS_DE_PAGO, cuentaCorriente } from '@/lib/api'
import type { MovimientoDeCuenta, SaldoDeCuenta } from '@/lib/api'
import { fecha, pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function CuentaCorriente() {
  const [deudores, setDeudores] = useState<SaldoDeCuenta[]>([])
  const [elegido, setElegido] = useState<number | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const recargar = useCallback(() => {
    setCargando(true)
    cuentaCorriente
      .deudores()
      .then(setDeudores)
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [])

  useEffect(recargar, [recargar])

  if (cargando) return <p className="text-muted-foreground">Cargando…</p>

  return (
    <div className="space-y-4">
      <EncabezadoDePantalla
        titulo={<h1 className="text-lg font-semibold">Cuenta corriente</h1>}
      />
      <AvisoDeError mensaje={error} />

      {deudores.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nadie tiene movimientos en cuenta corriente todavía. Las reservas se fían
          desde el detalle del turno, con «Cargar a la cuenta».
        </p>
      ) : (
        <div className="grid gap-4 md:grid-cols-[minmax(0,20rem)_1fr]">
          <ListaDeDeudores deudores={deudores} elegido={elegido} onElegir={setElegido} />
          {elegido === null ? (
            <p className="text-sm text-muted-foreground">
              Elegí un cliente para ver su extracto.
            </p>
          ) : (
            <Detalle clienteId={elegido} onPago={recargar} />
          )}
        </div>
      )}
    </div>
  )
}

function ListaDeDeudores({ deudores, elegido, onElegir }: {
  deudores: SaldoDeCuenta[]
  elegido: number | null
  onElegir: (id: number) => void
}) {
  return (
    <ul className="divide-y rounded-lg border bg-card">
      {deudores.map((d) => (
        <li key={d.cliente_id}>
          <button
            type="button"
            onClick={() => onElegir(d.cliente_id)}
            aria-current={d.cliente_id === elegido ? 'true' : undefined}
            className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-muted ${
              d.cliente_id === elegido ? 'bg-muted' : ''
            }`}
          >
            <span className="truncate">{d.cliente}</span>
            <Saldo monto={d.saldo} />
          </button>
        </li>
      ))}
    </ul>
  )
}

/** 🔑 Un saldo a favor no es un error: se dice «a favor», no un número negativo
 *  con signo menos que hay que interpretar. */
function Saldo({ monto }: { monto: number }) {
  if (monto === 0) return <span className="text-muted-foreground">Al día</span>
  if (monto > 0) return <span className="font-medium">{pesos(String(monto))}</span>
  return (
    <span className="text-muted-foreground">
      {pesos(String(-monto))} a favor
    </span>
  )
}

function Detalle({ clienteId, onPago }: { clienteId: number; onPago: () => void }) {
  const [datos, setDatos] = useState<
    (SaldoDeCuenta & { movimientos: MovimientoDeCuenta[] }) | null
  >(null)
  const [monto, setMonto] = useState('')
  const [medio, setMedio] = useState<string>(MEDIOS_DE_PAGO[0].valor)
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const recargar = useCallback(() => {
    cuentaCorriente
      .ver(clienteId)
      .then(setDatos)
      .catch((e: Error) => setError(e.message))
  }, [clienteId])

  useEffect(recargar, [recargar])

  if (datos === null) return <p className="text-muted-foreground">Cargando…</p>

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between gap-2 rounded-lg border bg-card p-4">
        <div className="font-medium">{datos.cliente}</div>
        <div className="text-lg"><Saldo monto={datos.saldo} /></div>
      </div>

      <div className="space-y-3 rounded-lg border bg-card p-4">
        <div className="font-medium">Registrar un pago</div>
        {/* El pago entra a la caja del turno abierto: sin turno, el backend
            contesta 409 y el mensaje lo dice. No se esconde el formulario —
            abrir la caja es lo que hay que hacer, y esconderlo no lo explica. */}
        <div className="grid grid-cols-2 gap-2">
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
            <Label htmlFor="medio-cc">Medio</Label>
            <select
              id="medio-cc"
              className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
              value={medio}
              onChange={(e) => setMedio(e.target.value)}
            >
              {MEDIOS_DE_PAGO.map((m) => (
                <option key={m.valor} value={m.valor}>{m.etiqueta}</option>
              ))}
            </select>
          </div>
        </div>
        <AvisoDeError mensaje={error} />
        <Button
          disabled={enviando || !monto.trim()}
          onClick={async () => {
            setError(null)
            setEnviando(true)
            try {
              await cuentaCorriente.pagar(clienteId, { monto, medio_pago: medio })
              setMonto('')
              recargar()
              onPago()
            } catch (e) {
              setError((e as Error).message)
            } finally {
              setEnviando(false)
            }
          }}
        >
          {enviando ? 'Registrando…' : 'Registrar pago'}
        </Button>
      </div>

      <Extracto movimientos={datos.movimientos} />
    </div>
  )
}

function Extracto({ movimientos }: { movimientos: MovimientoDeCuenta[] }) {
  if (movimientos.length === 0) {
    return <p className="text-sm text-muted-foreground">Sin movimientos.</p>
  }
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead className="border-b text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Fecha</th>
            <th className="px-3 py-2 text-left font-medium">Concepto</th>
            <th className="px-3 py-2 text-right font-medium">Debe</th>
            <th className="px-3 py-2 text-right font-medium">Haber</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {movimientos.map((m, i) => (
            // El motor no devuelve un id único por movimiento —vienen de tres
            // tablas distintas—, así que la key va por posición.
            <tr key={`${m.fecha}-${i}`}>
              <td className="whitespace-nowrap px-3 py-2">{fecha(m.fecha)}</td>
              <td className="px-3 py-2">{m.concepto}</td>
              {/* 🔑 Dos columnas y no una con signo: el monto viene siempre
                  positivo y el que dice de qué lado va es `tipo`. */}
              <td className="px-3 py-2 text-right">
                {m.tipo === 'debito' ? pesos(String(m.monto)) : ''}
              </td>
              <td className="px-3 py-2 text-right">
                {m.tipo === 'debito' ? '' : pesos(String(m.monto))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
