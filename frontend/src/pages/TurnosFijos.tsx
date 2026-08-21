/** Canchas fijas: "los martes a las 20:00, la cancha 3, el grupo de Juan".
 *
 * 🔴 **El backend existía desde F1 y no tenía pantalla**, así que esto sólo se
 * podía cargar por API. Es la feature que el humano pidió primero de las cuatro
 * y la más barata justamente por eso.
 *
 * 🔑 **La columna que decide si la pantalla sirve es «Generados hasta».** Una
 * cancha fija sin fecha de fin no genera turnos infinitos: se materializa una
 * ventana de 90 días y hay que extenderla. Sin verla, esa ventana se agota y el
 * grupo llega un martes y el turno está libre para cualquiera — sin que nada
 * haya fallado y sin nada que mirar para darse cuenta.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { AlertTriangle, Plus } from 'lucide-react'

import {
  canchas as apiCanchas, clientes as apiClientes, series as api,
} from '@/lib/api'
import type { Cancha, Cliente, Serie, SerieCreada } from '@/lib/api'
import { fecha } from '@/lib/fechas'
import { useSucursal } from '@/context/SucursalContext'
import { FormularioDeSerie } from '@/components/FormularioDeSerie'
import { ResultadoDeSerie } from '@/components/ResultadoDeSerie'
import { AvisoDeError, filaInactiva } from '@/components/listado'
import { Button } from '@/components/ui/button'

const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

/** Cuántos días faltan para que se agote la ventana de turnos generados. */
function diasRestantes(hasta: string | null): number | null {
  if (hasta === null) return null
  const dif = new Date(`${hasta}T00:00:00`).getTime() - new Date().setHours(0, 0, 0, 0)
  return Math.round(dif / 86_400_000)
}

/** 🔑 Se avisa con **tres semanas** de anticipación, no cuando ya se agotó.
 *  Extender es un click, pero hay que estar mirando la pantalla: si el aviso
 *  apareciera el día que se acaba, el primer martes sin turno ya pasó. */
const DIAS_PARA_AVISAR = 21

export function TurnosFijos() {
  const { actual } = useSucursal()
  const [filas, setFilas] = useState<Serie[]>([])
  const [canchas, setCanchas] = useState<Cancha[]>([])
  const [clientes, setClientes] = useState<Cliente[]>([])
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)
  const [abierto, setAbierto] = useState(false)
  const [ultimo, setUltimo] = useState<SerieCreada | null>(null)

  const recargar = useCallback(() => {
    setCargando(true)
    Promise.all([api.listar(), apiCanchas.listar(), apiClientes.listar()])
      .then(([s, ca, cl]) => {
        setFilas(s)
        setCanchas(ca)
        setClientes(cl)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [])

  useEffect(recargar, [recargar])

  const deLaSucursal = canchas.filter((c) => actual === null || c.sucursal_id === actual)
  const idsDeLaSucursal = new Set(deLaSucursal.map((c) => c.id))
  const propias = filas.filter((s) => actual === null || idsDeLaSucursal.has(s.cancha_id))

  const extender = useCallback(
    async (serie: Serie) => {
      setError(null)
      setUltimo(null)
      try {
        setUltimo(await api.extender(serie.id))
        recargar()
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [recargar],
  )

  const darDeBaja = useCallback(
    async (serie: Serie) => {
      // 🔴 El conteo va en la pregunta. "¿Dar de baja?" a secas esconde que se
      // van a cancelar diez turnos ya vendidos, que es la parte que el operador
      // necesita saber ANTES de apretar.
      const texto =
        serie.proximas > 0
          ? `Se va a dar de baja la cancha fija de ${serie.cliente} y a cancelar ` +
            `sus ${serie.proximas} turnos futuros. Los que ya pasaron no se tocan. ¿Seguís?`
          : `Se va a dar de baja la cancha fija de ${serie.cliente}. No tiene turnos futuros.`
      if (!confirm(texto)) return
      setError(null)
      try {
        const r = await api.darDeBaja(serie.id, { cancelar_futuras: true })
        setUltimo(null)
        recargar()
        if (r.canceladas > 0) {
          setError(null)
        }
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [recargar],
  )

  const columnas = useMemo<ColumnDef<Serie, unknown>[]>(
    () => [
      {
        id: 'cuando',
        header: sortableHeader('Cuándo'),
        accessorFn: (s) => `${s.dia_semana}-${s.hora}`,
        cell: ({ row }) => (
          <span className="font-medium">
            {DIAS[row.original.dia_semana]} {row.original.hora.slice(0, 5)}
            {!row.original.activa && (
              <span className="ml-2 text-xs text-muted-foreground">(dada de baja)</span>
            )}
          </span>
        ),
      },
      { accessorKey: 'cliente', header: sortableHeader('Cliente') },
      { accessorKey: 'cancha', header: 'Cancha' },
      {
        id: 'duracion',
        header: 'Duración',
        cell: ({ row }) => `${row.original.duracion_min} min`,
      },
      {
        id: 'vigencia',
        header: 'Vigencia',
        cell: ({ row }) =>
          row.original.hasta
            ? `${fecha(row.original.desde)} – ${fecha(row.original.hasta)}`
            : `desde ${fecha(row.original.desde)}`,
      },
      {
        id: 'generados',
        header: 'Generados hasta',
        cell: ({ row }) => <Generados serie={row.original} />,
      },
      {
        id: 'acciones',
        header: '',
        cell: ({ row }) =>
          row.original.activa ? (
            <div className="flex justify-end gap-1">
              <Button variant="outline" size="sm" onClick={() => extender(row.original)}>
                Extender
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`Dar de baja la cancha fija de ${row.original.cliente}`}
                onClick={() => darDeBaja(row.original)}
              >
                Dar de baja
              </Button>
            </div>
          ) : null,
      },
    ],
    [extender, darDeBaja],
  )

  if (cargando) return <p className="text-muted-foreground">Cargando…</p>

  const porVencer = propias.filter((s) => {
    if (!s.activa) return false
    const d = diasRestantes(s.materializada_hasta)
    return d === null || d <= DIAS_PARA_AVISAR
  })

  return (
    <div className="space-y-3">
      <EncabezadoDePantalla titulo={<h1 className="text-lg font-semibold">Turnos fijos</h1>}>
        {deLaSucursal.length > 0 && clientes.length > 0 && (
          <Button onClick={() => setAbierto(true)}>
            <Plus className="size-4" />
            Nueva cancha fija
          </Button>
        )}
      </EncabezadoDePantalla>

      <p className="text-sm text-muted-foreground">
        El grupo que juega siempre el mismo día y a la misma hora. Los turnos se
        generan por adelantado: una cancha fija sin fecha de fin cubre los
        próximos 90 días y después hay que <strong>extenderla</strong>.
      </p>

      {porVencer.length > 0 && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>
            <span className="font-medium">Hay que extender:</span>{' '}
            {porVencer.map((s) => `${s.cliente} (${DIAS[s.dia_semana]})`).join(', ')}.
            Si no, esos turnos dejan de aparecer en la agenda.
          </span>
        </div>
      )}

      <AvisoDeError mensaje={error} />

      {ultimo && (
        <div className="rounded-md border bg-card p-3">
          <ResultadoDeSerie
            creadas={ultimo.creadas.length}
            salteadas={ultimo.salteadas}
          />
        </div>
      )}

      <DataTable
        columns={columnas}
        data={propias}
        getRowClassName={(s) => filaInactiva(s.activa)}
        emptyMessage="Sin canchas fijas. El grupo que juega todos los martes va acá."
        search={{
          campos: (s) => [s.cliente, s.cancha, DIAS[s.dia_semana]],
          placeholder: 'Buscar por cliente, cancha o día',
          ariaLabel: 'Buscar cancha fija',
        }}
      />

      <FormularioDeSerie
        abierto={abierto}
        canchas={deLaSucursal}
        clientes={clientes}
        onCerrar={() => setAbierto(false)}
        onCreada={recargar}
      />
    </div>
  )
}

/** Hasta cuándo hay turnos, y si eso está por agotarse. */
function Generados({ serie }: { serie: Serie }) {
  if (serie.materializada_hasta === null) {
    // 🔴 Distinto de "está por vencer": acá NO hay ni un turno generado. Pasa
    // cuando todas las ocurrencias se saltearon —sin tarifa, fuera de horario—
    // y la serie existe sin estar funcionando.
    return (
      <span className="text-amber-700 dark:text-amber-500">Ningún turno generado</span>
    )
  }
  const dias = diasRestantes(serie.materializada_hasta)!
  const texto = fecha(serie.materializada_hasta)
  if (!serie.activa) return <span className="text-muted-foreground">{texto}</span>
  return (
    <span className={dias <= DIAS_PARA_AVISAR ? 'text-amber-700 dark:text-amber-500' : ''}>
      {texto}
      <span className="ml-1 text-xs text-muted-foreground">
        ({dias <= 0 ? 'vencido' : `faltan ${dias} d`})
      </span>
    </span>
  )
}
