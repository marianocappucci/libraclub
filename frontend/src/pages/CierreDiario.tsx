/** El cierre diario: el acto registrado de cerrar el día operativo de la
 * sucursal activa, con el ticket de 80 mm del comprobante.
 *
 * Pedido del humano (2026-09-13): «cierre diario con comprobante impreso en
 * VentaLibra y LibraClub». El motor (LibraCore v1.98.0, ADR-011) numera por
 * sucursal, exige los turnos del día cerrados y guarda una foto que no se
 * recalcula al reimprimir — acá sólo se muestra lo que el backend calculó.
 *
 * 🔑 **El día operativo es el de la fecha elegida, no "hoy" a secas.** Por eso
 * hay un selector de fecha: un complejo que cierra a la mañana quiere poder
 * cerrar el día de ayer sin esperar a la medianoche, y el motor identifica el
 * día por la apertura del turno en hora AR, no por cuándo se aprieta el botón.
 *
 * 🔴 **Quién puede cerrar lo decide el backend** (`autorizar_cierre`, admin o
 * staff — el cajero de este producto). Acá no hay ningún chequeo de rol: el
 * botón se deshabilita por ESTADO (turnos abiertos, día ya cerrado), nunca por
 * rol, porque cualquiera que llega a esta pantalla ya pasó el gate del router.
 */
import { useCallback, useEffect, useState } from 'react'
import { ClipboardCheck, Printer } from 'lucide-react'
import { hoyISO } from 'libra-ui/fechas'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import { cierreDiario } from '@/lib/api'
import type { CierreDiario as CierreDiarioFila, PreviewDeCierreDiario } from '@/lib/api'
import { fecha, fechaHora, pesos } from '@/lib/fechas'
import { abrirTicket } from '@/lib/tickets'
import { useSucursal } from '@/context/SucursalContext'
import { useMediosDePago } from '@/lib/medios-pago'
import { AvisoDeError } from '@/components/listado'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DiferenciaDeArqueo } from '@/pages/TurnosDeCaja'

export function CierreDiario() {
  const { actual } = useSucursal()
  const [fechaElegida, setFechaElegida] = useState(hoyISO())
  const [preview, setPreview] = useState<PreviewDeCierreDiario | null>(null)
  const [listado, setListado] = useState<CierreDiarioFila[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [confirmando, setConfirmando] = useState(false)
  const [cerrando, setCerrando] = useState(false)
  const { etiqueta: etiquetaDeMedio } = useMediosDePago()

  const recargarPreview = useCallback(() => {
    if (actual === null) return
    setCargando(true)
    setError(null)
    cierreDiario
      .preview(actual, fechaElegida)
      .then(setPreview)
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [actual, fechaElegida])

  const recargarListado = useCallback(() => {
    if (actual === null) return
    cierreDiario
      .listar(actual)
      .then(setListado)
      .catch(() => setListado([]))
  }, [actual])

  useEffect(recargarPreview, [recargarPreview])
  useEffect(recargarListado, [recargarListado])

  const cerrarElDia = async () => {
    if (actual === null) return
    setCerrando(true)
    setError(null)
    try {
      await cierreDiario.cerrar(actual, fechaElegida)
      setConfirmando(false)
      recargarPreview()
      recargarListado()
    } catch (e) {
      // El error del servidor (422 turnos abiertos, 409 ya cerrado) se
      // muestra tal cual: es el que explica por qué no se pudo, y el
      // deshabilitado del botón ya cubre el caso esperable.
      setError((e as Error).message)
      setConfirmando(false)
    } finally {
      setCerrando(false)
    }
  }

  const bloqueado = (preview?.turnos_abiertos.length ?? 0) > 0 || (preview?.ya_cerrado ?? false)

  return (
    <div className="space-y-4">
      <EncabezadoDePantalla
        titulo={<TituloPantalla icono={ClipboardCheck}>Cierre diario</TituloPantalla>}
      />
      <AvisoDeError mensaje={error} />

      <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-3">
        <div className="grid gap-1.5">
          <Label htmlFor="fecha-cierre">Día operativo</Label>
          <Input
            id="fecha-cierre" type="date" className="w-40"
            value={fechaElegida} onChange={(e) => setFechaElegida(e.target.value)}
          />
        </div>
      </div>

      {cargando ? (
        <p className="text-muted-foreground">Cargando…</p>
      ) : preview === null ? null : (
        <>
          {preview.turnos_abiertos.length > 0 && (
            <section className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
              <p className="font-medium text-amber-800 dark:text-amber-400">
                Hay {preview.turnos_abiertos.length} turno
                {preview.turnos_abiertos.length !== 1 ? 's' : ''} abierto
                {preview.turnos_abiertos.length !== 1 ? 's' : ''}: hay que cerrarlo
                {preview.turnos_abiertos.length !== 1 ? 's' : ''} antes de cerrar el día.
              </p>
              <ul className="space-y-1 text-sm text-amber-800 dark:text-amber-400">
                {preview.turnos_abiertos.map((t) => (
                  <li key={t.id}>
                    Turno #{t.id} — {t.usuario_nombre}, {t.caja_nombre || 'sin mostrador'},
                    {' '}abierto {fechaHora(t.apertura)}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {preview.ya_cerrado && (
            <section className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
              El día {fecha(fechaElegida)} ya está cerrado en esta sucursal.
            </section>
          )}

          {preview.turnos.length > 0 && (
            <section className="rounded-lg border bg-card p-4">
              <h2 className="mb-3 font-medium">Turnos del día</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b text-muted-foreground">
                    <tr>
                      <th className="py-2 pr-3 text-left font-medium">Cajero</th>
                      <th className="py-2 pr-3 text-left font-medium">Mostrador</th>
                      <th className="py-2 pr-3 text-right font-medium">Esperado</th>
                      <th className="py-2 pr-3 text-right font-medium">Declarado</th>
                      <th className="py-2 text-right font-medium">Diferencia</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.turnos.map((t) => (
                      <tr key={t.id} className="border-b last:border-0">
                        <td className="py-2 pr-3">{t.usuario_nombre}</td>
                        <td className="py-2 pr-3">{t.caja_nombre || 'sin mostrador'}</td>
                        <td className="py-2 pr-3 text-right">{pesos(t.monto_esperado_cierre)}</td>
                        <td className="py-2 pr-3 text-right">{pesos(t.monto_declarado_cierre)}</td>
                        <td className="py-2 text-right">
                          <DiferenciaDeArqueo
                            esperado={t.monto_esperado_cierre}
                            declarado={t.monto_declarado_cierre}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {preview.medios.length > 0 && (
                <div className="mt-4 grid gap-1.5 text-sm">
                  <h3 className="font-medium">Por medio de pago</h3>
                  {preview.medios.map((m) => (
                    <div key={m.medio_pago} className="flex justify-between">
                      <span className="text-muted-foreground">{etiquetaDeMedio(m.medio_pago)}</span>
                      <span>{pesos(m.neto)}</span>
                    </div>
                  ))}
                </div>
              )}

              <dl className="mt-4 grid gap-1.5 border-t pt-3 text-sm">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Esperado</dt>
                  <dd>{pesos(preview.monto_esperado_total)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Declarado</dt>
                  <dd>{pesos(preview.monto_declarado_total)}</dd>
                </div>
                <div className="flex justify-between font-medium">
                  <dt>Diferencia</dt>
                  <dd>
                    <DiferenciaDeArqueo
                      esperado={preview.monto_esperado_total}
                      declarado={preview.monto_declarado_total}
                    />
                  </dd>
                </div>
              </dl>
            </section>
          )}

          <Button disabled={bloqueado} onClick={() => setConfirmando(true)}>
            Cerrar el día
          </Button>
        </>
      )}

      <ConfirmDialog
        open={confirmando}
        onOpenChange={setConfirmando}
        title="Cerrar el día"
        description="Esta acción no se puede deshacer: el cierre queda numerado y registrado, con su ticket."
        confirmLabel={cerrando ? 'Cerrando…' : 'Cerrar el día'}
        onConfirm={cerrarElDia}
      />

      <section className="rounded-lg border bg-card p-4">
        <h2 className="mb-3 font-medium">Cierres de esta sucursal</h2>
        {listado.length === 0 ? (
          <p className="text-sm text-muted-foreground">Todavía no se cerró ningún día.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b text-muted-foreground">
                <tr>
                  <th className="py-2 pr-3 text-left font-medium">N°</th>
                  <th className="py-2 pr-3 text-left font-medium">Fecha</th>
                  <th className="py-2 pr-3 text-left font-medium">Cerrado por</th>
                  <th className="py-2 pr-3 text-right font-medium">Diferencia</th>
                  <th className="py-2 text-right font-medium">Ticket</th>
                </tr>
              </thead>
              <tbody>
                {listado.map((c) => (
                  <tr key={c.id} className="border-b last:border-0">
                    <td className="py-2 pr-3 text-muted-foreground">{c.numero}</td>
                    <td className="py-2 pr-3">{fecha(c.fecha)}</td>
                    <td className="py-2 pr-3">{c.cerrado_por_nombre}</td>
                    <td className="py-2 pr-3 text-right">
                      <DiferenciaDeArqueo
                        esperado={c.monto_esperado_total}
                        declarado={c.monto_declarado_total}
                      />
                    </td>
                    <td className="py-2 text-right">
                      <Button
                        size="sm" variant="outline"
                        onClick={() => abrirTicket(cierreDiario.urlDelTicket(c.id))}
                      >
                        <Printer className="size-4" /> Imprimir ticket
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
