/** Un turno de caja cerrado, con su arqueo y sus movimientos.
 *
 * Es a dónde lleva el historial, y lo que hace que ese listado sirva para algo:
 * sin esto, la lista de turnos no se puede abrir.
 *
 * 🔑 **Muestra el arqueo, no lo calcula.** Los totales por medio y el esperado
 * salen del backend; acá sólo se restan esperado y declarado para la
 * diferencia, que es una resta de dos números que ya vinieron. Sumar
 * movimientos del lado de la pantalla es cómo dos vistas terminan diciendo
 * números distintos sobre la misma caja.
 *
 * ⚠️ **La lista de movimientos es de sólo lectura y no lleva el botón de
 * anular**, al revés que `/caja/movimientos`. Un arqueo cerrado no se toca: el
 * backend ya lo rechaza (`anular` exige turno abierto), y ofrecer un botón que
 * sólo puede fallar es peor que no ofrecerlo. Sobre un turno abierto tampoco se
 * ofrece acá — para eso está su pantalla, que es donde el operador trabaja.
 */
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Wallet } from 'lucide-react'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { BadgeEstado } from 'libra-ui/badge-estado'

import { caja } from '@/lib/api'
import type { ResumenDeCaja, TurnoDeCaja } from '@/lib/api'
import { useMediosDePago } from '@/lib/medios-pago'
import { fechaHora, hora, pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { DiferenciaDeArqueo } from '@/pages/TurnosDeCaja'

export function TurnoDeCajaDetalle() {
  const { id } = useParams<{ id: string }>()
  const turnoId = Number(id)
  const [turno, setTurno] = useState<TurnoDeCaja | null>(null)
  const [resumen, setResumen] = useState<ResumenDeCaja | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const { etiqueta: etiquetaDeMedio } = useMediosDePago()

  const recargar = useCallback(() => {
    setCargando(true)
    setError(null)
    caja
      .detalle(turnoId)
      .then((d) => {
        setTurno(d.turno)
        setResumen(d.resumen)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [turnoId])

  useEffect(recargar, [recargar])

  return (
    <div className="space-y-4">
      <EncabezadoDePantalla
        titulo={
          <TituloPantalla icono={Wallet}>
            Turno #{Number.isNaN(turnoId) ? '—' : turnoId}
          </TituloPantalla>
        }
      >
        <Link
          to="/caja/turnos"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          <ArrowLeft className="size-4" /> Volver al historial
        </Link>
      </EncabezadoDePantalla>
      <AvisoDeError mensaje={error} />

      {cargando ? (
        <p className="text-muted-foreground">Cargando…</p>
      ) : turno === null ? (
        /* 🔑 El cartel va acá y no se deja la pantalla en blanco. El 403 de un
           turno ajeno y el 404 de uno que no existe llegan los dos por
           `AvisoDeError` con el motivo del backend; esto cubre el hueco de
           abajo, que si no quedaría vacío y parecería que se colgó. */
        <p className="text-muted-foreground">No se pudo mostrar este turno.</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="rounded-lg border bg-card p-4">
            <h2 className="mb-3 flex items-center gap-2 font-medium">
              Datos del turno
              <BadgeEstado tono={turno.estado === 'abierto' ? 'ok' : 'neutro'}>
                {turno.estado === 'abierto' ? 'Abierto' : 'Cerrado'}
              </BadgeEstado>
            </h2>
            <dl className="grid gap-1.5 text-sm">
              <Dato titulo="Cajero" valor={turno.usuario_nombre} />
              <Dato titulo="Mostrador" valor={turno.caja_nombre || 'sin mostrador'} />
              <Dato titulo="Apertura" valor={fechaHora(turno.apertura)} />
              {turno.cierre && <Dato titulo="Cierre" valor={fechaHora(turno.cierre)} />}
              <Dato titulo="Fondo inicial" valor={pesos(turno.monto_inicial)} />
              {turno.notas && <Dato titulo="Notas" valor={turno.notas} />}
            </dl>
          </section>

          <section className="rounded-lg border bg-card p-4">
            <h2 className="mb-3 font-medium">Recaudación por medio</h2>
            {Object.keys(resumen?.pagos_por_medio ?? {}).length === 0 ? (
              <p className="text-sm text-muted-foreground">No entró plata en este turno.</p>
            ) : (
              <dl className="grid gap-1.5 text-sm">
                {Object.entries(resumen!.pagos_por_medio).map(([medio, total]) => (
                  <Dato key={medio} titulo={etiquetaDeMedio(medio)} valor={pesos(total)} />
                ))}
                <div className="mt-1 flex justify-between border-t pt-1.5 font-medium">
                  <span>Total</span>
                  <span>{pesos(resumen?.total_ventas ?? 0)}</span>
                </div>
              </dl>
            )}
          </section>

          {/* Sólo con el turno cerrado: sobre uno abierto no hay declarado
              todavía, y una tarjeta de «resultado del cierre» con guiones invita
              a pensar que el cierre falló.

              ⚠️ **Las tres condiciones no son intercambiables, y una no está
              cubierta por ningún test.** Los dos `!== null` son lo que TypeScript
              necesita para estrechar `number | null` a `number`; sacar cualquiera
              de ellos no compila. `estado !== 'abierto'` es la intención escrita,
              y **es redundante en la práctica**: `cerrar_turno` estampa el estado
              y los dos montos juntos, así que un turno abierto siempre llega con
              los montos en `null`.

              Se comprobó: la mutación que la saca **no pone rojo a nadie**, y no
              porque el test sea flojo sino porque el estado que distinguiría no
              existe. Se deja igual —dice qué se está preguntando, que es más de
              lo que dicen dos chequeos de nulo— sabiendo que lo que la sostiene
              es un invariante del backend y no un test de acá. */}
          {turno.estado !== 'abierto'
            && turno.monto_declarado_cierre !== null
            && turno.monto_esperado_cierre !== null && (
            <section className="rounded-lg border bg-card p-4">
              <h2 className="mb-3 font-medium">Resultado del cierre</h2>
              <dl className="grid gap-1.5 text-sm">
                <Dato titulo="Efectivo esperado" valor={pesos(turno.monto_esperado_cierre)} />
                <Dato titulo="Efectivo declarado" valor={pesos(turno.monto_declarado_cierre)} />
                <div className="mt-1 flex items-center justify-between border-t pt-1.5 font-medium">
                  <span>Diferencia</span>
                  <DiferenciaDeArqueo
                    esperado={turno.monto_esperado_cierre}
                    declarado={turno.monto_declarado_cierre}
                  />
                </div>
              </dl>
            </section>
          )}

          <section className="rounded-lg border bg-card p-4 lg:col-span-2">
            <h2 className="mb-3 font-medium">
              Movimientos <span className="text-muted-foreground">({resumen?.movimientos.length ?? 0})</span>
            </h2>
            {(resumen?.movimientos.length ?? 0) === 0 ? (
              <p className="text-sm text-muted-foreground">No hubo movimientos en este turno.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b text-muted-foreground">
                    <tr>
                      <th className="py-2 pr-3 text-left font-medium">Hora</th>
                      <th className="py-2 pr-3 text-left font-medium">Concepto</th>
                      <th className="py-2 pr-3 text-left font-medium">Medio</th>
                      <th className="py-2 text-right font-medium">Importe</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resumen!.movimientos.map((m) => (
                      <tr key={m.id} className="border-b last:border-0">
                        <td className="py-1.5 pr-3 whitespace-nowrap">{hora(m.fecha)}</td>
                        {/* Los anulados van tachados Y con la palabra, las dos
                            cosas: sólo el tachado se pierde en una impresión en
                            blanco y negro y no lo lee un lector de pantalla.
                            Misma decisión que en /caja/movimientos. */}
                        <td className={`py-1.5 pr-3 ${m.anulado ? 'text-muted-foreground line-through' : ''}`}>
                          {m.concepto}
                        </td>
                        <td className="py-1.5 pr-3">{etiquetaDeMedio(m.medio_pago)}</td>
                        <td className={`py-1.5 text-right whitespace-nowrap ${m.anulado ? 'text-muted-foreground line-through' : ''}`}>
                          {m.tipo === 'egreso' ? '−' : ''}{pesos(m.monto)}
                          {m.anulado ? (
                            <span className="ml-2 text-xs uppercase no-underline">anulado</span>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  )
}

function Dato({ titulo, valor }: { titulo: string; valor: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground">{titulo}</dt>
      <dd className="text-right">{valor}</dd>
    </div>
  )
}
