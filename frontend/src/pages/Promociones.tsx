import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from 'libra-ui/data-table'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { BadgePercent, Plus } from 'lucide-react'

import { canchas as apiCanchas, promociones as api } from '@/lib/api'
import type { Cancha, Promocion } from '@/lib/api'
import { fecha } from '@/lib/fechas'
import { useSucursal } from '@/context/SucursalContext'
import { useAuth } from '@/context/AuthContext'
import { DIAS_CORTOS, FormularioDePromocion } from '@/components/FormularioDePromocion'
import { AvisoDeError, columnaDeAcciones, filaInactiva } from '@/components/listado'
import { Button } from '@/components/ui/button'

/** Cómo se leen los días de una promoción: «Todos los días», «Lun a Jue» o «Lun, Mié, Vie». */
export function textoDeDias(dias: number[] | null): string {
  if (dias === null) return 'Todos los días'
  const orden = [...dias].sort((a, b) => a - b)
  const seguidos = orden.length > 2 && orden.every((d, i) => i === 0 || d === orden[i - 1] + 1)
  if (seguidos) return `${DIAS_CORTOS[orden[0]]} a ${DIAS_CORTOS[orden[orden.length - 1]]}`
  return orden.map((d) => DIAS_CORTOS[d]).join(', ')
}

/** La vigencia en dos renglones («01-11-2026» / «al 15-11-2026»): en una sola línea el rango
 *  completo ensancha la tabla más de lo que entra en un notebook. */
function vigencia(p: Promocion): string[] {
  if (!p.vigente_desde && !p.vigente_hasta) return ['Siempre']
  if (p.vigente_desde && p.vigente_hasta) return [fecha(p.vigente_desde), `al ${fecha(p.vigente_hasta)}`]
  return p.vigente_desde ? [`Desde el ${fecha(p.vigente_desde)}`] : [`Hasta el ${fecha(p.vigente_hasta)}`]
}

export function Promociones() {
  const { actual } = useSucursal()
  const { user } = useAuth()
  const [filas, setFilas] = useState<Promocion[]>([])
  const [canchas, setCanchas] = useState<Cancha[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editando, setEditando] = useState<Promocion | null>(null)
  const [abierto, setAbierto] = useState(false)

  // Igual que Tarifas: el backend gatea con `require_admin` y la pantalla no ofrece botones que
  // van a dar 403. El mostrador las ve (sirve para explicar por qué un turno salió más barato).
  const puedeEscribir = user?.role === 'admin'

  const recargar = useCallback(() => {
    Promise.all([api.listar(), apiCanchas.listar()])
      .then(([p, c]) => {
        setFilas(p)
        setCanchas(c)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(recargar, [recargar])

  const propias = filas.filter((p) => actual === null || p.sucursal_id === actual)
  const deLaSucursal = canchas.filter((c) => actual === null || c.sucursal_id === actual)

  const nombreCancha = useCallback(
    (id: number | null) =>
      id === null ? 'Toda la sucursal' : (canchas.find((c) => c.id === id)?.nombre ?? `#${id}`),
    [canchas],
  )

  const borrar = useCallback(
    async (promo: Promocion) => {
      if (!confirm(`¿Borrar la promoción "${promo.nombre}"?`)) return
      setError(null)
      try {
        await api.borrar(promo.id)
        recargar()
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [recargar],
  )

  const columnas = useMemo<ColumnDef<Promocion, unknown>[]>(() => {
    const base: ColumnDef<Promocion, unknown>[] = [
      {
        accessorKey: 'nombre',
        header: sortableHeader('Nombre'),
        cell: ({ row }) => (
          <span className="font-medium">
            {row.original.nombre}
            {!row.original.activa && (
              <span className="ml-2 text-xs text-muted-foreground">(inactiva)</span>
            )}
          </span>
        ),
      },
      {
        accessorKey: 'descuento_porcentaje',
        header: sortableHeader('Descuento'),
        cell: ({ row }) => (
          <BadgeEstado tono="ok">{`${row.original.descuento_porcentaje}% menos`}</BadgeEstado>
        ),
      },
      {
        id: 'dias',
        header: 'Días',
        cell: ({ row }) => (
          <div>
            {textoDeDias(row.original.dias_semana)}
            {row.original.aplica_en_feriados && (
              <div className="text-xs text-muted-foreground">y feriados</div>
            )}
          </div>
        ),
      },
      {
        id: 'franja',
        header: 'Franja',
        cell: ({ row }) =>
          `${row.original.hora_desde.slice(0, 5)} – ${row.original.hora_hasta.slice(0, 5)}`,
      },
      {
        id: 'cancha',
        header: 'Cancha',
        cell: ({ row }) => nombreCancha(row.original.cancha_id),
      },
      {
        id: 'vigencia',
        header: 'Vigencia',
        cell: ({ row }) => (
          <div>
            {vigencia(row.original).map((linea) => (
              <div key={linea}>{linea}</div>
            ))}
          </div>
        ),
      },
    ]
    if (!puedeEscribir) return base
    return [
      ...base,
      columnaDeAcciones<Promocion>({
        onEditar: (p) => {
          setEditando(p)
          setAbierto(true)
        },
        onBorrar: borrar,
        nombreDe: (p) => p.nombre,
      }),
    ]
  }, [puedeEscribir, borrar, nombreCancha])

  return (
    <div className="space-y-3">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={BadgePercent}>Promociones</TituloPantalla>}>
        {puedeEscribir && actual !== null && (
          <Button
            onClick={() => {
              setEditando(null)
              setAbierto(true)
            }}
          >
            <Plus className="size-4" />
            Nueva promoción
          </Button>
        )}
      </EncabezadoDePantalla>

      <p className="text-sm text-muted-foreground">
        Un porcentaje menos sobre la tarifa, para una franja y una vigencia: sirve para la hora
        valle y para las promociones de temporada. Aplica en el mostrador y en la página de
        reservas; si coinciden varias, gana la que más descuenta.
      </p>

      <AvisoDeError mensaje={error} />

      <DataTable
        columns={columnas}
        data={propias}
        getRowClassName={(p) => filaInactiva(p.activa)}
        emptyMessage="Sin promociones cargadas. Los turnos se cobran a la tarifa."
        // Se busca sobre lo que se VE (como en Tarifas): la columna Cancha guarda un id y muestra un nombre.
        search={{
          campos: (p) => [p.nombre, textoDeDias(p.dias_semana), nombreCancha(p.cancha_id)],
          placeholder: 'Buscar por nombre, día o cancha',
          ariaLabel: 'Buscar promoción',
        }}
      />

      {actual !== null && (
        <FormularioDePromocion
          abierto={abierto}
          promocion={editando}
          canchas={deLaSucursal}
          sucursalId={actual}
          onCerrar={() => setAbierto(false)}
          onGuardada={() => {
            setAbierto(false)
            recargar()
          }}
        />
      )}
    </div>
  )
}
