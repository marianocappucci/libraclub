/** La caja del turno: abrir, cobrar y cerrar con arqueo.
 *
 * Una pantalla y no tres: el operador abre al empezar, cobra durante el turno y
 * cierra al irse. Partirlo en rutas obligaría a navegar para hacer lo único que
 * se hace en un mostrador.
 *
 * 🔑 **El esperado lo calcula el backend y acá sólo se muestra.** Es el número
 * que se mira al cerrar, y dos lugares restando por su cuenta terminan mostrando
 * cosas distintas por un redondeo.
 *
 * 🔴 **Y desde el 2026-08-28 ésta es la única pantalla donde entra plata.**
 * Antes había tres —el turno se cobraba desde el detalle de la reserva, el
 * buffet suelto desde la pantalla de Buffet, y acá quedaba el cobro libre—, cada
 * una nacida por su lado; la Caja terminó siendo la que sobra en vez de la que
 * manda. Reportado por el humano: *"todo tiene que ir por el mismo lado"*.
 *
 * Lo que **no** se junta es el consumo con su cobro: cargar buffet a una cancha
 * abierta **no cobra nada**, queda colgado del turno y se cobra con él, en una
 * sola operación y un solo comprobante. Cobrarlo dos veces es exactamente lo que
 * ese diseño evita. Por eso las dos acciones están separadas y con su nombre.
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { CalendarCheck, CupSoda, Receipt, Users, Wallet } from 'lucide-react'

import {
  buffet, caja, cajas as apiCajas, cobroDelTurno, cobroQr, turnosPorCobrar,
} from '@/lib/api'
import { useMediosDePago } from '@/lib/medios-pago'
import type {
  CajaDeMostrador, LineaDeConsumo, QrDisponible, ResumenDeCaja, TurnoDeCaja,
  TurnoPorCobrar,
} from '@/lib/api'
import { diasDeDiferencia, fecha, hora, pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { DialogoDeConsumo } from '@/components/DialogoDeConsumo'
import { SeccionDeCobroConQr } from '@/components/CobroConQr'
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
  // El monto, el concepto y el medio del cobro viven ahora en cada modo del
  // punto de venta: los tres cobran cosas distintas y compartir un solo estado
  // dejaba el importe de un turno metido en el cobro libre siguiente.
  const { medios, etiqueta: etiquetaDeMedio } = useMediosDePago()
  const [declarado, setDeclarado] = useState('')
  const [enviando, setEnviando] = useState(false)

  const esperado = turno.monto_inicial + (resumen?.efectivo_ventas ?? 0)

  // 🔴 **Un turno de caja es de una jornada, y esto es lo único que lo sostiene.**
  // No hay nada que cierre los turnos viejos: el 2026-08-28 había dos abiertos
  // desde el 21, siete días, y el «esperado en el cajón» era la suma de una
  // semana — un arqueo que abarca siete días no mide nada, y el faltante que
  // aparezca no se puede atribuir a ningún día.
  //
  // Se compara el **día local** y no el tiempo transcurrido: uno abierto ayer a
  // las 23:00 y mirado hoy a las 08:00 lleva un día, aunque hayan pasado nueve
  // horas. Lo que cambió es la jornada.
  const diasAbierto = diasDeDiferencia(turno.apertura)
  const deOtroDia = diasAbierto > 0

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="space-y-4 rounded-lg border bg-card p-4">
        <div className="flex items-center gap-2 font-medium">
          <Wallet className="size-4" /> Cobrar
        </div>

        {deOtroDia ? (
          // 🔴 **El freno está acá y no en la API**, a propósito. Bloquearlo del
          // lado del backend rompería lo que llega **solo**: la acreditación de
          // un pago por QR y el consumo de buffet que se cobra con el turno
          // entran por `registrar_ingreso` sin que nadie apriete un botón, y
          // rechazarlos perdería plata que ya entró. Esto es disciplina en el
          // punto de uso, no un invariante — y se dice, para no confundir una
          // cosa con la otra.
          <div className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
            <p className="font-medium">
              Cerrá la caja del {fecha(turno.apertura)} antes de seguir cobrando.
            </p>
            <p className="text-muted-foreground">
              Está abierta hace {diasAbierto === 1 ? 'un día' : `${diasAbierto} días`}, así
              que el arqueo de la derecha suma todo ese tiempo y no la jornada.
              Contá el efectivo, cerrala, y abrí una nueva.
            </p>
          </div>
        ) : (
          <>
            <PuntoDeVenta medios={medios} onCambio={onCambio} onError={onError} />

            <Egreso medios={medios} onHecho={onCambio} onError={onError} />
          </>
        )}
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
        {deOtroDia && (
          // El mismo dato de este lado: acá está el arqueo, y es donde se ve el
          // número que la antigüedad explica.
          <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-sm">
            Abierta desde el <strong>{fecha(turno.apertura)}</strong>, hace{' '}
            {diasAbierto === 1 ? 'un día' : `${diasAbierto} días`}.
          </p>
        )}
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

        {/* 🔴 **El detalle acumulado del turno NO va acá.** Pedido del humano
            el 2026-08-28: *"lo que la caja mueva entre todas las canchas no
            tiene por qué verse en la pantalla de caja"*. Y no es sólo ruido: la
            unidad de trabajo del mostrador es **la cuenta de una cancha**, y una
            lista con los movimientos de todas mezclados invita a buscar ahí lo
            que se cierra del otro lado, cancha por cancha.

            Lo que queda de este lado son los **totales**, que son lo que se
            necesita para el arqueo. El detalle sigue existiendo —y con él la
            anulación— en `/caja/movimientos`, a un click. */}
        <Link
          to="/caja/movimientos"
          className="block text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          Ver los movimientos del turno →
        </Link>

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
/** Las tres formas de que entre plata, juntas y con su nombre.
 *
 * 🔴 **Son tres y no una sola caja de texto** justamente porque no son lo mismo:
 *
 * | | Qué cobra | Contra qué queda |
 * |---|---|---|
 * | **Canchas** | la cuenta de un turno: alquiler + su buffet | la reserva, y su comprobante |
 * | **Venta suelta** | una venta de buffet sin cancha, en el acto | la venta |
 * | **Otro** | un ingreso suelto, con concepto libre | nada |
 *
 * 🔑 **La cuenta de la cancha es la unidad de trabajo**, y por eso es el primer
 * modo: el operador va a un turno concreto, a nombre de alguien, y lo cierra
 * ahí. El buffet consumido en esa cancha entra en esa cuenta y **no se cobra
 * aparte** — cargarlo no mueve plata, la mueve el cierre del turno. Cobrarlo dos
 * veces es exactamente lo que ese diseño evita.
 *
 * «Venta suelta» es la otra mitad: la gaseosa que compra alguien que no está
 * jugando. Ésa sí se cobra en el acto, porque no hay turno donde colgarla.
 */
function PuntoDeVenta({ medios, onCambio, onError }: {
  medios: { valor: string; etiqueta: string }[]
  onCambio: () => void
  onError: (m: string) => void
}) {
  const { actual: sucursalId } = useSucursal()
  const [modo, setModo] = useState<'turno' | 'buffet' | 'libre'>('turno')
  const [turnos, setTurnos] = useState<TurnoPorCobrar[]>([])

  const recargarTurnos = useCallback(() => {
    if (sucursalId === null) return
    turnosPorCobrar
      .listar(sucursalId)
      // Se comprueba la forma y no se confía en ella: un cuerpo truncado es
      // truthy y el `.map()` del selector tumbaría la pantalla entera.
      .then((ts) => setTurnos(Array.isArray(ts) ? ts : []))
      .catch(() => setTurnos([]))
  }, [sucursalId])

  useEffect(recargarTurnos, [recargarTurnos])

  const alCobrar = () => {
    recargarTurnos()
    onCambio()
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-1 rounded-md bg-muted p-1">
        <BotonDeModo icono={CalendarCheck} activo={modo === 'turno'} onClick={() => setModo('turno')}>
          Canchas
        </BotonDeModo>
        {/* ⚠️ Dice «Venta suelta» y no «Mostrador»: los cajones de la caja se
            llaman así —el default de cada sede es «Mostrador»— y dos cosas
            distintas con el mismo nombre en la misma pantalla es una de las
            formas más baratas de confundir a quien la usa. Lo delató un test que
            buscaba el nombre del cajón y encontraba la pestaña. */}
        <BotonDeModo icono={CupSoda} activo={modo === 'buffet'} onClick={() => setModo('buffet')}>
          Venta suelta
        </BotonDeModo>
        <BotonDeModo icono={Receipt} activo={modo === 'libre'} onClick={() => setModo('libre')}>
          Otro
        </BotonDeModo>
      </div>

      {modo === 'turno' && (
        <CuentasDeCancha
          turnos={turnos}
          medios={medios}
          sucursalId={sucursalId}
          onCobrado={alCobrar}
          onError={onError}
        />
      )}
      {modo === 'buffet' && (
        <VentaDeMostrador sucursalId={sucursalId} onCargado={alCobrar} />
      )}
      {modo === 'libre' && <CobroLibre medios={medios} onCobrado={alCobrar} onError={onError} />}
    </div>
  )
}

function BotonDeModo({ icono: Icono, activo, onClick, children }: {
  icono: typeof Wallet
  activo: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={activo}
      className={
        'flex items-center justify-center gap-1.5 rounded px-2 py-1.5 text-sm transition-colors '
        + (activo
          ? 'bg-background font-medium shadow-xs'
          : 'text-muted-foreground hover:text-foreground')
      }
    >
      <Icono className="size-4" /> {children}
    </button>
  )
}

/** Parte un importe en `cuantas` partes que **suman exactamente el importe**.
 *
 * 🔴 **El resto se reparte, no se descarta.** Es el defecto clásico de dividir
 * una cuenta: $14.000 entre 3 da $4.666,66 y tres pagos de eso suman $13.999,98
 * — quedan **dos centavos pendientes que nadie puede cobrar** y el turno no
 * cierra nunca. Se trabaja en centavos enteros y el resto se reparte de a uno
 * entre las primeras partes, así que la suma cierra siempre.
 *
 * Se exporta sólo para que el test pueda medirlo sin montar la pantalla: es
 * aritmética, y probarla a través de clicks es probarla con ruido.
 */
export function partirImporte(importe: number, cuantas: number): number[] {
  if (!Number.isFinite(importe) || importe <= 0 || cuantas < 1) return []
  const centavos = Math.round(importe * 100)
  const base = Math.floor(centavos / cuantas)
  const resto = centavos - base * cuantas
  return Array.from({ length: cuantas }, (_, i) => (base + (i < resto ? 1 : 0)) / 100)
}

/** Cuántos jugadores propone la pantalla según el deporte.
 *
 * Es un **punto de partida, no una regla**: se puede cambiar antes de dividir.
 * El pádel se juega de a cuatro y es el caso dominante de este producto, así que
 * arrancar en 2 obligaría a corregirlo siempre. Para el resto se arranca en 2,
 * que es lo menos comprometido — un fútbol 5 son diez jugadores pero nadie
 * divide una cancha en diez.
 */
function jugadoresSugeridos(deporte: string): number {
  return deporte === 'padel' ? 4 : 2
}

/** La cuenta de una cancha: qué debe ese turno y cómo se cierra.
 *
 * 🔑 **Una lista y no un `<select>`.** El pedido del humano fue *"poder ir a una
 * cancha determinada en un turno determinado a nombre de tal persona"*: eso es
 * mirar lo que hay abierto y elegir, no desplegar un combo y adivinar. Con
 * cuatro canchas la lista entra entera y se lee de un vistazo cuánto debe cada
 * una.
 *
 * 🔴 **El monto arranca en el pendiente y se puede editar.** Lo primero cubre el
 * caso normal —el cliente paga todo— y lo segundo la seña, que es la mitad de lo
 * que pasa en un complejo. Fijarlo al total obligaría a cobrar de más o a salir
 * de la Caja para tomar una seña.
 */
function CuentasDeCancha({ turnos, medios, sucursalId, onCobrado, onError }: {
  turnos: TurnoPorCobrar[]
  medios: { valor: string; etiqueta: string }[]
  sucursalId: number | null
  onCobrado: () => void
  onError: (m: string) => void
}) {
  const [elegido, setElegido] = useState<number | null>(null)

  // 🔴 **La elección se suelta cuando el turno deja la lista.** Un turno cobrado
  // entero desaparece de `turnos`, y con el id viejo guardado el panel se
  // quedaría abierto sobre una cuenta que ya no está — o peor, mostrando los
  // números de la cuenta que ocupe ese lugar después.
  useEffect(() => {
    if (elegido !== null && !turnos.some((t) => t.reserva_id === elegido)) {
      setElegido(null)
    }
  }, [elegido, turnos])

  if (turnos.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No hay canchas con cuenta abierta hoy.
      </p>
    )
  }

  const turno = turnos.find((t) => t.reserva_id === elegido) ?? null

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-1">
        {turnos.map((t) => (
          <button
            key={t.reserva_id}
            type="button"
            aria-pressed={t.reserva_id === elegido}
            onClick={() => setElegido(t.reserva_id === elegido ? null : t.reserva_id)}
            className={
              'flex min-w-0 items-center gap-2 rounded-md border px-2 py-1.5 text-left text-sm '
              + (t.reserva_id === elegido ? 'border-primary bg-accent' : 'hover:bg-accent/50')
            }
          >
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium">{t.cancha}</span>
              <span className="text-muted-foreground"> · {hora(t.comienza_at)}</span>
              {t.cliente ? <span className="text-muted-foreground"> · {t.cliente}</span> : null}
            </span>
            <span className="shrink-0 tabular-nums">{pesos(t.pendiente)}</span>
          </button>
        ))}
      </div>

      {turno && (
        <CierreDeCuenta
          turno={turno}
          medios={medios}
          sucursalId={sucursalId}
          onCobrado={onCobrado}
          onError={onError}
        />
      )}
    </div>
  )
}

function CierreDeCuenta({ turno, medios, sucursalId, onCobrado, onError }: {
  turno: TurnoPorCobrar
  medios: { valor: string; etiqueta: string }[]
  sucursalId: number | null
  onCobrado: () => void
  onError: (m: string) => void
}) {
  const [consumos, setConsumos] = useState<LineaDeConsumo[]>([])
  const [monto, setMonto] = useState(String(turno.pendiente))
  const [medio, setMedio] = useState<string>('')
  const [enviando, setEnviando] = useState(false)
  const [cargandoBuffet, setCargandoBuffet] = useState(false)
  const [qrDeLaInstancia, setQrDeLaInstancia] = useState<QrDisponible | null>(null)

  // Si este complejo puede cobrar por QR. Se pregunta una vez por cuenta
  // abierta; sin respuesta se asume que no, porque cobrar por QR es una forma
  // más de cobrar y no un requisito para operar el mostrador.
  useEffect(() => {
    cobroQr.estado()
      .then(setQrDeLaInstancia)
      .catch(() => setQrDeLaInstancia({ disponible: false, auto_facturar: false }))
  }, [])
  // Qué líneas de la cuenta se están cobrando en este movimiento. `null` = la
  // cuenta entera, que es el caso normal y el estado inicial.
  const [tildadas, setTildadas] = useState<Set<string> | null>(null)
  // La división entre jugadores, si se pidió. `partes` se calcula **una vez** y
  // no se recalcula: ver el comentario del efecto que la suelta.
  const [division, setDivision] = useState<{ partes: number[]; pagadas: boolean[] } | null>(null)
  const [cuantos, setCuantos] = useState(() => jugadoresSugeridos(turno.deporte))

  useEffect(() => {
    if (!medio && medios.length > 0) setMedio(medios[0].valor)
  }, [medio, medios])

  // El monto sigue al turno: cambiar de cancha con el importe del anterior
  // adentro es cobrarle a uno lo que debe otro. Y se sueltan las tildes, por lo
  // mismo: son las líneas de la cuenta anterior.
  useEffect(() => {
    setMonto(String(turno.pendiente))
    setTildadas(null)
  }, [turno.reserva_id, turno.pendiente])

  // 🔴 **La división se suelta al cambiar de cancha y NO al bajar el pendiente.**
  // Es la diferencia entre que funcione y que no: cada parte que se cobra baja
  // el pendiente, y recalcular las partes desde el pendiente nuevo le cambiaría
  // el importe a los jugadores que todavía no pagaron. Se calcula una vez, sobre
  // lo que había, y se sostiene hasta que se cobra entera o se cancela.
  useEffect(() => {
    setDivision(null)
    setCuantos(jugadoresSugeridos(turno.deporte))
  }, [turno.reserva_id, turno.deporte])

  const verConsumos = useCallback(() => {
    buffet
      .consumosDe(turno.reserva_id)
      // Una instancia sin buffet configurado contesta 503: no es un error que
      // mostrar, es que este complejo no tiene buffet y el detalle no aparece.
      .then((d) => setConsumos(Array.isArray(d?.lineas) ? d.lineas : []))
      .catch(() => setConsumos([]))
  }, [turno.reserva_id])

  useEffect(verConsumos, [verConsumos])

  const buffetDeLaCuenta = consumos.reduce((suma, l) => suma + l.importe, 0)

  /** Las líneas de la cuenta: el alquiler, y cada consumo cargado a la cancha.
   *
   * 🔑 **El alquiler sale de restar** y no de un campo propio: el backend manda
   * el total ya armado —alquiler más buffet— y es el mismo número que factura el
   * turno. Pedir el precio por separado abriría un segundo origen para la misma
   * cifra, que es cómo dos pantallas terminan diciendo cosas distintas.
   */
  const lineas = [
    { clave: 'alquiler', texto: 'Alquiler de la cancha', importe: turno.total - buffetDeLaCuenta },
    ...consumos.map((l, i) => ({
      clave: `c${i}`,
      texto: `${l.cantidad}× ${l.descripcion}`,
      importe: l.importe,
    })),
  ]

  // 🔑 El valor es el del backend (`servicios/caja.MEDIOS_PAGO`), no una
  // constante de esta pantalla: la lista viene de `/api/caja/medios-pago` y
  // duplicarla es cómo se llega a que la pantalla ofrezca un medio que el POST
  // rechaza con 422.
  const porQr = medio === 'mercadopago'
  const fraccionado = tildadas !== null
  const elegidas = lineas.filter((l) => !fraccionado || tildadas.has(l.clave))
  const sumaElegida = elegidas.reduce((suma, l) => suma + l.importe, 0)

  const alternar = (clave: string) => {
    // La primera tilde arranca desde "todas", que es lo que se ve: destildar una
    // línea de una cuenta completa es el gesto natural para cobrar el resto.
    const base = tildadas ?? new Set(lineas.map((l) => l.clave))
    const proximas = new Set(base)
    if (proximas.has(clave)) proximas.delete(clave)
    else proximas.add(clave)
    setTildadas(proximas)
    setMonto(
      String(lineas.filter((l) => proximas.has(l.clave)).reduce((s, l) => s + l.importe, 0)),
    )
  }

  const detalle = fraccionado && elegidas.length < lineas.length
    ? elegidas.map((l) => l.texto).join(', ').slice(0, 120)
    : ''

  return (
    <div className="space-y-3 rounded-md border bg-muted/40 p-3">
      {/* 🔑 **Cada línea se tilda, y ahí está el fraccionamiento.** Pedido del
          humano el 2026-08-28: un turno se cierra como una mesa de restaurante,
          *"se puede pagar solo la cancha y después cada uno paga individual lo
          que pidió"*. Destildar el buffet y cobrar deja el alquiler saldado y el
          resto pendiente; después cada jugador tilda lo suyo. Son N cobros
          parciales contra la misma reserva — lo mismo que ya hacía una seña.
          ⚠️ Lo que el sistema guarda es **cuánto** entró, no qué línea quedó
          saldada: el texto de las líneas viaja como `detalle` para que el arqueo
          se pueda leer, pero no es una liquidación. */}
      <div className="space-y-1 text-sm">
        {lineas.map((l) => (
          <label
            key={l.clave}
            className="flex cursor-pointer items-center justify-between gap-2"
          >
            <span className="flex min-w-0 items-center gap-2">
              <input
                type="checkbox"
                className="size-3.5 shrink-0"
                // Con MercadoPago el monto lo decide el backend: dejar tildar
                // sugeriría que el QR va a cobrar lo elegido, y no lo hace.
                disabled={porQr}
                checked={!fraccionado || tildadas.has(l.clave)}
                onChange={() => alternar(l.clave)}
              />
              <span className="min-w-0 truncate text-muted-foreground">{l.texto}</span>
            </span>
            <span className="shrink-0 tabular-nums">{pesos(l.importe)}</span>
          </label>
        ))}
        <div className="flex justify-between border-t pt-1">
          <span className="text-muted-foreground">Total</span>
          <span className="tabular-nums">{pesos(turno.total)}</span>
        </div>
        {turno.cobrado > 0 && (
          <div className="flex justify-between">
            <span className="text-muted-foreground">Ya cobrado</span>
            <span className="tabular-nums">−{pesos(turno.cobrado)}</span>
          </div>
        )}
        <div className="flex justify-between border-t pt-1 font-medium">
          <span>Pendiente</span>
          <span className="tabular-nums">{pesos(turno.pendiente)}</span>
        </div>
        {fraccionado && elegidas.length < lineas.length && (
          // 🔴 Se dice **qué** se está por cobrar, no sólo cuánto. Con tres
          // cobros parciales sobre la misma cuenta, un importe suelto en la
          // pantalla no alcanza para saber si es el que corresponde.
          <p className="border-t pt-1 text-muted-foreground">
            Cobrando {elegidas.length} de {lineas.length}: {pesos(sumaElegida)}
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="grid gap-1.5">
          <Label htmlFor="monto-cuenta">Monto</Label>
          <Input
            id="monto-cuenta"
            inputMode="decimal"
            value={monto}
            onChange={(e) => setMonto(e.target.value)}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="medio-cuenta">Medio</Label>
          <select
            id="medio-cuenta"
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

      {/* 🔴 **Elegir MercadoPago acá lleva al QR, no registra un movimiento.**
       *
       * Lo reportó el humano el 2026-08-28: *"si quiero realizar un cobro y
       * elijo mercadopago no me dirige para que la persona escanee el QR"*. El
       * flujo existía entero —poner el monto en el cartel, poléar hasta que se
       * acredite, facturar solo— pero **sólo se llegaba desde el detalle del
       * turno**, que con la Caja convertida en punto de venta es justamente el
       * camino que dejó de usarse. Seleccionar «MercadoPago» y apretar Cobrar
       * anotaba el ingreso como si hubiera entrado, sin haber cobrado nada.
       *
       * ⚠️ **El QR cobra el pendiente ENTERO y una sola vez.** No respeta las
       * líneas destildadas ni la división: el monto lo decide el backend
       * —`cobro_qr.total_a_cobrar`— y la base admite **un solo pago aprobado por
       * reserva** (`uq_pagos_reserva_aprobado`). Por eso con MercadoPago elegido
       * esta pantalla no ofrece fraccionar: ofrecerlo sería prometer algo que el
       * modelo no puede cumplir. Para fraccionar, se cobra cada parte por otro
       * medio — o se cobra el resto en efectivo y el saldo por QR, que sí
       * funciona porque el QR ahora pone lo que falta y no el total.
       */}
      {porQr ? (
        <div className="space-y-2 border-t pt-3">
          {/* 🔑 **El mensaje de «no hay credenciales» lo pone el componente**, que
              es quien lo sabe. Acá estaba duplicado y es cómo una copia termina
              diciendo una cosa y la otra otra. */}
          <SeccionDeCobroConQr
            reservaId={turno.reserva_id}
            estado={turno.estado}
            abierto
            onCobrado={onCobrado}
          />
          {qrDeLaInstancia?.disponible ? (
            // Lo que agrega esta línea sobre el texto del componente es **el
            // número**: el componente dice qué cobra, y acá se sabe cuánto.
            <p className="text-xs text-muted-foreground">
              Son {pesos(turno.pendiente)}, de una sola vez.
            </p>
          ) : (
            // Y lo que agrega de este lado cuando NO se puede: que el cobro
            // igual se puede anotar a mano. Eso es propio de la Caja —en el
            // detalle del turno no hay dónde anotarlo— así que no va al
            // componente.
            <p className="text-xs text-muted-foreground">
              Mientras tanto, el cobro se puede registrar a mano con el botón de
              abajo.
            </p>
          )}
        </div>
      ) : null}

      {/* 🔑 **Dividir entre jugadores.** En una cancha de pádel lo normal no es
          que pague uno: pagan los cuatro, y a veces con medios distintos. Se
          divide **lo que se está por cobrar** —el monto de arriba, que por
          defecto es el pendiente y con líneas destildadas es la parte elegida—,
          así las dos formas de partir la cuenta se componen: cobrás el alquiler
          entero y después dividís el buffet entre los tres que consumieron.

          🔴 El medio de pago es el de arriba y se cambia **entre parte y
          parte**: es exactamente el caso en que uno paga en efectivo y otro
          transfiere, que es por lo que esto existe. */}
      {porQr ? null : division === null ? (
        <div className="flex items-end gap-2 border-t pt-3">
          <div className="grid gap-1.5">
            <Label htmlFor="cuantos-jugadores">Jugadores</Label>
            <Input
              id="cuantos-jugadores"
              className="w-20"
              inputMode="numeric"
              value={String(cuantos)}
              onChange={(e) => setCuantos(Math.max(1, Number(e.target.value) || 1))}
            />
          </div>
          <Button
            variant="outline"
            disabled={cuantos < 2 || partirImporte(Number(monto), cuantos).length === 0}
            onClick={() => {
              const partes = partirImporte(Number(monto), cuantos)
              setDivision({ partes, pagadas: partes.map(() => false) })
            }}
          >
            <Users className="size-4" /> Dividir
          </Button>
        </div>
      ) : (
        <div className="space-y-2 border-t pt-3">
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-medium">
              Dividido en {division.partes.length}
            </span>
            <button
              type="button"
              className="text-sm text-muted-foreground underline-offset-4 hover:underline"
              onClick={() => setDivision(null)}
            >
              Cancelar la división
            </button>
          </div>
          {division.partes.map((parte, i) => (
            <div key={i} className="flex items-center gap-2 text-sm">
              <span className="min-w-0 flex-1 truncate">
                Jugador {i + 1} de {division.partes.length}
              </span>
              <span className="shrink-0 tabular-nums">{pesos(parte)}</span>
              {division.pagadas[i] ? (
                <span className="shrink-0 text-muted-foreground">cobrado</span>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  className="shrink-0"
                  disabled={enviando}
                  onClick={async () => {
                    setEnviando(true)
                    try {
                      await cobroDelTurno.registrar(turno.reserva_id, {
                        monto: String(parte),
                        medio_pago: medio,
                        detalle: `Jugador ${i + 1} de ${division.partes.length}`,
                      })
                      // 🔴 Se marca **esta** parte y no se recalculan las otras:
                      // el importe de los que faltan ya está fijado.
                      setDivision({
                        ...division,
                        pagadas: division.pagadas.map((p, n) => (n === i ? true : p)),
                      })
                      onCobrado()
                    } catch (e) {
                      onError((e as Error).message)
                    } finally {
                      setEnviando(false)
                    }
                  }}
                >
                  Cobrar
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          // Con el QR elegido el cobro lo cierra el poll, no este botón: el
          // único caso en que sigue habilitado es la instancia sin credenciales,
          // donde «mercadopago» significa una transferencia anotada a mano.
          disabled={
            enviando || !monto.trim() || division !== null
            || (porQr && Boolean(qrDeLaInstancia?.disponible))
          }
          onClick={async () => {
            setEnviando(true)
            try {
              await cobroDelTurno.registrar(turno.reserva_id, {
                monto, medio_pago: medio, detalle,
              })
              onCobrado()
            } catch (e) {
              onError((e as Error).message)
            } finally {
              setEnviando(false)
            }
          }}
        >
          {enviando
            ? 'Cobrando…'
            : fraccionado && elegidas.length < lineas.length
              ? 'Cobrar lo seleccionado'
              : 'Cobrar y cerrar la cuenta'}
        </Button>

        {/* 🔴 Cargar buffet acá **no cobra**: le suma a esta cuenta y se cobra
            con el botón de al lado, en una sola operación y un solo
            comprobante. Está junto al cierre a propósito — es lo que se hace
            mientras el turno corre, y mandarlo a otra pantalla es lo que hacía
            que el buffet de la cancha se terminara cobrando aparte. */}
        {sucursalId !== null && (
          <Button variant="outline" onClick={() => setCargandoBuffet(true)}>
            <CupSoda className="size-4" /> Cargar buffet
          </Button>
        )}
      </div>

      {sucursalId !== null && (
        <DialogoDeConsumo
          abierto={cargandoBuffet}
          sucursalId={sucursalId}
          reservaId={turno.reserva_id}
          onCerrar={() => setCargandoBuffet(false)}
          onCargado={() => {
            setCargandoBuffet(false)
            verConsumos()
            onCobrado()
          }}
        />
      )}
    </div>
  )
}

/** La venta de buffet que NO es de una cancha: se cobra en el acto.
 *
 * 🔴 **La diferencia con «Cargar buffet» de una cuenta no es de forma, es de
 * plata.** Acá el consumo se cobra al confirmar; allá no se cobra, se le cuelga
 * al turno. Confundirlas es cobrar dos veces las mismas gaseosas.
 */
function VentaDeMostrador({ sucursalId, onCargado }: {
  sucursalId: number | null
  onCargado: () => void
}) {
  const [abierto, setAbierto] = useState(false)

  if (sucursalId === null) {
    return <p className="text-sm text-muted-foreground">Elegí una sucursal.</p>
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Para quien no está jugando: se cobra al confirmar. Lo que consume una
        cancha abierta se carga desde su cuenta, en «Canchas».
      </p>
      <Button variant="outline" onClick={() => setAbierto(true)}>
        <CupSoda className="size-4" /> Vender del buffet
      </Button>
      <DialogoDeConsumo
        abierto={abierto}
        sucursalId={sucursalId}
        reservaId={null}
        onCerrar={() => setAbierto(false)}
        onCargado={() => {
          setAbierto(false)
          onCargado()
        }}
      />
    </div>
  )
}

/** El ingreso suelto: lo que no es un turno ni una venta de buffet.
 *
 * Es el que estaba desde el principio y el único que **no queda atado a nada**:
 * ni reserva ni comprobante. Sigue existiendo porque en un mostrador entra plata
 * que no es ninguna de las otras dos —una cuota, un alquiler de paletas—, pero
 * es el último de los tres a propósito: usarlo para cobrar un turno es lo que
 * dejaba el comprobante viéndose «sin cobrar» sobre plata que ya había entrado.
 */
function CobroLibre({ medios, onCobrado, onError }: {
  medios: { valor: string; etiqueta: string }[]
  onCobrado: () => void
  onError: (m: string) => void
}) {
  const [monto, setMonto] = useState('')
  const [concepto, setConcepto] = useState('')
  const [medio, setMedio] = useState<string>('')
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!medio && medios.length > 0) setMedio(medios[0].valor)
  }, [medio, medios])

  return (
    <div className="space-y-3">
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
            onCobrado()
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
  )
}

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
