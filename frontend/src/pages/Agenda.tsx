import { useCallback, useEffect, useState } from 'react'
import { agenda, canchas as apiCanchas, NOMBRE_DE_DEPORTE } from '@/lib/api'
import type { Cancha, Semana, Turno } from '@/lib/api'
import { diaYMes, hora, lunesDeLaSemana, nombreDelDia, pesos } from '@/lib/fechas'
import { useSucursal } from '@/context/SucursalContext'
import { DialogoDeReserva } from '@/components/DialogoDeReserva'
import { DetalleDeReserva } from '@/components/DetalleDeReserva'
import { AvisoDeConflictos } from '@/components/AvisoDeConflictos'
import { buttonVariants } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { iconoDeDeporte } from '@/lib/deportes'
import { AvisoDeError } from '@/components/listado'
import { sumarDiasISO } from 'libra-ui/fechas'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { ICONOS } from 'libra-ui/iconos-identidad'
import { EtiquetasDeReservaDelNodo } from 'libra-ui/EtiquetasDeReserva'
import { TONOS_ESTADO, type TonoEstado } from 'libra-ui/badge-estado'
import { ETIQUETA_EN_CONFLICTO, ETIQUETA_SIN_SUBIR, esReservaProvisoria, estaEnConflicto } from 'libra-ui/reservas-del-nodo'

/** Los colores por estado. Un solo lugar, para que la leyenda y la grilla no
 *  puedan decir cosas distintas.
 *
 *  ⚠️ **Desde el addendum de ADR-028 sólo pintan lo que no tiene punto de pago**: un
 *  bloqueo, una franja sin tarifa o una instancia sin caja. Un turno con total se
 *  pinta por lo cobrado (`TONO_DEL_COBRO`, más abajo).
 *
 *  🔑 **Estos NO se migran a tokens del tema, y es a propósito.** Es una paleta
 *  de dominio —ámbar lo que falta cerrar, esmeralda lo confirmado, gris lo que
 *  ya pasó—, no cromo de la interfaz. El resto del producto sí usa tokens desde
 *  el 2026-08-20; acá no se puede: `--muted`, `--accent` y `--secondary` son
 *  **los tres `oklch(0.97 0 0)`** en este tema, así que mapear `jugada` y
 *  `bloqueo` a dos de ellos los dejaría del mismo color y el operador perdería
 *  la distinción entre un turno jugado y uno bloqueado.
 *
 *  Si alguna vez hace falta que la grilla siga al tema, el camino es declarar
 *  tokens propios en `index.css` **y verificar en el CSS generado que las
 *  utilidades existan** — ver la nota al pie de ese archivo, que explica por qué
 *  los tres tokens que hubo ahí se sacaron. */
const COLOR: Record<string, string> = {
  provisoria: 'bg-amber-100 text-amber-900 border-amber-300',
  pendiente_pago: 'bg-amber-200 text-amber-950 border-amber-400',
  confirmada: 'bg-emerald-100 text-emerald-900 border-emerald-300',
  jugada: 'bg-slate-200 text-slate-700 border-slate-300',
  bloqueo: 'bg-slate-300 text-slate-800 border-slate-400',
}

/** En qué punto de pago está un turno. El backend lo calcula contra la caja
 *  (`cobro` en cada casillero); acá sólo se dibuja. */
type Cobro = 'cobrado' | 'senado' | 'pendiente'

/** Cada punto de pago, con el tono del kit (`TONOS_ESTADO` de `libra-ui/badge-estado`).
 *
 *  🔑 **Los tonos son los de la familia y no una paleta de este producto.** Ya
 *  traen el color del texto, del borde y del fondo suave en claro y en oscuro, y
 *  su contraste está medido (el `atencion` usa amber-800 por eso mismo: ver la
 *  nota del kit). La grilla no inventa una cuarta forma de decir «ok», «en
 *  curso» y «atención».
 *
 *  - `cobrado` → `ok` (verde): no debe nada.
 *  - `senado` → `curso` (azul): entró algo y falta el resto.
 *  - `pendiente` → `atencion` (ámbar): no entró nada.
 *
 *  🔴 Se elige **la cadena entera** y no se le agrega una clase al color del
 *  estado: el `className` de abajo es un template string sin `cn()`, así que dos
 *  `bg-*` en la misma lista no se resuelven por orden de escritura sino por el
 *  orden en que Tailwind los emitió en la hoja. Con una cadena por caso no hay
 *  nada que competir. */
const TONO_DEL_COBRO: Record<Cobro, TonoEstado> = {
  cobrado: 'ok',
  senado: 'curso',
  pendiente: 'atencion',
}

/** La palabra de cada punto de pago. */
const PALABRA_DEL_COBRO: Record<Cobro, string> = {
  cobrado: 'cobrado',
  senado: 'señado',
  pendiente: 'sin cobrar',
}

/** Lo que falta cobrar, escrito para el casillero: vacío si ya no falta nada o no se sabe. */
function faltaDelCobro(cobro: Cobro, saldo: string | number | null | undefined): string {
  if (cobro === 'cobrado' || saldo === null || saldo === undefined) return ''
  const monto = pesos(String(saldo))
  // Con seña, lo que falta; sin nada, lo que se debe.
  return cobro === 'senado' ? `falta ${monto}` : monto
}

/** El rótulo entero, para el nombre accesible: «señado · falta $ 6.000,00». */
function rotuloDelCobro(cobro: Cobro, saldo: string | number | null | undefined): string {
  return [PALABRA_DEL_COBRO[cobro], faltaDelCobro(cobro, saldo)].filter(Boolean).join(' · ')
}

/** El punto de pago de un casillero. Un backend anterior sólo mandaba `cobrado`. */
function cobroDe(turno: Turno): Cobro | null {
  if (turno.cobro) return turno.cobro
  return turno.cobrado ? 'cobrado' : null
}

/** El estado de la reserva, cuando dice algo que el color de cobro no dice. Una
 *  confirmada es lo normal y no lleva palabra. */
const PALABRA_DEL_ESTADO: Record<string, string> = {
  jugada: 'jugada',
  provisoria: 'provisoria',
  pendiente_pago: 'espera la seña',
}

interface Seleccion {
  cancha: Cancha
  turno: Turno
}

export function Agenda() {
  const { actual, cargando: cargandoSucursal } = useSucursal()
  const [desde, setDesde] = useState(() => lunesDeLaSemana())
  const [semana, setSemana] = useState<Semana | null>(null)
  const [canchas, setCanchas] = useState<Cancha[]>([])
  //: Qué cancha se está mirando. `null` hasta que llegue el listado.
  //
  //: 🔑 Se guarda el **id** y no el índice: al cambiar de sucursal la lista es
  //: otra, y un índice apuntaría a la cancha que ocupe ese lugar en la nueva.
  const [elegida, setElegida] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)
  const [nueva, setNueva] = useState<Seleccion | null>(null)
  const [detalle, setDetalle] = useState<Seleccion | null>(null)

  const recargar = useCallback(() => {
    if (actual === null) return
    setCargando(true)
    setError(null)
    Promise.all([agenda.semana(actual, desde), apiCanchas.listar()])
      .then(([s, c]) => {
        setSemana(s)
        setCanchas(c.filter((x) => x.sucursal_id === actual && x.activa))
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [actual, desde])

  useEffect(recargar, [recargar])

  if (cargandoSucursal) return <p className="text-muted-foreground">Cargando…</p>
  if (actual === null)
    return (
      <p className="text-muted-foreground">
        No hay ninguna sucursal activa. Creá una antes de usar la agenda.
      </p>
    )

  // Los siete días se derivan de `semana.desde` y no de las claves de la
  // primera cancha: con la primera cancha sin turnos —un feriado cerrado, por
  // ejemplo— la grilla entera se quedaba sin columnas.
  const dias = semana ? Array.from({ length: 7 }, (_, i) => sumarDiasISO(semana.desde, i)) : []

  // La cancha que se muestra. Cae a la primera cuando la elegida no está en la
  // lista: pasa al cambiar de sucursal, y también si se da de baja la que se
  // estaba mirando. Sin la caída, la agenda quedaría en blanco sin decir por qué.
  const activa = canchas.find((c) => c.id === elegida) ?? canchas[0] ?? null

  function elegir(cancha: Cancha, turno: Turno) {
    if (turno.libre) setNueva({ cancha, turno })
    else setDetalle({ cancha, turno })
  }

  return (
    <div className="space-y-4">
      {/* La barra de la agenda: el título y el salto de semana, pegados arriba.
       *
       * 🔑 **La agenda no tenía título de pantalla** y era la única así: su
       * único `<h2>` era el encabezado de cada cancha, adentro del `.map()`. El
       * guard de iconos lo tenía anotado como excepción documentada desde que se
       * escribió; con el título puesto, esa excepción se retira.
       *
       * 🔑 **Sticky, y medido en un navegador antes de elegir el `top`.** Con
       * esta misma cadena de contenedores —`main` con `p-4 pt-12 md:p-6`, la
       * pantalla en `space-y-4`— la barra arranca a 48px y al scrollear queda
       * clavada en **0**, sin dejar franja de contenido asomando arriba, y sin
       * que nada pase por los costados: los 16px laterales son el padding del
       * `main`, donde no hay filas. Es el mismo tipo de arnés con el que
       * LibraDesk midió su barra de abajo.
       *
       * `sticky` y no `fixed`: tiene que respetar el ancho de la columna de
       * contenido, que cambia según la sidebar esté abierta, cerrada o en
       * mobile. Un `fixed` se posiciona contra el viewport y cruzaría por debajo
       * del menú.
       *
       * El fondo **opaco** no es decorativo: la grilla pasa por debajo.
       */}
      <div className="sticky top-0 z-20 -mx-1 space-y-3 rounded-lg border bg-card px-3 py-3 shadow-sm">
        <TituloPantalla icono={ICONOS.agenda}>Agenda</TituloPantalla>

      {/* 🔴 `flex-wrap`: los botones de `buttonVariants` traen `whitespace-nowrap`
          y `shrink-0`, así que la fila NO se puede encoger. Sin envolver, en un
          teléfono de 375px se sale 61px y arrastra al `<body>` con ella.
          Medido, y **lo introdujo la migración de colores del 2026-08-20**: los
          botones escritos a mano de antes no traían esas dos clases y el texto
          les envolvía adentro. Mismo criterio que `EncabezadoDePantalla` de
          `libra-ui`, que envuelve por esta misma razón. */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          className={buttonVariants({ variant: 'outline', size: 'sm' })}
          onClick={() => setDesde(sumarDiasISO(desde, -7))}
        >
          ← Semana anterior
        </button>
        <button
          className={buttonVariants({ variant: 'outline', size: 'sm' })}
          onClick={() => setDesde(lunesDeLaSemana())}
        >
          Esta semana
        </button>
        <button
          className={buttonVariants({ variant: 'outline', size: 'sm' })}
          onClick={() => setDesde(sumarDiasISO(desde, 7))}
        >
          Semana siguiente →
        </button>
        {cargando && <span className="text-sm text-muted-foreground">actualizando…</span>}
      </div>

      {/* Una cancha por vez, elegida acá.
       *
       * 🔑 **Antes se apilaban todas**, una debajo de la otra: con cuatro
       * canchas la pantalla eran cuatro grillas de siete días y para ver la
       * última había que scrollear más allá de las otras tres. Un complejo mira
       * **una** cancha a la vez.
       *
       * Las pestañas van adentro de la barra pegada, con la navegación de
       * semana: son las dos cosas que mueven lo que se está mirando, y tenerlas
       * a mano es justamente para lo que la barra queda arriba.
       *
       * `overflow-x-auto` porque la tira crece con el complejo: con ocho canchas
       * no entra, y sin esto arrastra el ancho de la página entera. */}
      {canchas.length > 1 && (
        <div className="-mx-1 overflow-x-auto px-1">
          <Tabs
            value={activa ? String(activa.id) : ''}
            onValueChange={(v) => setElegida(Number(v))}
          >
            <TabsList>
              {canchas.map((c) => (
                <TabsTrigger key={c.id} value={String(c.id)} className="gap-1.5">
                  {/* El icono dice de qué es la cancha sin leer: con seis
                      pestañas, el nombre solo obliga a leerlas todas. */}
                  {(() => {
                    const Icono = iconoDeDeporte(c.deporte)
                    return <Icono aria-hidden className="size-4 shrink-0" />
                  })()}
                  {c.nombre}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>
      )}
      </div>

      <LeyendaDeCobro />

      <AvisoDeError mensaje={error} />

      {/* Las reservas que se dieron en el club sin conexión y chocaron (ADR-022). No ocupan la cancha, así que la
          grilla no las dibuja: sin este aviso quedarían invisibles. Sin conflictos no dibuja nada. */}
      <AvisoDeConflictos sucursalId={actual} onResuelto={recargar} />

      {/*
        🔴 Se distingue "no hay canchas" de "no hay turnos". Una pantalla vacía
        sin explicación se lee como un error del sistema, y lo que falta es una
        cancha cargada.
      */}
      {canchas.length === 0 && !cargando && (
        <p className="text-muted-foreground">
          Esta sucursal todavía no tiene canchas cargadas.
        </p>
      )}

      {(activa ? [activa] : []).map((cancha) => (
        <section key={cancha.id} className="rounded-lg border bg-card">
          <h2 className="encabezado-de-cancha border-b px-4 py-2 font-medium">
            {cancha.nombre}
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              {NOMBRE_DE_DEPORTE[cancha.deporte] ?? cancha.deporte} · turnos de {cancha.duracion_turno_min} min
            </span>
          </h2>
          <div className="overflow-x-auto">
            <div className="flex min-w-max gap-3 p-3">
              {dias.map((dia) => (
                <div key={dia} className="w-40 shrink-0">
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {nombreDelDia(dia)} {diaYMes(dia)}
                  </p>
                  <div className="space-y-1">
                    {(semana?.canchas[String(cancha.id)]?.[dia] ?? []).map((t) => (
                      <Casillero
                        key={t.comienza_at}
                        turno={t}
                        onElegir={() => elegir(cancha, t)}
                      />
                    ))}
                    {(semana?.canchas[String(cancha.id)]?.[dia] ?? []).length === 0 && (
                      <p className="text-xs text-muted-foreground">Cerrado</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      ))}

      <DialogoDeReserva
        abierto={nueva !== null}
        cancha={nueva?.cancha ?? null}
        turno={nueva?.turno ?? null}
        onCerrar={() => setNueva(null)}
        onCreada={() => {
          setNueva(null)
          recargar()
        }}
      />

      <DetalleDeReserva
        abierto={detalle !== null}
        cancha={detalle?.cancha ?? null}
        turno={detalle?.turno ?? null}
        onCerrar={() => setDetalle(null)}
        onCambiada={() => {
          setDetalle(null)
          recargar()
        }}
      />
    </div>
  )
}

function Casillero({ turno, onElegir }: { turno: Turno; onElegir: () => void }) {
  const etiqueta = turno.libre
    ? `Reservar ${hora(turno.comienza_at)}`
    : `Ver la reserva de ${hora(turno.comienza_at)}`

  if (turno.libre) {
    return (
      <button
        type="button"
        onClick={onElegir}
        aria-label={etiqueta}
        className="w-full rounded-md border border-dashed px-2 py-1 text-left text-xs text-muted-foreground hover:border-ring hover:bg-accent hover:text-accent-foreground"
      >
        <div className="font-medium">{hora(turno.comienza_at)}</div>
        {/* Un turno sin precio se muestra igual, diciendo que falta la tarifa.
            Esconderlo dejaría invisible la franja sin precio cargado. */}
        <div className={turno.precio ? 'text-muted-foreground' : 'text-amber-700 dark:text-amber-400'}>
          {turno.precio ? pesos(turno.precio) : 'sin tarifa'}
        </div>
      </button>
    )
  }
  // Con punto de pago, el color es el del cobro: lo que el operador quiere ver de
  // un vistazo es qué le queda por cobrar. Sin él (un bloqueo, una franja sin
  // tarifa, una instancia sin caja) queda el color del estado de la reserva.
  const cobro = cobroDe(turno)
  const color = cobro
    ? TONOS_ESTADO[TONO_DEL_COBRO[cobro]]
    : COLOR[turno.estado ?? ''] ?? 'bg-muted border-border'
  const palabraDelEstado = cobro && turno.estado ? PALABRA_DEL_ESTADO[turno.estado] : undefined
  const falta = cobro ? faltaDelCobro(cobro, turno.saldo) : ''
  // Lo que dice el nodo de esta reserva (libra-ui ADR-094): dada en el club sin conexión y todavía sin subir (id negativo), o en conflicto.
  const sinSubir = esReservaProvisoria(turno.reserva_id)
  const enConflicto = estaEnConflicto(turno.estado)
  return (
    <button
      type="button"
      onClick={onElegir}
      // 🔑 El estado va también en el nombre accesible. El color y el punto no
      // los lee un lector de pantalla, y el que opera con uno necesita saber
      // qué turno ya está cerrado tanto como el que mira la grilla.
      aria-label={[
        etiqueta,
        cobro && rotuloDelCobro(cobro, turno.saldo),
        palabraDelEstado,
        sinSubir && ETIQUETA_SIN_SUBIR.toLowerCase(),
        enConflicto && ETIQUETA_EN_CONFLICTO.toLowerCase(),
      ].filter(Boolean).join(', ')}
      className={`w-full rounded-md border px-2 py-1 text-left text-xs hover:brightness-95 ${color}`}
    >
      <div className="font-medium">{hora(turno.comienza_at)}</div>
      <div className="truncate">{turno.cliente ?? turno.motivo ?? 'Ocupado'}</div>
      {/* 🔴 «Sin subir al central» y NO «Provisoria»: `provisoria` es el turno retenido esperando el pago del portal. Sin nodo no dibuja nada. */}
      <EtiquetasDeReservaDelNodo
        id={turno.reserva_id}
        estado={turno.estado}
        className="mt-0.5 flex flex-wrap items-center gap-1"
      />
      {/* 🔴 **El punto Y la palabra, las dos cosas.** Es la misma decisión que
          los movimientos anulados del 2026-08-28: sólo el color se pierde en
          una impresión en blanco y negro y no lo lee un lector de pantalla;
          sólo la palabra se pierde entre los casilleros de una semana.

          Dos renglones y no uno: el casillero mide 160 px y «señado · falta
          $ 5.000,00» no entra sin cortarse, que es justo el dato que se mira. */}
      {cobro && (
        <>
          <div className="mt-0.5 flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide">
            <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-current" />
            <span className="truncate">{PALABRA_DEL_COBRO[cobro]}</span>
            {/* El estado va donde haya lugar: con un monto debajo, al lado del
                monto; sin él (cobrado), al lado de la palabra. */}
            {palabraDelEstado && !falta && (
              <span className="ml-auto truncate font-normal opacity-80">{palabraDelEstado}</span>
            )}
          </div>
          {falta && (
            <div className="flex items-baseline gap-1 text-[11px]">
              <span className="tabular-nums">{falta}</span>
              {palabraDelEstado && (
                <span className="ml-auto truncate text-[10px] font-normal uppercase tracking-wide opacity-80">
                  {palabraDelEstado}
                </span>
              )}
            </div>
          )}
        </>
      )}
    </button>
  )
}

/** Qué quiere decir cada color de la grilla. Los mismos tonos que los casilleros:
 *  si la leyenda y la grilla salieran de dos lugares, un día dirían cosas distintas. */
function LeyendaDeCobro() {
  const items: { cobro: Cobro; texto: string }[] = [
    { cobro: 'cobrado', texto: 'Cobrado' },
    { cobro: 'senado', texto: 'Señado, falta el resto' },
    { cobro: 'pendiente', texto: 'Sin cobrar' },
  ]
  return (
    <ul aria-label="Leyenda de la agenda" className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
      {items.map((i) => (
        <li key={i.cobro} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={`inline-block size-3.5 rounded-sm border ${TONOS_ESTADO[TONO_DEL_COBRO[i.cobro]]}`}
          />
          {i.texto}
        </li>
      ))}
      <li className="flex items-center gap-1.5 text-muted-foreground">
        <span aria-hidden className={`inline-block size-3.5 rounded-sm border ${COLOR.bloqueo}`} />
        Bloqueo o sin precio
      </li>
      <li className="flex items-center gap-1.5 text-muted-foreground">
        <span aria-hidden className="inline-block size-3.5 rounded-sm border border-dashed" />
        Libre
      </li>
    </ul>
  )
}
