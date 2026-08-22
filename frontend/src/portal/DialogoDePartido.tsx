/** El detalle de un partido: quién juega y cómo contactarlos.
 *
 * 🔑 **El contacto lo decide el servidor, no esta pantalla.** `telefono` viene
 * `null` para quien no juega ahí, y acá simplemente no se dibuja. No hay un `if`
 * de permisos del lado del cliente — un permiso que se evalúa en el navegador es
 * un permiso que se saca con las herramientas de desarrollo.
 */
import { useCallback, useEffect, useState } from 'react'
import { Phone, Users } from 'lucide-react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

import { partidos as api } from '@/lib/api'
import type { PartidoDetalle } from '@/lib/api'
import { fecha, hora } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'

export function DialogoDePartido({
  partidoId,
  onCerrar,
  onCambio,
}: {
  partidoId: number | null
  onCerrar: () => void
  onCambio: () => void
}) {
  const [partido, setPartido] = useState<PartidoDetalle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  const recargar = useCallback(() => {
    if (partidoId === null) return
    setError(null)
    api
      .ver(partidoId)
      .then(setPartido)
      .catch((e: Error) => setError(e.message))
  }, [partidoId])

  useEffect(() => {
    setPartido(null)
    recargar()
  }, [recargar])

  if (partidoId === null) return null

  async function accion(fn: () => Promise<PartidoDetalle>) {
    setError(null)
    setEnviando(true)
    try {
      setPartido(await fn())
      onCambio()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {partido
              ? `${fecha(partido.comienza_at)} · ${hora(partido.comienza_at)}`
              : 'Partido'}
          </DialogTitle>
        </DialogHeader>

        <AvisoDeError mensaje={error} />

        {partido && (
          <div className="space-y-3 text-sm">
            <div className="rounded-md border bg-card p-3">
              <div className="font-medium">{partido.cancha}</div>
              <div className="text-muted-foreground">
                {hora(partido.comienza_at)} a {hora(partido.termina_at)}
              </div>
              {partido.nota && <div className="mt-1">{partido.nota}</div>}
            </div>

            <div className="space-y-1">
              <div className="flex items-center gap-2 font-medium">
                <Users className="size-4" />
                {partido.faltan > 0 ? `Faltan ${partido.faltan}` : 'Completo'}
              </div>

              <Persona
                nombre={partido.organizador}
                telefono={partido.organizador_telefono}
                etiqueta="organiza"
              />
              {partido.anotados.map((a, i) => (
                <Persona
                  key={`${a.nombre}-${i}`}
                  nombre={a.nombre}
                  telefono={a.telefono}
                  etiqueta={a.soy_yo ? 'vos' : undefined}
                />
              ))}
            </div>

            {/* 🔑 El aviso de por qué no se ven los teléfonos. Sin él, el que
                mira cree que nadie cargó su número. */}
            {!partido.estoy_anotado && !partido.soy_organizador && (
              <p className="text-muted-foreground">
                Cuando te sumes vas a ver cómo contactarlos.
              </p>
            )}

            <div className="flex flex-wrap justify-end gap-2">
              {partido.soy_organizador ? (
                partido.abierta && (
                  <Button
                    variant="outline"
                    disabled={enviando}
                    onClick={() => accion(() => api.cerrar(partido.id))}
                  >
                    Dejar de buscar
                  </Button>
                )
              ) : partido.estoy_anotado ? (
                <Button
                  variant="outline"
                  disabled={enviando}
                  onClick={() => accion(() => api.bajarme(partido.id))}
                >
                  Bajarme
                </Button>
              ) : (
                partido.abierta &&
                partido.faltan > 0 && (
                  <Button
                    disabled={enviando}
                    onClick={() => accion(() => api.sumarme(partido.id))}
                  >
                    Sumarme
                  </Button>
                )
              )}
              <Button variant="ghost" onClick={onCerrar}>
                Cerrar
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Persona({
  nombre, telefono, etiqueta,
}: {
  nombre: string
  telefono: string | null
  etiqueta?: string
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span>
        {nombre}
        {etiqueta && <span className="ml-1 text-muted-foreground">({etiqueta})</span>}
      </span>
      {/* `null` = no me corresponde verlo. La cadena vacía sería "no lo cargó",
          y por eso el servidor manda `null` y no `""`. */}
      {telefono && (
        <a href={`tel:${telefono}`} className="flex items-center gap-1 text-muted-foreground">
          <Phone className="size-3" />
          {telefono}
        </a>
      )}
    </div>
  )
}
