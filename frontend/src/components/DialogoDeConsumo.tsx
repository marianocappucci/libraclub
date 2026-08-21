/** Cargar consumo del buffet: el mismo diálogo para la cancha y el mostrador.
 *
 * 🔑 **Uno solo, y la diferencia es `reservaId`.** Con reserva el consumo se
 * carga a la cancha y **no se cobra** —se cobra al facturar el turno—; sin
 * reserva es una venta de mostrador y pide medio de pago. Duplicar la pantalla
 * habría duplicado también el carrito y el redondeo.
 */
import { useEffect, useMemo, useState } from 'react'
import { Minus, Plus, Trash2 } from 'lucide-react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { MEDIOS_DE_PAGO, buffet } from '@/lib/api'
import type { ProductoDeBuffet } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { buttonVariants } from '@/components/ui/button'

export function DialogoDeConsumo({
  abierto,
  sucursalId,
  reservaId = null,
  onCerrar,
  onCargado,
}: {
  abierto: boolean
  sucursalId: number
  /** `null` = venta de mostrador: se cobra en el acto. */
  reservaId?: number | null
  onCerrar: () => void
  onCargado: () => void
}) {
  const [productos, setProductos] = useState<ProductoDeBuffet[]>([])
  const [carrito, setCarrito] = useState<Record<number, number>>({})
  const [medio, setMedio] = useState<string>(MEDIOS_DE_PAGO[0].valor)
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    setCarrito({})
    buffet
      .productos(sucursalId)
      .then((p) => setProductos(p.filter((x) => x.activo)))
      .catch((e: Error) => setError(e.message))
  }, [abierto, sucursalId])

  const total = useMemo(
    () =>
      Object.entries(carrito).reduce((suma, [id, cant]) => {
        const p = productos.find((x) => x.item_id === Number(id))
        return suma + (p ? p.precio * cant : 0)
      }, 0),
    [carrito, productos],
  )

  function sumar(itemId: number, delta: number) {
    setCarrito((c) => {
      const cant = (c[itemId] ?? 0) + delta
      const { [itemId]: _, ...resto } = c
      return cant > 0 ? { ...resto, [itemId]: cant } : resto
    })
  }

  const lineas = Object.entries(carrito)

  async function cargar() {
    setError(null)
    setEnviando(true)
    try {
      await buffet.consumir(sucursalId, {
        lineas: lineas.map(([id, cant]) => ({ item_id: Number(id), cantidad: String(cant) })),
        reserva_id: reservaId,
        medio_pago: reservaId === null ? medio : null,
      })
      onCargado()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Dialog open={abierto} onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {reservaId === null ? 'Venta de buffet' : 'Cargar consumo a la cancha'}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <AvisoDeError mensaje={error} />

          {productos.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No hay productos cargados en el buffet.
            </p>
          ) : (
            <div className="grid max-h-64 grid-cols-2 gap-2 overflow-y-auto">
              {productos.map((p) => (
                <button
                  key={p.item_id}
                  type="button"
                  onClick={() => sumar(p.item_id, 1)}
                  className="rounded-md border p-2 text-left text-sm hover:bg-muted"
                >
                  <div className="font-medium">{p.nombre}</div>
                  <div className="flex items-center justify-between text-muted-foreground">
                    <span>{pesos(String(p.precio))}</span>
                    {/* 🔑 El stock se muestra al vender, no sólo en la pantalla
                        de stock: el encargado tiene que ver que quedan dos antes
                        de prometer cuatro. */}
                    <span className={p.stock <= 0 ? 'text-amber-700 dark:text-amber-500' : ''}>
                      {p.stock} en stock
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}

          {lineas.length > 0 && (
            <div className="space-y-1 rounded-md border p-2 text-sm">
              {lineas.map(([id, cant]) => {
                const p = productos.find((x) => x.item_id === Number(id))!
                return (
                  <div key={id} className="flex items-center justify-between gap-2">
                    <span className="truncate">{p.nombre}</span>
                    <span className="flex items-center gap-1">
                      <button
                        type="button"
                        aria-label={`Quitar uno de ${p.nombre}`}
                        onClick={() => sumar(p.item_id, -1)}
                        className="rounded border p-1"
                      >
                        {cant === 1 ? <Trash2 className="size-3" /> : <Minus className="size-3" />}
                      </button>
                      <span className="w-6 text-center tabular-nums">{cant}</span>
                      <button
                        type="button"
                        aria-label={`Agregar uno de ${p.nombre}`}
                        onClick={() => sumar(p.item_id, 1)}
                        className="rounded border p-1"
                      >
                        <Plus className="size-3" />
                      </button>
                      <span className="w-20 text-right">{pesos(String(p.precio * cant))}</span>
                    </span>
                  </div>
                )
              })}
              <div className="flex justify-between border-t pt-1 font-medium">
                <span>Total</span>
                <span>{pesos(String(total))}</span>
              </div>
            </div>
          )}

          {reservaId === null ? (
            <label className="block space-y-1">
              <span className="text-sm font-medium">Cobrar con</span>
              <select
                className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
                value={medio}
                onChange={(e) => setMedio(e.target.value)}
              >
                {MEDIOS_DE_PAGO.map((m) => (
                  <option key={m.valor} value={m.valor}>{m.etiqueta}</option>
                ))}
              </select>
            </label>
          ) : (
            <p className="text-sm text-muted-foreground">
              Se carga a la cancha: se cobra y se factura junto con el turno.
            </p>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onCerrar}
              className={buttonVariants({ variant: 'outline' })}
            >
              Cancelar
            </button>
            <button
              type="button"
              disabled={enviando || lineas.length === 0}
              onClick={cargar}
              className={buttonVariants()}
            >
              {enviando ? 'Cargando…' : reservaId === null ? 'Cobrar' : 'Cargar'}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
