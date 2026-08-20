import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

/**
 * Un diálogo modal sobre `<dialog>` nativo.
 *
 * Nativo y no un div con `position: fixed` porque el navegador ya trae lo que
 * hay que hacer bien: foco atrapado adentro, `Escape` que cierra, y el resto de
 * la página marcada como inerte para el lector de pantalla. Reimplementar eso a
 * mano es donde aparecen los modales que se cierran haciendo Tab.
 */
export function Modal({
  abierto,
  titulo,
  onCerrar,
  children,
}: {
  abierto: boolean
  titulo: string
  onCerrar: () => void
  children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialogo = ref.current
    if (!dialogo) return
    // `showModal()` y no el atributo `open`: el atributo muestra el diálogo
    // pero **no** activa el modo modal, así que no atrapa el foco ni escucha
    // Escape. Se ve igual y se comporta distinto.
    if (abierto && !dialogo.open) dialogo.showModal()
    if (!abierto && dialogo.open) dialogo.close()
  }, [abierto])

  return (
    <dialog
      ref={ref}
      onClose={onCerrar}
      onCancel={onCerrar}
      className="w-full max-w-md rounded-lg border border-slate-200 p-0 backdrop:bg-slate-900/40"
      aria-label={titulo}
    >
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h2 className="font-semibold">{titulo}</h2>
        <button
          type="button"
          onClick={onCerrar}
          aria-label="Cerrar"
          className="rounded-md px-2 py-1 text-slate-500 hover:bg-slate-100"
        >
          ✕
        </button>
      </div>
      <div className="px-4 py-4">{children}</div>
    </dialog>
  )
}
