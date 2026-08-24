/** El portal público: elegir cancha, día y turno, y pagar.
 *
 * 🔑 **Se puede mirar sin registrarse.** La cuenta se pide recién al apretar un
 * turno: pedirla antes de que el jugador vea si hay lugar el viernes es la forma
 * más rápida de que se vaya.
 *
 * 🔴 **El turno se retiene PROVISORIO y sólo el pago lo confirma.** Por eso la
 * pantalla muestra el reloj: un turno que desaparece sin aviso mientras el
 * jugador completa la tarjeta es la peor versión de esto.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Clock, MapPin } from 'lucide-react'

import { portal } from '@/lib/api'
import type { CanchaPublica, ReservaCreada, TurnoLibre } from '@/lib/api'
import { hora, pesos } from '@/lib/fechas'
import { useJugador } from '@/portal/JugadorContext'
import { DialogoDeCuenta } from '@/portal/DialogoDeCuenta'
import { DialogoDePago } from '@/portal/DialogoDePago'
import { AvisoDeError } from '@/components/listado'
import { enDiasISO, hoyISO } from 'libra-ui/fechas'

/** La sucursal que atiende este portal.
 *
 * ⚠️ Hoy es la primera y punto: una instancia de LibraClub es de **un**
 * complejo, y las que tienen más de una sede todavía no venden por internet.
 * Cuando eso pase, el portal necesita un selector — y este comentario es el
 * lugar donde va a estar la deuda.
 */
const SUCURSAL = 1

/** Los próximos días, para el selector. Sin calendario: en un complejo se
 *  reserva para esta semana, no para dentro de tres meses. */
const DIAS = Array.from({ length: 14 }, (_, i) => enDiasISO(i))

const NOMBRE_DIA = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb']

export function PortalReservar() {
  const { jugador } = useJugador()
  const [canchas, setCanchas] = useState<CanchaPublica[]>([])
  const [canchaId, setCanchaId] = useState<number | null>(null)
  const [dia, setDia] = useState(hoyISO)
  const [turnos, setTurnos] = useState<TurnoLibre[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pidiendoCuenta, setPidiendoCuenta] = useState<TurnoLibre | null>(null)
  const [reservado, setReservado] = useState<ReservaCreada | null>(null)

  useEffect(() => {
    portal
      .canchas(SUCURSAL)
      .then((c) => {
        setCanchas(c)
        setCanchaId((actual) => actual ?? c[0]?.id ?? null)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [])

  const recargar = useCallback(() => {
    if (canchaId === null) return
    setError(null)
    portal
      .disponibilidad(canchaId, dia)
      .then(setTurnos)
      .catch((e: Error) => setError(e.message))
  }, [canchaId, dia])

  useEffect(recargar, [recargar])

  const cancha = useMemo(
    () => canchas.find((c) => c.id === canchaId) ?? null,
    [canchas, canchaId],
  )

  async function tomar(turno: TurnoLibre) {
    // 🔑 Si no hay cuenta se pide ACÁ y no antes: el jugador ya vio que hay
    // lugar, así que registrarse tiene sentido para él.
    if (!jugador) {
      setPidiendoCuenta(turno)
      return
    }
    setError(null)
    try {
      setReservado(
        await portal.reservar({ cancha_id: canchaId!, comienza_at: turno.comienza_at }),
      )
      recargar()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (cargando) return <p className="p-6 text-muted-foreground">Cargando…</p>

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <AvisoDeError mensaje={error} />

      {canchas.length === 0 ? (
        <p className="text-muted-foreground">
          Este complejo todavía no publicó sus canchas.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {canchas.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setCanchaId(c.id)}
                aria-pressed={c.id === canchaId}
                className={`rounded-md border px-3 py-2 text-sm ${
                  c.id === canchaId ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
                }`}
              >
                {c.nombre}
                {c.techada && (
                  <span className="ml-2 text-xs opacity-80">techada</span>
                )}
              </button>
            ))}
          </div>

          <div className="flex gap-2 overflow-x-auto pb-1">
            {DIAS.map((d) => {
              const f = new Date(`${d}T12:00:00`)
              return (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDia(d)}
                  aria-pressed={d === dia}
                  className={`shrink-0 rounded-md border px-3 py-2 text-center text-sm ${
                    d === dia ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
                  }`}
                >
                  <div className="text-xs opacity-80">{NOMBRE_DIA[f.getDay()]}</div>
                  <div className="font-medium">{f.getDate()}</div>
                </button>
              )
            })}
          </div>

          {cancha && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <MapPin className="size-4" />
              {cancha.nombre} · turnos de {cancha.duracion_turno_min} min
            </p>
          )}

          {turnos.length === 0 ? (
            // 🔑 Se dice POR QUÉ puede estar vacío. "No hay turnos" a secas
            // deja al jugador sin saber si el complejo cierra ese día o si ya
            // se vendió todo.
            <p className="rounded-md border bg-card p-4 text-sm text-muted-foreground">
              No quedan turnos libres para ese día en esta cancha. Probá con otro
              día o con otra cancha.
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {turnos.map((t) => (
                <button
                  key={t.comienza_at}
                  type="button"
                  onClick={() => tomar(t)}
                  className="rounded-lg border bg-card p-3 text-left hover:border-primary"
                >
                  <div className="flex items-center gap-1 font-medium">
                    <Clock className="size-4" />
                    {hora(t.comienza_at)}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {pesos(String(t.precio))}
                  </div>
                </button>
              ))}
            </div>
          )}
        </>
      )}

      <DialogoDeCuenta
        abierto={pidiendoCuenta !== null}
        onCerrar={() => setPidiendoCuenta(null)}
        onEntro={async () => {
          const turno = pidiendoCuenta
          setPidiendoCuenta(null)
          if (turno) await tomar(turno)
        }}
      />
      <DialogoDePago
        reserva={reservado}
        onCerrar={() => {
          setReservado(null)
          recargar()
        }}
      />
    </div>
  )
}
