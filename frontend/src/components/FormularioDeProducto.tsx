import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { buffet as api } from '@/lib/api'
import type { ProductoDeBuffet, ProductoEntrada } from '@/lib/api'
import { Input } from '@/components/ui/input'
import { buttonVariants } from '@/components/ui/button'
import { AvisoDeError } from '@/components/listado'

function vacio(): ProductoEntrada {
  return { nombre: '', precio: '', costo: '0', stock_minimo: '0', activo: true }
}

export function FormularioDeProducto({
  abierto,
  producto,
  sucursalId,
  onCerrar,
  onGuardado,
}: {
  abierto: boolean
  /** `null` = alta. */
  producto: ProductoDeBuffet | null
  sucursalId: number
  onCerrar: () => void
  onGuardado: () => void
}) {
  const [datos, setDatos] = useState<ProductoEntrada>(vacio)
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    setDatos(
      producto
        ? {
            nombre: producto.nombre,
            precio: String(producto.precio),
            // El costo no viene en el listado —no se muestra en la tabla— así
            // que al editar arranca en 0. Es el único campo que se pierde, y se
            // deja explícito acá en vez de pedirlo a la API por una columna.
            costo: '0',
            stock_minimo: String(producto.stock_minimo),
            activo: producto.activo,
          }
        : vacio(),
    )
  }, [abierto, producto])

  function set<K extends keyof ProductoEntrada>(campo: K, valor: ProductoEntrada[K]) {
    setDatos((d) => ({ ...d, [campo]: valor }))
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      if (!datos.nombre.trim()) throw new Error('El producto necesita un nombre.')
      if (datos.precio === '' || Number.isNaN(Number(datos.precio)))
        throw new Error('Poné un precio.')
      const cuerpo: ProductoEntrada = {
        ...datos,
        nombre: datos.nombre.trim(),
        precio: Number(datos.precio).toFixed(2),
        costo: Number(datos.costo || 0).toFixed(2),
        stock_minimo: String(Number(datos.stock_minimo || 0)),
      }
      if (producto) await api.editarProducto(sucursalId, producto.item_id, cuerpo)
      else await api.crearProducto(sucursalId, cuerpo)
      onGuardado()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Dialog open={abierto} onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {producto ? `Editar ${producto.nombre}` : 'Nuevo producto del buffet'}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={enviar} className="space-y-3">
          <label className="block space-y-1">
            <span className="text-sm font-medium">Nombre</span>
            <Input value={datos.nombre} onChange={(e) => set('nombre', e.target.value)} />
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="text-sm font-medium">Precio de venta</span>
              <Input
                inputMode="decimal"
                value={datos.precio}
                onChange={(e) => set('precio', e.target.value)}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm font-medium">Costo</span>
              <Input
                inputMode="decimal"
                value={datos.costo}
                onChange={(e) => set('costo', e.target.value)}
              />
            </label>
          </div>

          <label className="block space-y-1">
            <span className="text-sm font-medium">Stock mínimo</span>
            <Input
              inputMode="numeric"
              value={datos.stock_minimo}
              onChange={(e) => set('stock_minimo', e.target.value)}
            />
            {/* Se pide en el alta y no después: un producto sin mínimo nunca
                avisa, y el faltante se descubre cuando el cliente lo pide. */}
            <span className="text-xs text-muted-foreground">
              Debajo de esta cantidad la pantalla avisa que hay que reponer. 0 = no avisa.
            </span>
          </label>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={datos.activo}
              onChange={(e) => set('activo', e.target.checked)}
            />
            Activo
          </label>

          <AvisoDeError mensaje={error} />

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onCerrar}
              className={buttonVariants({ variant: 'outline' })}
            >
              Cancelar
            </button>
            <button type="submit" disabled={enviando} className={buttonVariants()}>
              {enviando ? 'Guardando…' : 'Guardar'}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
