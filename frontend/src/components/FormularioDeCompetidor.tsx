import { useEffect, useState } from 'react'
import { Plus, X } from 'lucide-react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

import { torneos as api } from '@/lib/api'
import type { Integrante } from '@/lib/api'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

/** Cuánta gente propone el formulario según el deporte.
 *
 * En pádel y tenis dobles son dos y el nombre se arma solo; en fútbol se carga
 * el capitán y alcanza. Es un punto de partida: se agregan y se quitan filas.
 */
const INTEGRANTES_SUGERIDOS: Record<string, number> = {
  padel: 2, tenis: 1, futbol: 1, basquet: 1, voley: 1, hockey: 1, otro: 1,
}

function vacios(cuantos: number): Integrante[] {
  return Array.from({ length: cuantos }, () => ({ nombre: '', telefono: '' }))
}

/** Inscribir un competidor: una pareja, un equipo o un jugador.
 *
 * 🔑 **El nombre se propone a partir de los integrantes pero se guarda como
 * texto.** Es lo que se dibuja en el cuadro, y un cuadro se lee de lejos: no
 * puede depender de una concatenación que cambie si alguien corrige un apellido
 * a mitad de campeonato.
 */
export function FormularioDeCompetidor({
  abierto,
  torneoId,
  deporte,
  onCerrar,
  onInscripto,
}: {
  abierto: boolean
  torneoId: number
  deporte: string
  onCerrar: () => void
  onInscripto: () => void
}) {
  const sugeridos = INTEGRANTES_SUGERIDOS[deporte] ?? 1
  const [nombre, setNombre] = useState('')
  const [tocado, setTocado] = useState(false)
  const [siembra, setSiembra] = useState('')
  const [integrantes, setIntegrantes] = useState<Integrante[]>(() => vacios(sugeridos))
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    setNombre('')
    setTocado(false)
    setSiembra('')
    setIntegrantes(vacios(sugeridos))
  }, [abierto, sugeridos])

  // El nombre propuesto: «Pérez / García». Deja de proponerse en cuanto el
  // operador escribe algo propio — pisarle lo que escribió sería peor que no
  // ayudarlo.
  const propuesto = integrantes
    .map((i) => i.nombre.trim())
    .filter(Boolean)
    .join(' / ')
  const efectivo = tocado ? nombre : propuesto

  function cambiar(indice: number, campo: keyof Integrante, valor: string) {
    setIntegrantes((lista) =>
      lista.map((i, n) => (n === indice ? { ...i, [campo]: valor } : i)),
    )
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setEnviando(true)
    try {
      await api.inscribir(torneoId, {
        nombre: efectivo.trim(),
        siembra: siembra ? Number(siembra) : null,
        integrantes: integrantes
          .filter((i) => i.nombre.trim())
          .map((i) => ({ nombre: i.nombre.trim(), telefono: i.telefono || null })),
      })
      onInscripto()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  if (!abierto) return null

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Inscribir</DialogTitle>
        </DialogHeader>

        <form onSubmit={enviar} className="space-y-3 text-sm">
          <div className="space-y-2">
            <span className="font-medium">Jugadores</span>
            {integrantes.map((integrante, indice) => (
              <div key={indice} className="flex gap-2">
                <Input
                  autoFocus={indice === 0}
                  value={integrante.nombre}
                  onChange={(e) => cambiar(indice, 'nombre', e.target.value)}
                  placeholder="Nombre"
                />
                <Input
                  className="max-w-[10rem]"
                  value={integrante.telefono ?? ''}
                  onChange={(e) => cambiar(indice, 'telefono', e.target.value)}
                  placeholder="Teléfono"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`Quitar jugador ${indice + 1}`}
                  disabled={integrantes.length === 1}
                  onClick={() =>
                    setIntegrantes((l) => l.filter((_, n) => n !== indice))
                  }
                >
                  <X className="size-4" />
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setIntegrantes((l) => [...l, { nombre: '', telefono: '' }])}
            >
              <Plus className="size-4" />
              Agregar jugador
            </Button>
            {/* El teléfono está acá y no en el competidor: en una pareja los dos
                números importan y un solo campo obligaría a elegir uno. */}
            <p className="text-xs text-muted-foreground">
              El teléfono es para avisarles si se mueve un partido. Alcanza con
              el de uno.
            </p>
          </div>

          <label className="block space-y-1">
            <span className="font-medium">Cómo figura en el cuadro</span>
            <Input
              value={efectivo}
              onChange={(e) => {
                setTocado(true)
                setNombre(e.target.value)
              }}
              placeholder="Pérez / García"
            />
          </label>

          <label className="block space-y-1">
            <span className="font-medium">
              Cabeza de serie <span className="text-muted-foreground">(opcional)</span>
            </span>
            <Input
              type="number"
              min={1}
              value={siembra}
              onChange={(e) => setSiembra(e.target.value)}
              placeholder="1"
            />
            <span className="text-xs text-muted-foreground">
              Las cabezas de serie no entran al bombo: van a posiciones fijas
              para no cruzarse antes de tiempo. Dejalo vacío si no corresponde.
            </span>
          </label>

          <AvisoDeError mensaje={error} />

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onCerrar}>
              Cerrar
            </Button>
            <Button type="submit" disabled={enviando || !efectivo.trim()}>
              {enviando ? 'Inscribiendo…' : 'Inscribir'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
