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

import { caja, cajas as apiCajas } from '@/lib/api'
import { useMediosDePago } from '@/lib/medios-pago'
import type { CajaDeMostrador, ResumenDeCaja, TurnoDeCaja } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { useSucursal } from '@/context/SucursalContext'

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
  const { actual } = useSucursal()
  const [monto, setMonto] = useState('0')
  const [enviando, setEnviando] = useState(false)
  const [mostradores, setMostradores] = useState<CajaDeMostrador[]>([])
  const [elegida, setElegida] = useState<string>('')

  // 🔑 Los mostradores son **de esta sucursal**: el turno se abre sobre el cajón
  // en el que se está parado. Si esta sede no tiene ninguno, no se puede abrir
  // —y el cartel lo dice— porque crear uno es de admin.
  useEffect(() => {
    if (actual === null) return
    apiCajas
      .deLaSucursal(actual)
      .then((cs) => {
        const activas = cs.filter((c) => c.activo)
        setMostradores(activas)
        if (activas.length > 0) setElegida(String(activas[0].id))
      })
      .catch((e: Error) => onError(e.message))
  }, [actual, onError])

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

        {mostradores.length === 0 ? (
          // Se distingue "no hay mostradores" de "no abriste el turno": lo
          // primero no lo puede resolver el mostrador, y un formulario que no
          // funciona sin decir por qué manda a adivinar.
          <p className="text-sm text-amber-700 dark:text-amber-500">
            Esta sucursal no tiene ninguna caja cargada. Pedile a un
            administrador que dé de alta una en Maestros → Cajas.
          </p>
        ) : (
          <div className="grid gap-1.5">
            <Label htmlFor="mostrador">Caja</Label>
            <select
              id="mostrador"
              className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
              value={elegida}
              onChange={(e) => setElegida(e.target.value)}
            >
              {mostradores.map((c) => (
                <option key={c.id} value={String(c.id)}>{c.nombre}</option>
              ))}
            </select>
          </div>
        )}

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
          disabled={enviando || mostradores.length === 0}
          onClick={async () => {
            setEnviando(true)
            try {
              await caja.abrir(monto, '', Number(elegida))
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

        <Egreso medios={medios} onHecho={onCambio} onError={onError} />
      </div>

      <div className="space-y-3 rounded-lg border bg-card p-4">
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-medium">Turno abierto</span>
          {/* Sobre qué cajón, que es lo que separa el arqueo de una sede del de
              la otra. Los turnos anteriores al 2026-08-28 no tienen caja y se
              dice, en vez de dejar el lugar en blanco. */}
          <span className="text-sm text-muted-foreground">
            {turno.caja_nombre || 'sin caja asignada'}
          </span>
        </div>
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

        <Movimientos
          movimientos={resumen?.movimientos ?? []}
          etiquetaDeMedio={etiquetaDeMedio}
          onAnulado={onCambio}
          onError={onError}
        />

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


/** Plata que **sale** del cajón, con su motivo.
 *
 * 🔴 **Sin esto el arqueo sólo podía subir.** El resumen ya neteaba los egresos
 * y no había forma de registrar uno: sacar plata dejaba el cierre con un
 * faltante sin explicación, indistinguible de un error de conteo.
 *
 * El motivo sale de una lista **del backend** y no de constantes acá: si
 * divergieran, la pantalla ofrecería un motivo que el POST rechaza con 422.
 */
function Egreso({ medios, onHecho, onError }: {
  medios: { valor: string; etiqueta: string }[]
  onHecho: () => void
  onError: (m: string) => void
}) {
  const [abierto, setAbierto] = useState(false)
  const [motivos, setMotivos] = useState<string[]>([])
  const [motivo, setMotivo] = useState('')
  const [monto, setMonto] = useState('')
  const [detalle, setDetalle] = useState('')
  const [medio, setMedio] = useState('')
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    caja.motivosDeEgreso()
      .then((ms) => {
        setMotivos(ms)
        if (ms.length > 0) setMotivo((m) => m || ms[0])
      })
      .catch((e: Error) => onError(e.message))
  }, [abierto, onError])

  useEffect(() => {
    if (!medio && medios.length > 0) setMedio(medios[0].valor)
  }, [medio, medios])

  if (!abierto) {
    return (
      <Button variant="outline" size="sm" onClick={() => setAbierto(true)}>
        Registrar un egreso
      </Button>
    )
  }

  return (
    <div className="grid gap-2 rounded-md border border-dashed p-3">
      <div className="text-sm font-medium">Egreso</div>
      <div className="grid gap-1.5">
        <Label htmlFor="motivo-egreso">Motivo</Label>
        <select
          id="motivo-egreso"
          className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
          value={motivo}
          onChange={(e) => setMotivo(e.target.value)}
        >
          {motivos.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="grid gap-1.5">
          <Label htmlFor="monto-egreso">Monto</Label>
          <Input
            id="monto-egreso"
            inputMode="decimal"
            value={monto}
            onChange={(e) => setMonto(e.target.value)}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="medio-egreso">Medio</Label>
          <select
            id="medio-egreso"
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
      <div className="grid gap-1.5">
        <Label htmlFor="detalle-egreso">Detalle</Label>
        <Input
          id="detalle-egreso"
          value={detalle}
          onChange={(e) => setDetalle(e.target.value)}
          placeholder="Opcional"
        />
      </div>
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={enviando || !monto.trim() || !motivo}
          onClick={async () => {
            setEnviando(true)
            try {
              await caja.egreso({ monto, motivo, detalle: detalle.trim(), medio_pago: medio })
              setMonto('')
              setDetalle('')
              setAbierto(false)
              onHecho()
            } catch (e) {
              onError((e as Error).message)
            } finally {
              setEnviando(false)
            }
          }}
        >
          {enviando ? 'Registrando…' : 'Registrar egreso'}
        </Button>
        <Button size="sm" variant="outline" onClick={() => setAbierto(false)}>
          Cancelar
        </Button>
      </div>
    </div>
  )
}


/** Lo que se cargó en el turno, y el botón para anular un error.
 *
 * 🔑 **Los datos ya llegaban y la pantalla los tiraba.** `get_resumen_turno_caja`
 * devuelve `movimientos` desde siempre y acá se mostraban sólo los totales por
 * medio: el operador cobraba a ciegas y un monto mal tipeado sólo aparecía como
 * una diferencia al cerrar, cuando ya no se sabía cuál era.
 */
function Movimientos({ movimientos, etiquetaDeMedio, onAnulado, onError }: {
  movimientos: ResumenDeCaja['movimientos']
  etiquetaDeMedio: (m: string) => string
  onAnulado: () => void
  onError: (m: string) => void
}) {
  const [anulando, setAnulando] = useState<number | null>(null)

  if (movimientos.length === 0) {
    return (
      <p className="border-t pt-3 text-sm text-muted-foreground">
        Todavía no cargaste nada en este turno.
      </p>
    )
  }

  return (
    <div className="grid gap-1 border-t pt-3">
      <div className="text-sm font-medium">Movimientos</div>
      {movimientos.map((m) => (
        <div key={m.id} className="flex items-center justify-between gap-2 text-sm">
          <span className="min-w-0 flex-1 truncate" title={m.concepto}>
            {m.concepto}
            <span className="ml-1 text-muted-foreground">
              · {etiquetaDeMedio(m.medio_pago)}
            </span>
          </span>
          {/* El egreso se muestra en negativo: es lo que hace que la lista se
              pueda sumar de arriba abajo y dé el esperado. */}
          <span className={m.tipo === 'egreso' ? 'text-amber-700 dark:text-amber-500' : undefined}>
            {m.tipo === 'egreso' ? '−' : ''}{pesos(String(m.monto))}
          </span>
          <Button
            variant="outline"
            size="sm"
            aria-label={`Anular ${m.concepto}`}
            disabled={anulando === m.id}
            onClick={async () => {
              setAnulando(m.id)
              try {
                await caja.anular(m.id)
                onAnulado()
              } catch (e) {
                onError((e as Error).message)
              } finally {
                setAnulando(null)
              }
            }}
          >
            Anular
          </Button>
        </div>
      ))}
    </div>
  )
}
