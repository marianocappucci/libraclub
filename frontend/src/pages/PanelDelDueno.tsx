/** El panel del dueño: cómo anda el complejo, abierto por sucursal.
 *
 * Es la F5 del ROADMAP y el ADR-027. Cuatro cosas, en el orden en que un dueño las mira: cuánto se ocupó (el mapa de
 * calor por día y hora), cuánto entró (contra el período anterior), cuántos turnos se perdieron (cancelados y ausentes,
 * con los clientes que más faltan) y de dónde vinieron las reservas.
 *
 * 🔑 **Todo se abre por sucursal.** Con cinco sucursales el dueño ve cinco filas, no una sumada: un total que aplasta
 * a la que anda mal contra las que andan bien es exactamente lo que este panel viene a evitar. Los totales de arriba son
 * la suma de esas filas, y el mapa de calor es el de las sucursales que se están mirando.
 *
 * 🔑 **Los números vienen del backend** (`GET /api/admin/panel-del-dueno`, el mismo bloque `club` que lee `libra-panel`).
 * Acá se dibujan; lo único que se calcula es lo que depende de qué sucursales se mira (ver `lib/panel-del-dueno.ts`).
 *
 * ⚠️ **Es de admin.** El menú no lo ofrece al encargado y el backend le contesta 403; la pantalla no lo vuelve a decidir.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { GrillaDeIndicadores } from 'libra-ui/GrillaDeIndicadores'
import { TarjetaIndicador } from 'libra-ui/TarjetaIndicador'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { ICONOS } from 'libra-ui/iconos-identidad'
import { hoyISO, primerDiaDelMesISO, sumarDiasISO } from 'libra-ui/fechas'

import { canchas as apiCanchas, panelDelDueno } from '@/lib/api'
import type { Cancha, PanelDelDueno as Panel, SucursalDelPanel } from '@/lib/api'
import { useSucursal } from '@/context/SucursalContext'
import { fecha, pesos } from '@/lib/fechas'
import {
  clavesDeOrigen, etiquetaDeOrigen, porcentaje, sumarIngresos, turnosPerdidos, variacion,
} from '@/lib/panel-del-dueno'
import { AvisoDeError } from '@/components/listado'
import { MapaDeCalor } from '@/components/MapaDeCalor'
import { SelectBuscable } from '@/components/select-buscable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/** Los atajos de período. El primero es el que abre la pantalla: los últimos 30 días, como el panel. */
const ATAJOS = [
  { id: '7', etiqueta: '7 días', rango: () => ({ desde: sumarDiasISO(hoyISO(), -6), hasta: hoyISO() }) },
  { id: '30', etiqueta: '30 días', rango: () => ({ desde: sumarDiasISO(hoyISO(), -29), hasta: hoyISO() }) },
  { id: '90', etiqueta: '90 días', rango: () => ({ desde: sumarDiasISO(hoyISO(), -89), hasta: hoyISO() }) },
  { id: 'mes', etiqueta: 'Este mes', rango: () => ({ desde: primerDiaDelMesISO(), hasta: hoyISO() }) },
] as const

const TODAS = ''

function Variacion({ actual, anterior }: { actual: number; anterior: number }) {
  const cambio = variacion(actual, anterior)
  if (cambio === null) return <span className="text-muted-foreground">Sin período anterior</span>
  const sube = cambio > 0
  const baja = cambio < 0
  const texto = `${sube ? '+' : ''}${porcentaje(cambio)}`
  return (
    <span className={sube ? 'text-exito' : baja ? 'text-destructive' : 'text-muted-foreground'}>{texto}</span>
  )
}

function Seccion({ titulo, ayuda, children }: { titulo: string; ayuda?: string; children: ReactNode }) {
  return (
    <section className="space-y-3 rounded-lg border bg-card p-4">
      <div>
        <h2 className="font-medium">{titulo}</h2>
        {ayuda && <p className="text-sm text-muted-foreground">{ayuda}</p>}
      </div>
      {children}
    </section>
  )
}

function Vacio({ children }: { children: ReactNode }) {
  return <p className="py-2 text-sm text-muted-foreground">{children}</p>
}

const TH = 'py-2 pr-3 font-medium'

export function PanelDelDueno() {
  const { sucursales } = useSucursal()
  const [rango, setRango] = useState(() => ATAJOS[1].rango())
  const [sucursalId, setSucursalId] = useState(TODAS)
  const [canchaId, setCanchaId] = useState(TODAS)
  const [canchas, setCanchas] = useState<Cancha[]>([])
  const [datos, setDatos] = useState<Panel | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const pedido = useRef(0)

  const { desde, hasta } = rango
  // Un campo de fecha vacío (mientras se está escribiendo) o al revés no se manda: el backend contestaría 422 por algo que
  // la pantalla ya sabe. Sólo el invertido se avisa; el vacío es un paso del tipeo.
  const rangoInvertido = Boolean(desde && hasta) && desde > hasta
  const rangoCompleto = Boolean(desde && hasta) && !rangoInvertido

  useEffect(() => {
    apiCanchas.listar().then(setCanchas).catch(() => setCanchas([]))
  }, [])

  useEffect(() => {
    if (!rangoCompleto) return
    // Si el usuario cambia el filtro mientras viaja una respuesta, gana la última: una respuesta tardía de un
    // filtro anterior no puede pisar a la que se está mirando.
    const este = ++pedido.current
    setCargando(true)
    setError(null)
    panelDelDueno
      .obtener({
        desde, hasta,
        sucursalId: sucursalId ? Number(sucursalId) : undefined,
        canchaId: canchaId ? Number(canchaId) : undefined,
      })
      .then((r) => { if (este === pedido.current) setDatos(r) })
      .catch((e: Error) => { if (este === pedido.current) { setDatos(null); setError(e.message) } })
      .finally(() => { if (este === pedido.current) setCargando(false) })
  }, [desde, hasta, sucursalId, canchaId, rangoCompleto])

  // Las canchas que ofrece el filtro: las de la sucursal elegida, o todas si se miran todas (con el nombre de la sucursal,
  // porque «Cancha 1» hay en cada una).
  const nombreDeSucursal = useMemo(() => new Map(sucursales.map((s) => [s.id, s.nombre])), [sucursales])
  const opcionesDeCancha = useMemo(() => {
    const visibles = canchas.filter((c) => c.activa && (!sucursalId || c.sucursal_id === Number(sucursalId)))
    return [
      { value: TODAS, label: 'Todas las canchas' },
      ...visibles.map((c) => ({
        value: String(c.id),
        label: sucursalId ? c.nombre : `${c.nombre} · ${nombreDeSucursal.get(c.sucursal_id) ?? ''}`,
      })),
    ]
  }, [canchas, sucursalId, nombreDeSucursal])

  const filas: SucursalDelPanel[] = datos?.por_sucursal ?? []
  const ingresos = useMemo(() => sumarIngresos(filas), [filas])
  const reservas = filas.reduce((n, s) => n + s.reservas, 0)
  const canceladas = filas.reduce((n, s) => n + s.canceladas, 0)
  const ausentes = filas.reduce((n, s) => n + s.ausentes, 0)
  const perdidos = turnosPerdidos(canceladas, ausentes, reservas)
  const claves = clavesDeOrigen(filas)
  const sinActividad = datos !== null && reservas === 0 && canceladas === 0
  const elegirAtajo = (id: string) => setRango(ATAJOS.find((a) => a.id === id)!.rango())
  const atajoActivo = ATAJOS.find((a) => {
    const r = a.rango()
    return r.desde === desde && r.hasta === hasta
  })?.id

  return (
    <div className="space-y-4">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={ICONOS.dashboard}>Panel del dueño</TituloPantalla>} />

      <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-3">
        <div className="grid gap-1.5">
          <Label htmlFor="desde">Desde</Label>
          <Input
            id="desde" type="date" className="w-40" value={desde}
            onChange={(e) => setRango({ desde: e.target.value, hasta })}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="hasta">Hasta</Label>
          <Input
            id="hasta" type="date" className="w-40" value={hasta}
            onChange={(e) => setRango({ desde, hasta: e.target.value })}
          />
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Atajos de período">
          {ATAJOS.map((a) => (
            <Button
              key={a.id} type="button" size="sm"
              variant={atajoActivo === a.id ? 'default' : 'outline'}
              aria-pressed={atajoActivo === a.id}
              onClick={() => elegirAtajo(a.id)}
            >
              {a.etiqueta}
            </Button>
          ))}
        </div>
        {/* Con una sola sucursal el selector no decide nada. */}
        {sucursales.length > 1 && (
          <div className="grid gap-1.5">
            <Label htmlFor="sucursal-del-panel">Sucursal</Label>
            <SelectBuscable
              id="sucursal-del-panel" className="w-56" value={sucursalId}
              onChange={(v) => { setSucursalId(v); setCanchaId(TODAS) }}
              opciones={[
                { value: TODAS, label: 'Todas las sucursales' },
                ...sucursales.map((s) => ({ value: String(s.id), label: s.nombre })),
              ]}
              placeholder="Buscar sucursal…" limpiable={false}
            />
          </div>
        )}
      </div>

      {rangoInvertido && <AvisoDeError mensaje="La fecha «desde» no puede ser posterior a «hasta»." />}
      <AvisoDeError mensaje={error} />

      {rangoCompleto && cargando && !datos ? (
        <p className="text-muted-foreground">Cargando…</p>
      ) : !datos ? null : filas.length === 0 ? (
        <Vacio>Todavía no hay sucursales para mostrar.</Vacio>
      ) : (
        <div className={cargando ? 'space-y-4 opacity-60 transition-opacity' : 'space-y-4'} aria-busy={cargando}>
          <p className="text-sm text-muted-foreground">
            Del {fecha(datos.desde)} al {fecha(datos.hasta)}
            {filas.length > 1 ? `, ${filas.length} sucursales` : ''}.
          </p>

          <GrillaDeIndicadores>
            <TarjetaIndicador
              concepto="reportes" etiqueta="Ocupación"
              valor={porcentaje(datos.total.ocupacion_pct)}
              ayuda="De las horas abiertas, las reservadas"
            />
            <TarjetaIndicador
              concepto="cobros" etiqueta="Ingresos" tono="exito"
              valor={ingresos.medible ? pesos(ingresos.total) : '—'}
              ayuda={ingresos.medible ? 'Turnos, señas y buffet' : 'Sin caja configurada'}
              variacion={
                ingresos.medible && variacion(ingresos.total, ingresos.total_periodo_anterior) !== null
                  ? { porcentaje: variacion(ingresos.total, ingresos.total_periodo_anterior)! }
                  : undefined
              }
            />
            <TarjetaIndicador
              concepto="agenda" etiqueta="Reservas" valor={String(reservas)}
              ayuda="Sin contar las canceladas"
            />
            <TarjetaIndicador
              concepto="mermas" etiqueta="Turnos perdidos" valor={String(perdidos.perdidos)}
              tono={perdidos.perdidos > 0 ? 'aviso' : 'neutro'}
              ayuda={`${canceladas} canceladas · ${ausentes} ausentes (${porcentaje(perdidos.pct)})`}
            />
          </GrillaDeIndicadores>

          {sinActividad && (
            <Vacio>No hubo reservas en este período. Probá con uno más largo.</Vacio>
          )}

          <Seccion
            titulo="Ocupación por franja"
            ayuda="Por día de la semana y hora de inicio: el porcentaje de las horas abiertas que estuvieron reservadas."
          >
            <div className="flex flex-wrap items-end gap-3">
              <div className="grid gap-1.5">
                <Label htmlFor="cancha-del-panel">Cancha</Label>
                <SelectBuscable
                  id="cancha-del-panel" className="w-64" value={canchaId} onChange={setCanchaId}
                  opciones={opcionesDeCancha} placeholder="Buscar cancha…" limpiable={false}
                />
              </div>
            </div>
            {datos.total.franjas.length === 0 ? (
              <Vacio>
                No hay horas abiertas en este período para esta selección. Revisá el horario de atención.
              </Vacio>
            ) : (
              <MapaDeCalor franjas={datos.total.franjas} etiqueta="Ocupación por día y hora" />
            )}
            {filas.length > 1 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b text-left text-muted-foreground">
                    <tr>
                      <th className={TH}>Sucursal</th>
                      <th className={`${TH} text-right`}>Horas abiertas</th>
                      <th className={`${TH} text-right`}>Horas reservadas</th>
                      <th className="py-2 text-right font-medium">Ocupación</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filas.map((s) => (
                      <tr key={s.sucursal_id} className="border-b last:border-0">
                        <td className="py-2 pr-3">{s.sucursal}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{s.horas_abiertas.toLocaleString('es-AR')}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{s.horas_reservadas.toLocaleString('es-AR')}</td>
                        <td className="py-2 text-right font-medium tabular-nums">{porcentaje(s.ocupacion_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Seccion>

          <Seccion
            titulo="Ingresos"
            ayuda="Comparados con el período anterior, de igual largo. Los turnos se cuentan por la fecha en que se juegan."
          >
            {!ingresos.medible && filas.every((s) => s.ingresos === null) ? (
              <Vacio>Esta instancia no tiene la caja configurada, así que no puede informar ingresos.</Vacio>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b text-left text-muted-foreground">
                    <tr>
                      <th className={TH}>Sucursal</th>
                      <th className={`${TH} text-right`}>Turnos</th>
                      <th className={`${TH} text-right`}>Señas</th>
                      <th className={`${TH} text-right`}>Buffet</th>
                      <th className={`${TH} text-right`}>Total</th>
                      <th className={`${TH} text-right`}>Período anterior</th>
                      <th className="py-2 text-right font-medium">Variación</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filas.map((s) => (
                      <tr key={s.sucursal_id} className="border-b last:border-0">
                        <td className="py-2 pr-3">{s.sucursal}</td>
                        {s.ingresos === null ? (
                          <td colSpan={6} className="py-2 text-right text-muted-foreground">Sin caja configurada</td>
                        ) : (
                          <>
                            <td className="py-2 pr-3 text-right tabular-nums">{pesos(s.ingresos.reservas)}</td>
                            <td className="py-2 pr-3 text-right tabular-nums">{pesos(s.ingresos.senas)}</td>
                            <td className="py-2 pr-3 text-right tabular-nums">{pesos(s.ingresos.buffet)}</td>
                            <td className="py-2 pr-3 text-right font-medium tabular-nums">{pesos(s.ingresos.total)}</td>
                            <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">
                              {pesos(s.ingresos.total_periodo_anterior)}
                            </td>
                            <td className="py-2 text-right tabular-nums">
                              <Variacion actual={s.ingresos.total} anterior={s.ingresos.total_periodo_anterior} />
                            </td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                  {filas.length > 1 && ingresos.medible && (
                    <tfoot className="border-t font-medium">
                      <tr>
                        <td className="py-2 pr-3">Total</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{pesos(ingresos.reservas)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{pesos(ingresos.senas)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{pesos(ingresos.buffet)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{pesos(ingresos.total)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">
                          {pesos(ingresos.total_periodo_anterior)}
                        </td>
                        <td className="py-2 text-right tabular-nums">
                          <Variacion actual={ingresos.total} anterior={ingresos.total_periodo_anterior} />
                        </td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            )}
          </Seccion>

          <Seccion
            titulo="Cancelaciones y ausentes"
            ayuda="Cancelar avisa y libera la cancha a tiempo; no venir la quema. Las ausencias cuentan como reservas: el turno se ocupó."
          >
            <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b text-left text-muted-foreground">
                    <tr>
                      <th className={TH}>Sucursal</th>
                      <th className={`${TH} text-right`}>Reservas</th>
                      <th className={`${TH} text-right`}>Canceladas</th>
                      <th className="py-2 text-right font-medium">Ausentes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filas.map((s) => (
                      <tr key={s.sucursal_id} className="border-b last:border-0">
                        <td className="py-2 pr-3">{s.sucursal}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{s.reservas}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{s.canceladas}</td>
                        <td className="py-2 text-right tabular-nums">{s.ausentes}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div>
                <h3 className="mb-2 text-sm font-medium">Clientes con más ausentes</h3>
                {datos.top_ausentes.length === 0 ? (
                  <Vacio>Nadie faltó en este período.</Vacio>
                ) : (
                  <ol className="space-y-1 text-sm">
                    {datos.top_ausentes.map((c) => (
                      <li key={c.cliente_id} className="flex items-baseline justify-between gap-3 border-b py-1 last:border-0">
                        <span className="truncate">{c.nombre || `Cliente ${c.cliente_id}`}</span>
                        <span className="tabular-nums text-muted-foreground">
                          {c.ausentes} {c.ausentes === 1 ? 'ausente' : 'ausentes'}
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            </div>
          </Seccion>

          <Seccion
            titulo="Origen de las reservas"
            ayuda="De dónde llegó cada reserva vendida. Las canceladas no se cuentan."
          >
            {reservas === 0 ? (
              <Vacio>Sin reservas en este período.</Vacio>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b text-left text-muted-foreground">
                    <tr>
                      <th className={TH}>Sucursal</th>
                      {claves.map((k) => (
                        <th key={k} className={`${TH} text-right`}>{etiquetaDeOrigen(k)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filas.map((s) => (
                      <tr key={s.sucursal_id} className="border-b last:border-0">
                        <td className="py-2 pr-3">{s.sucursal}</td>
                        {claves.map((k) => {
                          const n = s.origen[k] ?? 0
                          return (
                            <td key={k} className="py-2 pr-3 text-right tabular-nums">
                              {n}
                              <span className="ml-1 text-xs text-muted-foreground">
                                {s.reservas > 0 ? `(${porcentaje((n / s.reservas) * 100)})` : ''}
                              </span>
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Seccion>
        </div>
      )}
    </div>
  )
}
