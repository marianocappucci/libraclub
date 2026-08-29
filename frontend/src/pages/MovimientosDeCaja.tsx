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
import { ArrowLeft, Ban, Wallet } from 'lucide-react'

import { caja } from '@/lib/api'
import type { ResumenDeCaja, TurnoDeCaja } from '@/lib/api'
import { useMediosDePago } from '@/lib/medios-pago'
import { hora, pesos } from '@/lib/fechas'
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
      <p className="text-sm text-muted-foreground">
        Todavía no cargaste nada en este turno.
      </p>
    )
  }

  return (
    // 🔑 **Una tabla con columnas, no una fila de texto.** Pedido del humano el
    // 2026-08-28: *"los movimientos se deberían tener que ver en una tabla con
    // columnas"*. Con veinte filas, el formato viejo —concepto y medio en una
    // línea corrida, el importe pegado a la derecha— no se puede leer ni sumar
    // con la vista, y no mostraba la hora.
    //
    // `overflow-x-auto` en el contenedor y no en la página: una tabla ancha
    // scrollea sola en el celular sin arrastrar el resto de la pantalla.
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-2 pr-3 font-medium">Hora</th>
            <th className="py-2 pr-3 font-medium">Concepto</th>
            <th className="py-2 pr-3 font-medium">Medio</th>
            {/* Los importes con el encabezado a la derecha, sobre la columna
                que alinean: un título a la izquierda de números alineados a la
                derecha obliga a buscar cuál es cuál. */}
            <th className="py-2 pr-3 text-right font-medium">Importe</th>
            <th className="py-2 w-9" aria-label="Acciones" />
          </tr>
        </thead>
        <tbody>
          {movimientos.map((m) => {
            const anulado = m.anulado === 1
            return (
              <tr
                key={m.id}
                className={`border-b last:border-0${anulado ? ' text-muted-foreground' : ''}`}
              >
                <td className="py-1.5 pr-3 tabular-nums whitespace-nowrap">
                  {hora(m.fecha)}
                </td>
                <td className="py-1.5 pr-3">
                  {/* 🔴 Tachado **y** con la palabra. Sólo el tachado se pierde
                      en una impresión en blanco y negro y no lo lee un lector de
                      pantalla; sólo la palabra se pierde entre veinte filas. */}
                  <span className={anulado ? 'line-through' : undefined}>{m.concepto}</span>
                  {anulado && (
                    <span className="ml-2 rounded border px-1 text-xs">anulado</span>
                  )}
                </td>
                <td className="py-1.5 pr-3 whitespace-nowrap">
                  {etiquetaDeMedio(m.medio_pago)}
                </td>
                <td
                  className={
                    'py-1.5 pr-3 text-right tabular-nums whitespace-nowrap'
                    + (m.tipo === 'egreso' && !anulado
                      ? ' text-amber-700 dark:text-amber-500' : '')
                    + (anulado ? ' line-through' : '')
                  }
                >
                  {/* El egreso en negativo: es lo que hace que la columna se
                      pueda sumar de arriba abajo y dé el esperado. */}
                  {m.tipo === 'egreso' ? '−' : ''}{pesos(String(m.monto))}
                </td>
                <td className="py-1.5">
                  {/* Un anulado no se vuelve a anular: el botón desaparece en vez
                      de quedar deshabilitado, que invita a apretarlo. */}
                  {!anulado && (
                    <Button
                      variant="outline"
                      size="icon"
                      className="size-7"
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
                      <Ban className="size-3.5" />
                    </Button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
