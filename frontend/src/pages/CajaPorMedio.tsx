/** Qué entró y qué salió por cada medio de pago, en un período.
 *
 * Es el corte de plata del complejo: lo que el dueño mira a fin de mes, no una
 * herramienta del mostrador. Por eso es **de admin** — el encargado tiene su
 * turno y su historial.
 *
 * 🔑 **Los números vienen pivoteados del backend.** Es plata: dos lugares
 * sumando por su cuenta terminan mostrando totales que no coinciden, y el que
 * mira no tiene forma de saber cuál es el bueno. Acá se dibuja lo que llega; lo
 * único que se calcula es el porcentaje de cada medio, que es presentación.
 *
 * ⚠️ **Los movimientos anulados no cuentan**, y eso lo garantiza la consulta del
 * motor (`sql_no_anulado`), no un filtro de esta pantalla. Es el mismo criterio
 * que usa el arqueo del turno.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Download, Wallet } from 'lucide-react'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { iconoDe } from 'libra-ui/medios-pago'
import { hoyISO, primerDiaDelMesISO } from 'libra-ui/fechas'

import { caja, cajas as apiCajas } from '@/lib/api'
import type { CajaDeMostrador, ReportePorMedio } from '@/lib/api'
import { useSucursal } from '@/context/SucursalContext'
import { useMediosDePago } from '@/lib/medios-pago'
import { pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function CajaPorMedio() {
  const { actual } = useSucursal()
  const [desde, setDesde] = useState(primerDiaDelMesISO())
  const [hasta, setHasta] = useState(hoyISO())
  const [cajaId, setCajaId] = useState('0')
  const [datos, setDatos] = useState<ReportePorMedio | null>(null)
  const [mostradores, setMostradores] = useState<CajaDeMostrador[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const { etiqueta: etiquetaDeMedio } = useMediosDePago()

  const recargar = useCallback(() => {
    setCargando(true)
    setError(null)
    caja
      .porMedio({ desde, hasta, cajaId: Number(cajaId) })
      .then(setDatos)
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [desde, hasta, cajaId])

  useEffect(recargar, [recargar])

  // El selector de mostrador se llena con los de la sede en la que se está
  // parado. El reporte sin filtro los trae a todos igual —y la columna dice de
  // cuál es cada fila—, así que esto acota, no esconde.
  useEffect(() => {
    if (actual === null) return
    apiCajas.deLaSucursal(actual).then(setMostradores).catch(() => setMostradores([]))
  }, [actual])

  const medios = useMemo(
    () => Object.entries(datos?.totales ?? {}).sort((a, b) => b[1].ingresos - a[1].ingresos),
    [datos],
  )

  const saldo = (datos?.total_ingresos ?? 0) - (datos?.total_egresos ?? 0)
  const urlDelCsv =
    `/api/caja/reportes/por-medio/export?desde=${desde}&hasta=${hasta}&caja_id=${cajaId}`

  return (
    <div className="space-y-4">
      <EncabezadoDePantalla
        titulo={<TituloPantalla icono={Wallet}>Caja por medio de pago</TituloPantalla>}
      >
        <Link
          to="/caja"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          <ArrowLeft className="size-4" /> Volver a la caja
        </Link>
      </EncabezadoDePantalla>

      <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-3">
        <div className="grid gap-1.5">
          <Label htmlFor="desde">Desde</Label>
          <Input
            id="desde" type="date" className="w-40"
            value={desde} onChange={(e) => setDesde(e.target.value)}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="hasta">Hasta</Label>
          <Input
            id="hasta" type="date" className="w-40"
            value={hasta} onChange={(e) => setHasta(e.target.value)}
          />
        </div>
        {/* Con un solo mostrador el selector no dice nada: la única opción
            además de «todos» es ése mismo. */}
        {mostradores.length > 1 && (
          <div className="grid gap-1.5">
            <Label htmlFor="mostrador">Mostrador</Label>
            <select
              id="mostrador"
              className="h-9 rounded-md border bg-transparent px-3 text-sm"
              value={cajaId}
              onChange={(e) => setCajaId(e.target.value)}
            >
              <option value="0">Todos</option>
              {mostradores.map((c) => (
                <option key={c.id} value={String(c.id)}>{c.nombre}</option>
              ))}
            </select>
          </div>
        )}
        {/* 🔑 Un `<a>` y no un `fetch`: la descarga la hace el navegador con la
            cookie de sesión, que viaja sola por ser el mismo origen. Bajar el
            CSV con fetch obligaría a armar un blob y un click sintético para
            nada. */}
        <Button asChild variant="outline" size="sm" className="ml-auto">
          <a href={urlDelCsv}>
            <Download className="size-4" /> Exportar CSV
          </a>
        </Button>
      </div>

      <AvisoDeError mensaje={error} />

      {cargando ? (
        <p className="text-muted-foreground">Cargando…</p>
      ) : medios.length === 0 ? (
        /* Un período sin movimientos y una consulta rota se ven igual si la
           pantalla queda en blanco. Se dice cuál de las dos es. */
        <p className="text-muted-foreground">
          No hubo movimientos de caja en este período.
        </p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Tarjeta titulo="Ingresos" valor={pesos(datos!.total_ingresos)} tono="text-emerald-700 dark:text-emerald-400" />
            <Tarjeta titulo="Egresos" valor={pesos(datos!.total_egresos)} tono="text-destructive" />
            <Tarjeta
              titulo="Saldo"
              valor={pesos(saldo)}
              tono={saldo >= 0 ? '' : 'text-destructive'}
            />
          </div>

          <section className="rounded-lg border bg-card p-4">
            <h2 className="mb-3 font-medium">Por medio de pago</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b text-muted-foreground">
                  <tr>
                    <th className="py-2 pr-3 text-left font-medium">Medio</th>
                    <th className="py-2 pr-3 text-center font-medium">Ops.</th>
                    <th className="py-2 pr-3 text-right font-medium">Ingresos</th>
                    <th className="py-2 pr-3 text-right font-medium">Egresos</th>
                    <th className="py-2 text-right font-medium">Saldo</th>
                  </tr>
                </thead>
                <tbody>
                  {medios.map(([medio, vals]) => {
                    const Icono = iconoDe(medio)
                    const propio = vals.ingresos - vals.egresos
                    return (
                      <tr key={medio} className="border-b last:border-0">
                        <td className="py-2 pr-3">
                          <span className="flex items-center gap-2">
                            <Icono className="size-4 text-muted-foreground" aria-hidden />
                            {etiquetaDeMedio(medio)}
                          </span>
                        </td>
                        <td className="py-2 pr-3 text-center text-muted-foreground">
                          {vals.ingresos_ops}
                        </td>
                        <td className="py-2 pr-3 text-right font-medium text-emerald-700 dark:text-emerald-400">
                          {pesos(vals.ingresos)}
                        </td>
                        <td className="py-2 pr-3 text-right text-destructive">
                          {vals.egresos > 0 ? pesos(vals.egresos) : '—'}
                        </td>
                        <td className="py-2 text-right font-medium">{pesos(propio)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {/* Con un solo mostrador esta sección repetiría la de arriba fila por
              fila. Aparece cuando hay más de uno, que es cuando dice algo. */}
          {datos!.cajas.length > 1 && (
            <section className="rounded-lg border bg-card p-4">
              <h2 className="mb-3 font-medium">Por mostrador</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b text-muted-foreground">
                    <tr>
                      <th className="py-2 pr-3 text-left font-medium">Mostrador</th>
                      <th className="py-2 pr-3 text-right font-medium">Ingresos</th>
                      <th className="py-2 pr-3 text-right font-medium">Egresos</th>
                      <th className="py-2 text-right font-medium">Saldo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {datos!.cajas.map((c) => (
                      <tr key={c.id} className="border-b last:border-0">
                        <td className="py-2 pr-3">{c.nombre}</td>
                        <td className="py-2 pr-3 text-right text-emerald-700 dark:text-emerald-400">
                          {pesos(c.total_ingresos)}
                        </td>
                        <td className="py-2 pr-3 text-right text-destructive">
                          {c.total_egresos > 0 ? pesos(c.total_egresos) : '—'}
                        </td>
                        <td className="py-2 text-right font-medium">{pesos(c.saldo)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function Tarjeta({ titulo, valor, tono }: { titulo: string; valor: string; tono: string }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-sm text-muted-foreground">{titulo}</p>
      <p className={`text-2xl font-medium ${tono}`}>{valor}</p>
    </div>
  )
}
