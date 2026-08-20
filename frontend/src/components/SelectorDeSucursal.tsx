/** El selector de sucursal activa. **Vive en el menú del usuario**, en el pie
 *  del sidebar (`userMenu` de `libra-ui/Layout`, v0.20.0) — mismo lugar que en
 *  LibraDesk, que es el otro producto de la familia con sucursal transversal.
 *
 *  Hasta el 2026-08-20 era un `<select>` suelto en el encabezado propio. Se
 *  mueve acá al adoptar el Layout del kit, que no tiene encabezado: la barra
 *  superior se eliminó en v0.19.0 para los seis productos.
 *
 *  > ⚠️ **En LibraClub la sucursal no se puede esconder del todo.** A
 *  > diferencia de LibraDesk —donde el default es "todas" y no filtra nada—
 *  > acá la sucursal es obligatoria y filtra la agenda, las canchas y las
 *  > tarifas: una pantalla filtrada se ve igual que una completa. Por eso el
 *  > nombre de la sucursal elegida se dibuja **siempre**, bajo "LibraClub" en
 *  > el encabezado del sidebar (`getUserSubtitle` en `Layout.tsx`), y este
 *  > selector es sólo el control para cambiarla.
 *
 *  No se renderiza con menos de dos sucursales: con una no ofrece ninguna
 *  decisión y con cero no hay concepto. Es la misma condición que tenía el
 *  `<select>` del encabezado viejo (`sucursales.length > 1`).
 */
import { MapPin } from 'lucide-react'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useSucursal } from '@/context/SucursalContext'

export function SelectorDeSucursal() {
  const { sucursales, actual, elegir } = useSucursal()
  if (sucursales.length < 2) return null
  return (
    <div className="grid gap-2">
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <MapPin className="h-3.5 w-3.5" />
        Sucursal
      </span>
      {/* Sin opción "todas", a diferencia de LibraDesk: `elegir` recibe un
          `number` y la agenda necesita UNA sucursal para poder dibujar la
          grilla. El contexto garantiza que `actual` sea una sucursal activa
          existente, así que el `value` siempre matchea un `SelectItem`. */}
      <Select
        value={actual === null ? '' : String(actual)}
        onValueChange={(v) => elegir(Number(v))}
      >
        <SelectTrigger className="h-8 w-full" aria-label="Sucursal">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {sucursales.map((s) => (
            <SelectItem key={s.id} value={String(s.id)}>
              {s.nombre}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
