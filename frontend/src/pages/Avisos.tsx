/** Avisos al cliente: qué se manda, cómo sale y qué se mandó (ADR-015, ADR-029, ADR-030).
 *
 *  Tres cosas, y de tres dueños:
 *
 *  - **Qué tipos de aviso salen** (confirmación, recordatorio, cancelación, seña por vencer): es de LibraClub
 *    (`/api/avisos/tipos`). El mostrador lo ve; cambiarlo es de admin.
 *  - **Cómo sale** (WhatsApp apagado, en registro o por Evolution; «probar envío»; si hay servidor de correo): es del
 *    motor (`libracore.avisos`, ADR-090) y lo pinta el kit con `ConfiguracionDeAvisos`.
 *  - **Qué salió** (el registro, con su estado y su motivo): es del motor y lo pinta el kit con `RegistroDeAvisos`.
 *
 *  🔴 Las dos últimas son **sólo de administrador** (el router del motor lleva `require_admin`: la apikey de Evolution y
 *  los teléfonos y textos de los clientes no son del mostrador). Para el mostrador la pantalla se reduce a los tipos,
 *  de sólo lectura, y lo dice.
 *
 *  🔴 **El interruptor general no está acá.** Es la tarea programada del servidor (`scripts/enviar_avisos.py`): sin ella
 *  no sale nada, se prenda lo que se prenda en esta pantalla. Por eso el texto no promete envíos: dice qué se manda
 *  *cuando* corre.
 */
import { useCallback, useEffect, useState } from 'react'
import { ConfiguracionDeAvisos } from 'libra-ui/ConfiguracionDeAvisos'
import { RegistroDeAvisos } from 'libra-ui/RegistroDeAvisos'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { Switch } from 'libra-ui/ui/switch'
import { BellRing } from 'lucide-react'

import { avisos as api } from '@/lib/api'
import type { TipoAviso, TiposDeAviso, TiposDeAvisoConDemo } from '@/lib/api'
import { useAuth } from '@/context/AuthContext'
import { AvisoDeError } from '@/components/listado'
import { buttonVariants } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const TIPOS: { clave: TipoAviso; titulo: string; detalle: string }[] = [
  {
    clave: 'confirmacion',
    titulo: 'Confirmación',
    detalle: 'Cuando el turno queda tomado.',
  },
  {
    clave: 'recordatorio',
    titulo: 'Recordatorio',
    detalle: 'El día antes (24 horas) y dos horas antes del turno.',
  },
  {
    clave: 'cancelacion',
    titulo: 'Cancelación',
    detalle: 'Cuando se cae un turno que el cliente ya tenía confirmado.',
  },
  {
    clave: 'sena_por_vencer',
    titulo: 'Seña por vencer',
    detalle:
      'Antes de que se libere un turno que espera la seña: unos minutos antes si se paga desde '
      + 'el portal, y tres horas antes si se reservó por teléfono o en el local (tiene 24 horas).',
  },
]

/** El rótulo de cada tipo en el registro: el `tipo` lo pone quien avisa (este producto), así que el vocabulario es suyo. */
const NOMBRE_DEL_TIPO: Record<TipoAviso, string> = {
  confirmacion: 'Confirmación',
  recordatorio: 'Recordatorio',
  cancelacion: 'Cancelación',
  sena_por_vencer: 'Seña por vencer',
}

const etiquetaDelTipo = (tipo: string) => NOMBRE_DEL_TIPO[tipo as TipoAviso] ?? tipo

/** Los cuatro interruptores sin el dato de la demo, que no se edita ni se guarda. */
const soloLosTipos = (c: TiposDeAvisoConDemo): TiposDeAviso => ({
  confirmacion: c.confirmacion,
  recordatorio: c.recordatorio,
  cancelacion: c.cancelacion,
  sena_por_vencer: c.sena_por_vencer,
})

export function Avisos() {
  const { user } = useAuth()
  const esAdmin = user?.role === 'admin'
  const [tipos, setTipos] = useState<TiposDeAvisoConDemo | null>(null)
  const [guardados, setGuardados] = useState<TiposDeAviso | null>(null)
  const [demo, setDemo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  const cargar = useCallback(() => {
    api.tipos()
      .then((t) => {
        setTipos(t)
        setGuardados(soloLosTipos(t))
        setDemo(t.demo)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(cargar, [cargar])

  const sinGuardar = tipos !== null && JSON.stringify(soloLosTipos(tipos)) !== JSON.stringify(guardados)

  async function guardar() {
    if (!tipos) return
    setGuardando(true)
    setError(null)
    setAviso(null)
    try {
      const nuevos = await api.guardarTipos(soloLosTipos(tipos))
      setTipos(nuevos)
      setGuardados(soloLosTipos(nuevos))
      setDemo(nuevos.demo)
      setAviso('Configuración guardada.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setGuardando(false)
    }
  }

  const seccionDeTipos = tipos && (
    <section className="space-y-2 rounded-lg border bg-card p-4">
      <h3 className="text-sm font-semibold">Qué avisos se mandan</h3>
      <p className="text-sm text-muted-foreground">
        Los avisos por correo salen con el servidor cargado en Configuración → Correo, y los de WhatsApp según
        cómo esté conectado (pestaña «WhatsApp y correo»). Si un cliente no tiene el dato o pidió no recibir avisos, el
        intento queda anotado como omitido en el registro.
      </p>
      <ul className="divide-y">
        {TIPOS.map((t) => (
          <li key={t.clave} className="flex items-start justify-between gap-4 py-3">
            <div>
              <label htmlFor={`aviso-${t.clave}`} className="text-sm font-medium">
                {t.titulo}
              </label>
              <p className="text-sm text-muted-foreground">{t.detalle}</p>
            </div>
            <Switch
              id={`aviso-${t.clave}`}
              checked={tipos[t.clave]}
              disabled={!esAdmin}
              onCheckedChange={(v) => setTipos({ ...tipos, [t.clave]: v })}
            />
          </li>
        ))}
      </ul>
      {esAdmin ? (
        <div className="flex items-center justify-end gap-3 pt-2">
          {aviso && <span role="status" className="text-sm text-muted-foreground">{aviso}</span>}
          <button
            type="button"
            className={buttonVariants()}
            disabled={guardando || !sinGuardar}
            onClick={guardar}
          >
            {guardando ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          Sólo un administrador cambia esto. Cómo salen los mensajes por WhatsApp y el registro de lo que salió también
          son del administrador.
        </p>
      )}
    </section>
  )

  return (
    <div className="space-y-3">
      <TituloPantalla icono={BellRing}>Avisos</TituloPantalla>
      <AvisoDeError mensaje={error} />

      {esAdmin ? (
        <Tabs defaultValue="avisos">
          <TabsList>
            <TabsTrigger value="avisos">Avisos</TabsTrigger>
            <TabsTrigger value="whatsapp">WhatsApp y correo</TabsTrigger>
            <TabsTrigger value="registro">Registro</TabsTrigger>
          </TabsList>

          <TabsContent value="avisos" className="space-y-4">{seccionDeTipos}</TabsContent>

          <TabsContent value="whatsapp" className="space-y-4">
            <ConfiguracionDeAvisos demo={demo} />
          </TabsContent>

          <TabsContent value="registro" className="space-y-2">
            <RegistroDeAvisos esAdmin etiquetaDelTipo={etiquetaDelTipo} />
          </TabsContent>
        </Tabs>
      ) : (
        seccionDeTipos
      )}
    </div>
  )
}
