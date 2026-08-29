/** Lo que las cuatro pantallas de listado repetían.
 *
 *  Canchas, Clientes, Sucursales y Tarifas tenían las mismas tres cosas escritas
 *  a mano cuatro veces: el aviso de error, la celda con Editar/Borrar y el
 *  ancho de esa columna. No es una pantalla genérica como el `AbmMaestro` de
 *  LibraCargo —acá cada maestro tiene su propio formulario con reglas de
 *  dominio propias, y meterlos en un molde común sería perderlas—: son sólo las
 *  piezas comunes.
 */
import type { ColumnDef } from '@tanstack/react-table'
import { Pencil, Trash2 } from 'lucide-react'
import { anchoColumnaAcciones } from 'libra-ui/data-table'

import { Button } from '@/components/ui/button'

/** El error de la API, arriba de la tabla.
 *
 *  `role="alert"` para que un lector de pantalla lo anuncie sin que haya que ir
 *  a buscarlo: aparece después de una acción, y quien la disparó puede tener el
 *  foco en otro lado.
 */
export function AvisoDeError({ mensaje }: { mensaje: string | null }) {
  if (!mensaje) return null
  return (
    <p
      role="alert"
      className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
    >
      {mensaje}
    </p>
  )
}

/** La columna de Editar y Borrar, al extremo derecho.
 *
 *  🔑 **Lleva título y los botones llevan borde**, que es la convención de la
 *  familia y lo que hace Contalibra en 12 de sus 17 columnas de acciones. Hasta
 *  el 2026-08-28 acá el `header` era `''` y los botones `ghost`: una columna sin
 *  encabezado en una tabla que sí lo tiene en todas las demás, y dos iconos
 *  sueltos sin nada que los delimite. El día que entró la bandeja de MercadoPago
 *  —que viene del kit y usa `outline`— quedaron los dos estilos en la misma app.
 *
 *  El `size` sale de `anchoColumnaAcciones` del kit y no de un número escrito
 *  acá: TanStack le da 150px por default a toda columna, que en esta sobra y le
 *  come lugar a las que tienen datos.
 *
 *  🔑 El `aria-label` lleva el nombre de la fila ("Editar Cancha 1"), no un
 *  "Editar" pelado. Con 40 filas, un lector de pantalla anuncia 40 botones
 *  idénticos y no hay forma de saber cuál es cuál. El texto visible no cambia:
 *  los botones siguen siendo sólo el icono.
 */
export function columnaDeAcciones<T>({ onEditar, onBorrar, nombreDe }: {
  onEditar: (fila: T) => void
  onBorrar: (fila: T) => void
  /** Cómo se nombra la fila en el `aria-label` de cada botón. */
  nombreDe: (fila: T) => string
}): ColumnDef<T, unknown> {
  return {
    id: 'acciones',
    header: () => <div className="text-right">Acciones</div>,
    size: anchoColumnaAcciones(2),
    // Sin ordenar ni buscar: no hay dato acá.
    enableSorting: false,
    cell: ({ row }: { row: { original: T } }) => (
      <div className="flex justify-end gap-1">
        <Button
          variant="outline"
          size="icon"
          aria-label={`Editar ${nombreDe(row.original)}`}
          onClick={() => onEditar(row.original)}
        >
          <Pencil className="size-4" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label={`Borrar ${nombreDe(row.original)}`}
          onClick={() => onBorrar(row.original)}
        >
          <Trash2 className="size-4" />
        </Button>
      </div>
    ),
  } as ColumnDef<T, unknown>
}

/** La clase de una fila dada de baja: atenuada, como en el resto de la familia. */
export function filaInactiva(activa: boolean): string | undefined {
  return activa ? undefined : 'opacity-50'
}
