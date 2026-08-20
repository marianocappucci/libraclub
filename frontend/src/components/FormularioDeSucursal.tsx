import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { sucursales as api } from '@/lib/api'
import type { Sucursal, SucursalEntrada } from '@/lib/api'
import { Input } from '@/components/ui/input'
import { buttonVariants } from '@/components/ui/button'
import { AvisoDeError } from '@/components/listado'

function vacia(): SucursalEntrada {
  return {
    nombre: '',
    direccion: null,
    localidad: null,
    telefono: null,
    email: null,
    punto_venta_arca: null,
    activa: true,
    observaciones: null,
  }
}

export function FormularioDeSucursal({
  abierto,
  sucursal,
  onCerrar,
  onGuardada,
}: {
  abierto: boolean
  /** `null` = alta. */
  sucursal: Sucursal | null
  onCerrar: () => void
  onGuardada: () => void
}) {
  const [datos, setDatos] = useState<SucursalEntrada>(vacia)
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    // Se copian todos los campos, no sólo los visibles: el endpoint es un PUT
    // que reemplaza la fila entera.
    setDatos(
      sucursal
        ? {
            nombre: sucursal.nombre,
            direccion: sucursal.direccion,
            localidad: sucursal.localidad,
            telefono: sucursal.telefono,
            email: sucursal.email,
            punto_venta_arca: sucursal.punto_venta_arca,
            activa: sucursal.activa,
            observaciones: sucursal.observaciones,
          }
        : vacia(),
    )
  }, [abierto, sucursal])

  function set<K extends keyof SucursalEntrada>(campo: K, valor: SucursalEntrada[K]) {
    setDatos((d) => ({ ...d, [campo]: valor }))
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      if (!datos.nombre.trim()) throw new Error('La sucursal necesita un nombre.')
      const limpio = (v: string | null) => v?.trim() || null
      const cuerpo: SucursalEntrada = {
        ...datos,
        nombre: datos.nombre.trim(),
        direccion: limpio(datos.direccion),
        localidad: limpio(datos.localidad),
        telefono: limpio(datos.telefono),
        email: limpio(datos.email),
        observaciones: limpio(datos.observaciones),
      }
      if (sucursal) await api.editar(sucursal.id, cuerpo)
      else await api.crear(cuerpo)
      onGuardada()
    } catch (err) {
      // El 409 del backend nombra la constraint y explica por qué: el nombre
      // repetido, o el punto de venta ya usado por otra sucursal.
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  // `onOpenChange` recibe el estado NUEVO. Se llama a `onCerrar` sólo cuando
  // llega `false`: el padre es quien tiene el estado y quien decide. Hoy nunca
  // llega `true` —ninguno de estos diálogos tiene `DialogTrigger`, los abre el
  // padre—, así que el `if` es defensivo. Ver la nota en `dialogos.test.tsx`
  // sobre por qué no se puede cubrir con un test.
  return (
    <Dialog open={abierto} onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{sucursal ? `Editar ${sucursal.nombre}` : 'Nueva sucursal'}</DialogTitle>
        </DialogHeader>
        <form onSubmit={enviar} className="space-y-3">
          <label className="block space-y-1">
            <span className="text-sm font-medium">Nombre</span>
            <Input
              
              value={datos.nombre}
              onChange={(e) => set('nombre', e.target.value)}
            />
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="text-sm font-medium">Dirección</span>
              <Input
                
                value={datos.direccion ?? ''}
                onChange={(e) => set('direccion', e.target.value)}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm font-medium">Localidad</span>
              <Input
                
                value={datos.localidad ?? ''}
                onChange={(e) => set('localidad', e.target.value)}
              />
            </label>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="text-sm font-medium">Teléfono</span>
              <Input
                
                value={datos.telefono ?? ''}
                onChange={(e) => set('telefono', e.target.value)}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm font-medium">Email</span>
              <Input
                
                value={datos.email ?? ''}
                onChange={(e) => set('email', e.target.value)}
              />
            </label>
          </div>

          <label className="block space-y-1">
            <span className="text-sm font-medium">Punto de venta de ARCA</span>
            <Input
              type="number"
              min={1}
              max={99999}
              value={datos.punto_venta_arca ?? ''}
              onChange={(e) =>
                set('punto_venta_arca', e.target.value ? Number(e.target.value) : null)
              }
            />
          </label>
          <p className="text-xs text-muted-foreground">
            Propio de cada sucursal. La numeración de comprobantes es por
            (tipo, punto de venta) y no lleva CUIT: dos sucursales con el mismo
            número se pisan la numeración entre ellas. Se puede dejar vacío hasta
            que la sucursal facture.
          </p>

          <label className="block space-y-1">
            <span className="text-sm font-medium">Observaciones</span>
            <Input
              
              value={datos.observaciones ?? ''}
              onChange={(e) => set('observaciones', e.target.value)}
            />
          </label>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={datos.activa}
              onChange={(e) => set('activa', e.target.checked)}
            />
            Activa
          </label>

          <AvisoDeError mensaje={error} />

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onCerrar}
              className={buttonVariants({ variant: 'outline' })}
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={enviando}
              className={buttonVariants()}
            >
              {enviando ? 'Guardando…' : 'Guardar'}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
