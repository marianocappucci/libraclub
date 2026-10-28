/** Avisos al cliente: qué se manda y qué se mandó (ADR-015, ADR-029).
 *
 *  Dos pestañas. **Configuración**: qué tipos de aviso salen y el modo del canal de WhatsApp.
 *  **Registro**: lo que `avisos` guardó de cada intento, que existía desde ADR-015 sin una
 *  pantalla para mirarlo (y es para lo único que se mira: «¿le llegó el aviso?»).
 *
 *  🔴 **El interruptor general no está acá.** Es la tarea programada del servidor
 *  (`scripts/enviar_avisos.py`): sin ella no sale nada, se prenda lo que se prenda en esta
 *  pantalla. Por eso el texto no promete envíos: dice qué se manda *cuando* corre.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from 'libra-ui/data-table'
import { DataTable } from 'libra-ui/data-table'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { BadgeEstado } from 'libra-ui/badge-estado'
import type { TonoEstado } from 'libra-ui/badge-estado'
import { Switch } from 'libra-ui/ui/switch'
import { BellRing, MessageSquareText } from 'lucide-react'

import { avisos as api } from '@/lib/api'
import type { AvisoRegistrado, ConfigAvisos, EstadoAviso, ModoWhatsapp, TipoAviso } from '@/lib/api'
import { fechaHora } from '@/lib/fechas'
import { useAuth } from '@/context/AuthContext'
import { AvisoDeError } from '@/components/listado'
import { Button, buttonVariants } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const TIPOS: { clave: keyof Omit<ConfigAvisos, 'whatsapp'>; titulo: string; detalle: string }[] = [
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

const MODOS: { valor: ModoWhatsapp; texto: string }[] = [
  { valor: 'apagado', texto: 'Apagado' },
  { valor: 'registro', texto: 'Registrar mensajes (prueba)' },
]

const NOMBRE_DEL_TIPO: Record<TipoAviso, string> = {
  confirmacion: 'Confirmación',
  recordatorio: 'Recordatorio',
  cancelacion: 'Cancelación',
  sena_por_vencer: 'Seña por vencer',
}

const ESTADOS: Record<EstadoAviso, { tono: TonoEstado; texto: string }> = {
  enviado: { tono: 'ok', texto: 'Enviado' },
  // «Registrado» y no «enviado»: el mensaje se armó y quedó anotado, pero nadie lo recibió.
  registrado: { tono: 'curso', texto: 'Registrado (no salió)' },
  omitido: { tono: 'neutro', texto: 'Omitido' },
  fallido: { tono: 'negativo', texto: 'Falló' },
}

export function Avisos() {
  const { user } = useAuth()
  const puedeEscribir = user?.role === 'admin'
  const [config, setConfig] = useState<ConfigAvisos | null>(null)
  const [guardada, setGuardada] = useState<ConfigAvisos | null>(null)
  const [registro, setRegistro] = useState<AvisoRegistrado[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)
  const [viendo, setViendo] = useState<AvisoRegistrado | null>(null)

  const cargar = useCallback(() => {
    Promise.all([api.config(), api.registro()])
      .then(([c, r]) => {
        setConfig(c)
        setGuardada(c)
        setRegistro(r)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(cargar, [cargar])

  const sinGuardar = config !== null && JSON.stringify(config) !== JSON.stringify(guardada)

  async function guardar() {
    if (!config) return
    setGuardando(true)
    setError(null)
    setAviso(null)
    try {
      const nueva = await api.guardarConfig(config)
      setConfig(nueva)
      setGuardada(nueva)
      setAviso('Configuración guardada.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setGuardando(false)
    }
  }

  const columnas = useMemo<ColumnDef<AvisoRegistrado, unknown>[]>(
    () => [
      { id: 'cuando', header: 'Cuándo', cell: ({ row }) => fechaHora(row.original.creado_at) },
      {
        id: 'tipo',
        header: 'Aviso',
        cell: ({ row }) => (
          <div>
            {NOMBRE_DEL_TIPO[row.original.tipo]}
            <div className="text-xs text-muted-foreground">
              {row.original.canal === 'email' ? 'Correo' : 'WhatsApp'}
            </div>
          </div>
        ),
      },
      {
        id: 'turno',
        header: 'Turno',
        cell: ({ row }) => (
          <div>
            {row.original.cancha ?? ''}
            <div className="text-xs text-muted-foreground">{fechaHora(row.original.comienza_at)}</div>
          </div>
        ),
      },
      {
        id: 'destino',
        header: 'Destino',
        cell: ({ row }) => row.original.destino || <span className="text-muted-foreground">—</span>,
      },
      {
        id: 'estado',
        header: 'Estado',
        cell: ({ row }) => {
          const { tono, texto } = ESTADOS[row.original.estado]
          return (
            <div className="space-y-0.5">
              <BadgeEstado tono={tono}>{texto}</BadgeEstado>
              {/* `whitespace-normal`: el motivo es una frase y en una línea ensancha la tabla. */}
              {row.original.detalle && (
                <div className="w-56 whitespace-normal text-xs text-muted-foreground">
                  {row.original.detalle}
                </div>
              )}
            </div>
          )
        },
      },
      {
        id: 'mensaje',
        header: () => <div className="text-right">Mensaje</div>,
        enableSorting: false,
        cell: ({ row }) =>
          row.original.cuerpo ? (
            <div className="flex justify-end">
              <Button
                variant="outline"
                size="icon"
                aria-label={`Ver el mensaje a ${row.original.destino}`}
                onClick={() => setViendo(row.original)}
              >
                <MessageSquareText className="size-4" />
              </Button>
            </div>
          ) : null,
      },
    ],
    [],
  )

  return (
    <div className="space-y-3">
      <TituloPantalla icono={BellRing}>Avisos</TituloPantalla>
      <AvisoDeError mensaje={error} />

      <Tabs defaultValue="configuracion">
        <TabsList>
          <TabsTrigger value="configuracion">Configuración</TabsTrigger>
          <TabsTrigger value="registro">Registro</TabsTrigger>
        </TabsList>

        <TabsContent value="configuracion" className="space-y-4">
          {config && (
            <>
              <section className="space-y-2 rounded-lg border bg-card p-4">
                <h3 className="text-sm font-semibold">Qué avisos se mandan</h3>
                <p className="text-sm text-muted-foreground">
                  Los avisos por correo salen con el servidor cargado en Configuración → Correo.
                  Si un cliente no tiene el dato o pidió no recibir avisos, el intento queda
                  anotado como omitido en el registro.
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
                        checked={config[t.clave]}
                        disabled={!puedeEscribir}
                        onCheckedChange={(v) => setConfig({ ...config, [t.clave]: v })}
                      />
                    </li>
                  ))}
                </ul>
              </section>

              <section className="space-y-2 rounded-lg border bg-card p-4">
                <h3 className="text-sm font-semibold">WhatsApp</h3>
                <label htmlFor="aviso-whatsapp" className="block text-sm font-medium">
                  Modo
                </label>
                {/* select-cerrado: los dos modos de la constante MODOS (apagado y registro) */}
                <select
                  id="aviso-whatsapp"
                  className="h-9 w-full max-w-xs rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
                  value={config.whatsapp}
                  disabled={!puedeEscribir}
                  onChange={(e) => setConfig({ ...config, whatsapp: e.target.value as ModoWhatsapp })}
                >
                  {MODOS.map((m) => (
                    <option key={m.valor} value={m.valor}>{m.texto}</option>
                  ))}
                </select>
                <p className="text-sm text-muted-foreground">
                  Todavía no hay un proveedor de WhatsApp conectado. En modo de prueba los mensajes
                  se arman con los mismos avisos de arriba y quedan en el registro con el estado
                  «Registrado», <strong>pero no se mandan a nadie</strong>. Sirve para revisar
                  cómo quedarían y a qué teléfonos saldrían antes de conectarlo.
                </p>
              </section>

              {puedeEscribir && (
                <div className="flex items-center justify-end gap-3">
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
              )}
            </>
          )}
        </TabsContent>

        <TabsContent value="registro" className="space-y-2">
          <p className="text-sm text-muted-foreground">
            Los últimos {registro.length === 100 ? '100 ' : ''}intentos, del más nuevo al más viejo.
            El destino es el que tenía el cliente cuando se mandó.
          </p>
          <DataTable
            columns={columnas}
            data={registro}
            emptyMessage="Todavía no se mandó ningún aviso."
            search={{
              campos: (a) => [a.destino, a.cancha ?? '', NOMBRE_DEL_TIPO[a.tipo], ESTADOS[a.estado].texto],
              placeholder: 'Buscar por destino, cancha o estado',
              ariaLabel: 'Buscar aviso',
            }}
          />
        </TabsContent>
      </Tabs>

      <Dialog open={viendo !== null} onOpenChange={(o) => { if (!o) setViendo(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {viendo ? `${NOMBRE_DEL_TIPO[viendo.tipo]} · ${viendo.destino}` : 'Mensaje'}
            </DialogTitle>
          </DialogHeader>
          {viendo?.asunto && <p className="text-sm font-medium">{viendo.asunto}</p>}
          <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 text-sm">{viendo?.cuerpo}</pre>
        </DialogContent>
      </Dialog>
    </div>
  )
}
