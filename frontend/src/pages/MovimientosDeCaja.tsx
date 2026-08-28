/** El detalle de lo que se movio en el turno de caja abierto.
 *
 * 🔴 **Vive en su propia pantalla desde el 2026-08-28**, y no adentro de la
 * Caja. El pedido del humano fue explicito: *"lo que la caja mueva entre todas
 * las canchas no tiene por que verse en la pantalla de caja"*. La unidad de
 * trabajo del mostrador es **la cuenta de una cancha** —ir a un turno, a nombre
 * de alguien, y cerrarlo—; una lista con los movimientos de todas mezclados
 * compite con eso y ademas invita a buscar ahi lo que se cierra del otro lado.
 *
 * 🔑 **Y no es una pantalla de adorno: es donde se anula.** Sacar la lista de
 * la Caja sin darle un lugar habria dejado sin camino al unico boton que
 * corrige un cobro mal cargado, que es la razon por la que se mudo en vez de
 * borrarse.
 *
 * Los totales —lo que se necesita para el arqueo— siguen en la Caja: lo que se
 * partio es el detalle, no el numero que se mira al cerrar.
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { ArrowLeft, Trash2, Wallet } from 'lucide-react'

import { caja } from '@/lib/api'
import type { ResumenDeCaja, TurnoDeCaja } from '@/lib/api'
import { useMediosDePago } from '@/lib/medios-pago'
import { pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

export function MovimientosDeCaja() {
  const [turno, setTurno] = useState<TurnoDeCaja | null>(null)
  const [resumen, setResumen] = useState<ResumenDeCaja | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const { etiqueta: etiquetaDeMedio } = useMediosDePago()

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

  return (
    <div className="space-y-4">
      {/* 🔑 **El icono es el de la Caja, no uno propio.** Lo reclamó el guard de
          `titulos-con-icono`, y tiene razón: el título lleva el icono de la
          entrada del sidebar a la que la pantalla pertenece. Ésta es una
          subpágina de /caja, así que darle uno propio diría que es otra sección
          del menú — y no hay ninguna. */}
      <EncabezadoDePantalla
        titulo={<TituloPantalla icono={Wallet}>Movimientos del turno</TituloPantalla>}
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
      ) : turno === null ? (
        /* Sin turno abierto no hay movimientos que listar, y decirlo es mejor
           que una lista vacia: son dos situaciones distintas. */
        <p className="text-muted-foreground">
          No hay una caja abierta. Abrila desde <Link to="/caja" className="underline">la caja</Link>.
        </p>
      ) : (
        <div className="rounded-lg border bg-card p-4">
          <Movimientos
            movimientos={resumen?.movimientos ?? []}
            etiquetaDeMedio={etiquetaDeMedio}
            onAnulado={recargar}
            onError={setError}
          />
        </div>
      )}
    </div>
  )
}

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
    // 🔴 `flex flex-col` y **no** `grid gap-1`, que es lo que había.
    //
    // Un grid implícito dimensiona su columna a `max-content`, así que la fila
    // crecía con el concepto más largo y se llevaba el importe y el botón fuera
    // de la tarjeta — con el `min-w-0` puesto en la fila **y** en el texto, que
    // no alcanzan. Medido en un navegador: la fila daba 554 dentro de un padre
    // de 424; con `flex flex-col` da 424, y con `grid-cols-[minmax(0,1fr)]`
    // también. Se elige el flex por ser el idioma del resto de la pantalla.
    <div className="flex flex-col gap-1 border-t pt-3">
      <div className="text-sm font-medium">Movimientos</div>
      {movimientos.map((m) => (
        <div key={m.id} className="flex min-w-0 items-center gap-2 text-sm">
          {/* 🔴 `min-w-0` en la fila **y** en el texto. Sin el de la fila, el
              `flex-1 truncate` del hijo no tiene contra qué achicarse: el
              contenido empuja y el importe y el botón se salen de la tarjeta.
              Medido en un navegador, no supuesto. */}
          <span className="min-w-0 flex-1 truncate" title={m.concepto}>
            {m.concepto}
            <span className="ml-1 text-muted-foreground">
              · {etiquetaDeMedio(m.medio_pago)}
            </span>
          </span>
          {/* El egreso se muestra en negativo: es lo que hace que la lista se
              pueda sumar de arriba abajo y dé el esperado.

              `shrink-0` y `tabular-nums`: el importe no se parte, y los dígitos
              quedan en columna para poder sumarlos con la vista. */}
          <span className={`shrink-0 tabular-nums${m.tipo === 'egreso' ? ' text-amber-700 dark:text-amber-500' : ''}`}>
            {m.tipo === 'egreso' ? '−' : ''}{pesos(String(m.monto))}
          </span>
          <Button
            variant="outline"
            size="icon"
            className="size-7 shrink-0"
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
            {/* Icono y no la palabra: con el texto, la acción se comía el
                ancho de una fila que ya lleva concepto, medio e importe.
                El nombre accesible lo da el `aria-label`, que además nombra
                **cuál** movimiento — con veinte filas, veinte «Anular»
                idénticos no le sirven a nadie que use lector de pantalla. */}
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      ))}
    </div>
  )
}
