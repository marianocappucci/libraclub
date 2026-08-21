import { useCallback, useEffect, useState } from 'react'
import { agenda, canchas as apiCanchas } from '@/lib/api'
import type { Cancha, Semana, Turno } from '@/lib/api'
import { hora, lunesDeLaSemana, nombreDelDia, pesos } from '@/lib/fechas'
import { useSucursal } from '@/context/SucursalContext'
import { DialogoDeReserva } from '@/components/DialogoDeReserva'
import { DetalleDeReserva } from '@/components/DetalleDeReserva'
import { buttonVariants } from '@/components/ui/button'
import { AvisoDeError } from '@/components/listado'

/** Los colores por estado. Un solo lugar, para que la leyenda y la grilla no
 *  puedan decir cosas distintas.
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

interface Seleccion {
  cancha: Cancha
  turno: Turno
}

export function Agenda() {
  const { actual, cargando: cargandoSucursal } = useSucursal()
  const [desde, setDesde] = useState(() => lunesDeLaSemana())
  const [semana, setSemana] = useState<Semana | null>(null)
  const [canchas, setCanchas] = useState<Cancha[]>([])
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
  const dias = semana ? Array.from({ length: 7 }, (_, i) => correr(semana.desde, i)) : []

  function elegir(cancha: Cancha, turno: Turno) {
    if (turno.libre) setNueva({ cancha, turno })
    else setDetalle({ cancha, turno })
  }

  return (
    <div className="space-y-4">
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
          onClick={() => setDesde(correr(desde, -7))}
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
          onClick={() => setDesde(correr(desde, 7))}
        >
          Semana siguiente →
        </button>
        {cargando && <span className="text-sm text-muted-foreground">actualizando…</span>}
      </div>

      <AvisoDeError mensaje={error} />

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

      {canchas.map((cancha) => (
        <section key={cancha.id} className="rounded-lg border bg-card">
          <h2 className="border-b px-4 py-2 font-medium">
            {cancha.nombre}
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              {cancha.deporte} · turnos de {cancha.duracion_turno_min} min
            </span>
          </h2>
          <div className="overflow-x-auto">
            <div className="flex min-w-max gap-3 p-3">
              {dias.map((dia) => (
                <div key={dia} className="w-40 shrink-0">
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {nombreDelDia(dia)} {dia.slice(8, 10)}/{dia.slice(5, 7)}
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
        <div className={turno.precio ? 'text-muted-foreground' : 'text-amber-700'}>
          {turno.precio ? pesos(turno.precio) : 'sin tarifa'}
        </div>
      </button>
    )
  }
  const color = COLOR[turno.estado ?? ''] ?? 'bg-muted border-border'
  return (
    <button
      type="button"
      onClick={onElegir}
      aria-label={etiqueta}
      className={`w-full rounded-md border px-2 py-1 text-left text-xs hover:brightness-95 ${color}`}
    >
      <div className="font-medium">{hora(turno.comienza_at)}</div>
      <div className="truncate">{turno.cliente ?? turno.motivo ?? 'Ocupado'}</div>
    </button>
  )
}

function correr(iso: string, dias: number): string {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + dias)
  return d.toISOString().slice(0, 10)
}
