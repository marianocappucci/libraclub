import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { clientes as api } from '@/lib/api'
import type { Cliente, ClienteEntrada } from '@/lib/api'
import { Input } from '@/components/ui/input'
import { buttonVariants } from '@/components/ui/button'
import { AvisoDeError } from '@/components/listado'

function vacio(): ClienteEntrada {
  return {
    nombre: '',
    telefono: null,
    email: null,
    documento: null,
    cuit: null,
    activo: true,
    observaciones: null,
  }
}

export function FormularioDeCliente({
  abierto,
  cliente,
  onCerrar,
  onGuardado,
}: {
  abierto: boolean
  /** `null` = alta. */
  cliente: Cliente | null
  onCerrar: () => void
  onGuardado: () => void
}) {
  const [datos, setDatos] = useState<ClienteEntrada>(vacio)
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    setDatos(
      cliente
        ? {
            nombre: cliente.nombre,
            telefono: cliente.telefono,
            email: cliente.email,
            documento: cliente.documento,
            cuit: cliente.cuit,
            activo: cliente.activo,
            observaciones: cliente.observaciones,
          }
        : vacio(),
    )
  }, [abierto, cliente])

  function set<K extends keyof ClienteEntrada>(campo: K, valor: ClienteEntrada[K]) {
    setDatos((d) => ({ ...d, [campo]: valor }))
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      if (!datos.nombre.trim()) throw new Error('El cliente necesita un nombre.')
      const limpio = (v: string | null) => v?.trim() || null
      const cuerpo: ClienteEntrada = {
        ...datos,
        nombre: datos.nombre.trim(),
        telefono: limpio(datos.telefono),
        email: limpio(datos.email),
        documento: limpio(datos.documento),
        cuit: limpio(datos.cuit),
        observaciones: limpio(datos.observaciones),
      }
      if (cliente) await api.editar(cliente.id, cuerpo)
      else await api.crear(cuerpo)
      onGuardado()
    } catch (err) {
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
          <DialogTitle>{cliente ? `Editar ${cliente.nombre}` : 'Nuevo cliente'}</DialogTitle>
        </DialogHeader>
        <form onSubmit={enviar} className="space-y-3">
          <label className="block space-y-1">
            <span className="text-sm font-medium">Nombre</span>
            <Input
              
              value={datos.nombre}
              onChange={(e) => set('nombre', e.target.value)}
            />
          </label>
          <p className="text-xs text-muted-foreground">
            Un solo campo y no nombre + apellido: la reserva se toma por teléfono y
            lo que queda anotado es "Juan de los martes". Partirlo en dos deja dos
            columnas medio vacías y una búsqueda peor.
          </p>

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

          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="text-sm font-medium">Documento</span>
              <Input
                
                value={datos.documento ?? ''}
                onChange={(e) => set('documento', e.target.value)}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm font-medium">CUIT</span>
              <Input
                
                value={datos.cuit ?? ''}
                onChange={(e) => set('cuit', e.target.value)}
              />
            </label>
          </div>
          <p className="text-xs text-muted-foreground">
            Documento y CUIT son texto, no números: un DNI con cero adelante no
            sobrevive a un entero, y el CUIT puede venir con guiones. Hacen falta
            para facturar.
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
              checked={datos.activo}
              onChange={(e) => set('activo', e.target.checked)}
            />
            Activo
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
