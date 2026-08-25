/** La caja del turno: abrir, cobrar y cerrar con arqueo.
 *
 * Una pantalla y no tres: el operador abre al empezar, cobra durante el turno y
 * cierra al irse. Partirlo en rutas obligaría a navegar para hacer lo único que
 * se hace en un mostrador.
 *
 * 🔑 **El esperado lo calcula el backend y acá sólo se muestra.** Es el número
 * que se mira al cerrar, y dos lugares restando por su cuenta terminan mostrando
 * cosas distintas por un redondeo.
 */
import { useCallback, useEffect, useState } from 'react'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { Wallet } from 'lucide-react'

import { caja } from '@/lib/api'
import { useMediosDePago } from '@/lib/medios-pago'
import type { ResumenDeCaja, TurnoDeCaja } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

type Cierre = TurnoDeCaja & { diferencia_de_caja: number }

export function Caja() {
  const [turno, setTurno] = useState<TurnoDeCaja | null>(null)
  const [resumen, setResumen] = useState<ResumenDeCaja | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [cerrado, setCerrado] = useState<Cierre | null>(null)

  const recargar = useCallback(() => {
    setCargando(true)
    caja
      .actual()
      .then((d) => {
        setTurno(d?.turno ?? null)
        setResumen(d?.resumen ?? null)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [])

  useEffect(recargar, [recargar])

  if (cargando) return <p className="text-muted-foreground">Cargando…</p>

  return (
    <div className="space-y-4">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={Wallet}>Caja</TituloPantalla>} />
      <AvisoDeError mensaje={error} />

      {turno === null ? (
        <Apertura
          onAbierta={() => {
            setCerrado(null)
            setError(null)
            recargar()
          }}
          onError={setError}
          ultimoCierre={cerrado}
        />
      ) : (
        <TurnoAbierto
          turno={turno}
          resumen={resumen}
          onCambio={recargar}
          onError={setError}
          onCerrado={(c) => {
            setCerrado(c)
            recargar()
          }}
        />
      )}
    </div>
  )
}

function Apertura({ onAbierta, onError, ultimoCierre }: {
  onAbierta: () => void
  onError: (m: string) => void
  ultimoCierre: Cierre | null
}) {
  const [monto, setMonto] = useState('0')
  const [enviando, setEnviando] = useState(false)

  return (
    <div className="space-y-4">
      {/* El arqueo del cierre anterior se muestra ACÁ y no en un cartel que se
          va: es el número que el operador tiene que ver antes de irse, y si
          desapareciera al recargar nadie sabría cómo cerró. */}
      {ultimoCierre && <Arqueo cierre={ultimoCierre} />}

      <div className="max-w-sm space-y-3 rounded-lg border bg-card p-4">
        <p className="text-sm text-muted-foreground">
          No tenés una caja abierta. Abrila con el efectivo con el que arrancás.
        </p>
        <div className="grid gap-1.5">
          <Label htmlFor="inicial">Efectivo inicial</Label>
          <Input
            id="inicial"
            inputMode="decimal"
            value={monto}
            onChange={(e) => setMonto(e.target.value)}
          />
        </div>
        <Button
          disabled={enviando}
          onClick={async () => {
            setEnviando(true)
            try {
              await caja.abrir(monto)
              onAbierta()
            } catch (e) {
              onError((e as Error).message)
            } finally {
              setEnviando(false)
            }
          }}
        >
          {enviando ? 'Abriendo…' : 'Abrir caja'}
        </Button>
      </div>
    </div>
  )
}

function Arqueo({ cierre }: { cierre: Cierre }) {
  const d = cierre.diferencia_de_caja
  return (
    <div className="max-w-sm space-y-1 rounded-lg border bg-card p-4 text-sm">
      <div className="font-medium">Cierre del turno anterior</div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">Esperado</span>
        <span>{pesos(String(cierre.monto_esperado_cierre ?? 0))}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">Declarado</span>
        <span>{pesos(String(cierre.monto_declarado_cierre ?? 0))}</span>
      </div>
      {/* 🔑 La diferencia no se esconde cuando es cero ni se pinta de rojo
          cuando no lo es: un cierre que no cuadra es un dato para mirar, no un
          error que alguien cometió. */}
      <div className="flex justify-between border-t pt-1 font-medium">
        <span>Diferencia</span>
        <span className={d === 0 ? undefined : 'text-amber-700 dark:text-amber-500'}>
          {d > 0 ? '+' : ''}{pesos(String(d))}
        </span>
      </div>
    </div>
  )
}

function TurnoAbierto({ turno, resumen, onCambio, onError, onCerrado }: {
  turno: TurnoDeCaja
  resumen: ResumenDeCaja | null
  onCambio: () => void
  onError: (m: string) => void
  onCerrado: (c: Cierre) => void
}) {
  const [monto, setMonto] = useState('')
  const [concepto, setConcepto] = useState('')
  const { medios, etiqueta: etiquetaDeMedio } = useMediosDePago()
  const [medio, setMedio] = useState<string>('')
  const [declarado, setDeclarado] = useState('')
  const [enviando, setEnviando] = useState(false)

  // 🔴 El medio por defecto **espera a que la lista llegue**. Antes se
  // inicializaba con `MEDIOS_DE_PAGO[0]`, una constante que estaba siempre; con
  // la lista pedida al backend eso es imposible hasta que conteste, y dejarlo en
  // `''` haría que el movimiento entre a la caja **sin medio** — el cierre lo
  // suma al total pero no lo reparte, y el arqueo por medio no cuadra.
  useEffect(() => {
    if (!medio && medios.length > 0) setMedio(medios[0].valor)
  }, [medio, medios])

  const esperado = turno.monto_inicial + (resumen?.efectivo_ventas ?? 0)

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="space-y-3 rounded-lg border bg-card p-4">
        <div className="flex items-center gap-2 font-medium">
          <Wallet className="size-4" /> Cobrar
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="concepto">Concepto</Label>
          <Input id="concepto" value={concepto} onChange={(e) => setConcepto(e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="grid gap-1.5">
            <Label htmlFor="monto">Monto</Label>
            <Input
              id="monto"
              inputMode="decimal"
              value={monto}
              onChange={(e) => setMonto(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="medio">Medio</Label>
            <select
              id="medio"
              className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
              value={medio}
              onChange={(e) => setMedio(e.target.value)}
            >
              {medios.map((m) => (
                <option key={m.valor} value={m.valor}>{m.etiqueta}</option>
              ))}
            </select>
          </div>
        </div>
        <Button
          disabled={enviando || !concepto.trim() || !monto.trim()}
          onClick={async () => {
            setEnviando(true)
            try {
              await caja.cobrar({ monto, concepto: concepto.trim(), medio_pago: medio })
              setMonto('')
              setConcepto('')
              onCambio()
            } catch (e) {
              onError((e as Error).message)
            } finally {
              setEnviando(false)
            }
          }}
        >
          {enviando ? 'Cobrando…' : 'Registrar cobro'}
        </Button>
      </div>

      <div className="space-y-3 rounded-lg border bg-card p-4">
        <div className="font-medium">Turno abierto</div>
        <div className="space-y-1 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Efectivo inicial</span>
            <span>{pesos(String(turno.monto_inicial))}</span>
          </div>
          {Object.entries(resumen?.pagos_por_medio ?? {}).map(([m, total]) => (
            <div key={m} className="flex justify-between">
              <span className="text-muted-foreground">
                {etiquetaDeMedio(m)}
              </span>
              <span>{pesos(String(total))}</span>
            </div>
          ))}
          {/* 🔑 Se dice «en el cajón» y no «total»: lo que no es efectivo entró
              igual, pero no está acá adentro — mezclarlos es lo que hace que
              toda caja con transferencias parezca cerrar con faltante. */}
          <div className="flex justify-between border-t pt-1 font-medium">
            <span>Esperado en el cajón</span>
            <span>{pesos(String(esperado))}</span>
          </div>
        </div>

        <div className="grid gap-1.5 border-t pt-3">
          <Label htmlFor="declarado">Efectivo contado</Label>
          <Input
            id="declarado"
            inputMode="decimal"
            value={declarado}
            onChange={(e) => setDeclarado(e.target.value)}
          />
        </div>
        <Button
          variant="outline"
          disabled={enviando || !declarado.trim()}
          onClick={async () => {
            setEnviando(true)
            try {
              onCerrado(await caja.cerrar(turno.id, declarado))
            } catch (e) {
              onError((e as Error).message)
            } finally {
              setEnviando(false)
            }
          }}
        >
          Cerrar caja
        </Button>
      </div>
    </div>
  )
}
