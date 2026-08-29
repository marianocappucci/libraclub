/** Los mostradores de la sucursal elegida.
 *
 * Una caja es un cajón físico y vive en una sede; una sede puede tener más de
 * uno —el mostrador y el buffet son dos cajones distintos—. El turno se abre
 * **sobre** una caja, y el arqueo del cierre es el de ese cajón.
 *
 * 🔑 **Va en Maestros y no con la Caja**: dar de alta un mostrador es configurar
 * el complejo, como una cancha o una tarifa. Lo que se toca todos los días es el
 * turno, que está en la otra pantalla.
 *
 * El alta, la edición y la baja son de **admin**; el listado lo puede ver el
 * encargado, que es quien elige la caja al abrir su turno.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { Plus, Star, Wallet } from 'lucide-react'

import { cajas as api } from '@/lib/api'
import type { CajaDeMostrador } from '@/lib/api'
import { useSucursal } from '@/context/SucursalContext'
import { useAuth } from '@/context/AuthContext'
import { useMediosDePago } from '@/lib/medios-pago'
import { AvisoDeError, columnaDeAcciones, filaInactiva } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/confirm-dialog'

export function Cajas() {
  const { actual } = useSucursal()
  const { user } = useAuth()
  const puedeEscribir = user?.role === 'admin'
  const { etiqueta: etiquetaDeMedio } = useMediosDePago()

  const [filas, setFilas] = useState<CajaDeMostrador[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editando, setEditando] = useState<CajaDeMostrador | null>(null)
  const [abierto, setAbierto] = useState(false)
  const [aBorrar, setABorrar] = useState<CajaDeMostrador | null>(null)
  //: Qué caja se está marcando. El id y no un booleano: con dos mostradores,
  //  un booleano deshabilitaría los dos botones a la vez.
  const [marcando, setMarcando] = useState<number | null>(null)

  const recargar = useCallback(() => {
    if (actual === null) return
    setCargando(true)
    api
      .deLaSucursal(actual)
      .then(setFilas)
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [actual])

  useEffect(recargar, [recargar])

  const marcarPredeterminada = useCallback(async (caja: CajaDeMostrador) => {
    setMarcando(caja.id)
    setError(null)
    try {
      await api.predeterminada(caja.id)
    } catch (e) {
      setError((e as Error).message)
      return
    } finally {
      setMarcando(null)
    }
    // 🔑 Se recarga la lista entera y no se parchea la fila: marcar una **apaga
    // la anterior**, así que el cambio es de dos filas y no de una. Parchear
    // sólo la tocada dejaría dos pastillas de «Predeterminada» en pantalla
    // hasta el próximo refresco.
    recargar()
  }, [recargar])

  const columnas = useMemo<ColumnDef<CajaDeMostrador>[]>(() => {
    const base: ColumnDef<CajaDeMostrador>[] = [
      { accessorKey: 'nombre', header: sortableHeader('Nombre') },
      { accessorKey: 'descripcion', header: 'Descripción' },
      {
        id: 'medios',
        header: 'Medios que acepta',
        cell: ({ row }) => {
          const medios = row.original.medios_pago
          // Vacío = todos los del producto. Se dice, no se deja en blanco: una
          // celda vacía se lee como "no acepta ninguno".
          if (medios.length === 0) {
            return <span className="text-muted-foreground">Todos</span>
          }
          return medios.map((m) => etiquetaDeMedio(m)).join(' · ')
        },
      },
      {
        id: 'estado',
        header: 'Estado',
        cell: ({ row }) => (
          <div className="flex flex-wrap items-center gap-1.5">
            <BadgeEstado tono={row.original.activo ? 'ok' : 'neutro'}>
              {row.original.activo ? 'Activa' : 'Dada de baja'}
            </BadgeEstado>
            {/* 🔑 **La marca va acá y no en una columna propia.** Es una sola
                caja por sede: una columna entera para una celda con contenido y
                el resto vacías ocupa ancho y no dice más que esto. */}
            {row.original.es_default && (
              <BadgeEstado tono="curso">Predeterminada</BadgeEstado>
            )}
          </div>
        ),
      },
    ]
    if (!puedeEscribir) return base
    return [
      ...base,
      {
        id: 'predeterminada',
        header: '',
        size: 190,
        cell: ({ row }) => {
          // 🔑 Sobre la que YA es predeterminada no se ofrece el botón: apretarlo
          // no haría nada y un control que no cambia nada enseña que la pantalla
          // no responde. Se ve la pastilla de la columna Estado en su lugar.
          if (row.original.es_default) return null
          // Tampoco sobre una dada de baja: sería elegir como predeterminado un
          // cajón sobre el que no se puede abrir turno.
          if (!row.original.activo) return null
          return (
            <Button
              size="sm"
              variant="outline"
              disabled={marcando === row.original.id}
              onClick={() => marcarPredeterminada(row.original)}
            >
              <Star className="size-4" />
              {marcando === row.original.id ? 'Marcando…' : 'Hacer predeterminada'}
            </Button>
          )
        },
      },
      columnaDeAcciones<CajaDeMostrador>({
        onEditar: (c) => { setEditando(c); setAbierto(true) },
        onBorrar: setABorrar,
        nombreDe: (c) => c.nombre,
      }),
    ]
  }, [puedeEscribir, etiquetaDeMedio, marcando, marcarPredeterminada])

  if (actual === null) {
    return <p className="text-muted-foreground">Elegí una sucursal para ver sus cajas.</p>
  }
  if (cargando) return <p className="text-muted-foreground">Cargando…</p>

  return (
    <div className="space-y-3">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={Wallet}>Cajas</TituloPantalla>}>
        {puedeEscribir && (
          <Button onClick={() => { setEditando(null); setAbierto(true) }}>
            <Plus />Nueva caja
          </Button>
        )}
      </EncabezadoDePantalla>
      <AvisoDeError mensaje={error} />

      <DataTable
        columns={columnas}
        data={filas}
        getRowClassName={(c) => filaInactiva(c.activo)}
        emptyMessage="Esta sucursal no tiene ninguna caja. Sin una caja no se puede abrir el turno."
      />

      <FormularioDeCaja
        abierto={abierto}
        caja={editando}
        sucursalId={actual}
        onCerrar={() => setAbierto(false)}
        onGuardada={() => { setAbierto(false); recargar() }}
        onError={setError}
      />

      <ConfirmDialog
        open={aBorrar !== null}
        onOpenChange={(v) => !v && setABorrar(null)}
        title={`¿Dar de baja ${aBorrar?.nombre ?? ''}?`}
        // 🔑 El motor rechaza borrar una caja con movimientos, y está bien: los
        // arqueos viejos quedarían apuntando a nada. Se dice acá para que el
        // 422 no sorprenda.
        description="Si la caja ya tiene movimientos registrados no se puede borrar: en ese caso, editala y marcala como dada de baja."
        confirmLabel="Borrar"
        onConfirm={async () => {
          if (!aBorrar) return
          try {
            await api.borrar(aBorrar.id)
            setABorrar(null)
            recargar()
          } catch (e) {
            setError((e as Error).message)
            setABorrar(null)
          }
        }}
      />
    </div>
  )
}

function FormularioDeCaja({ abierto, caja, sucursalId, onCerrar, onGuardada, onError }: {
  abierto: boolean
  caja: CajaDeMostrador | null
  sucursalId: number
  onCerrar: () => void
  onGuardada: () => void
  onError: (m: string) => void
}) {
  const { medios } = useMediosDePago()
  const [nombre, setNombre] = useState('')
  const [descripcion, setDescripcion] = useState('')
  const [elegidos, setElegidos] = useState<string[]>([])
  const [activo, setActivo] = useState(true)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setNombre(caja?.nombre ?? '')
    setDescripcion(caja?.descripcion ?? '')
    setElegidos(caja?.medios_pago ?? [])
    setActivo(caja?.activo ?? true)
  }, [abierto, caja])

  return (
    <Dialog open={abierto} onOpenChange={(v) => !v && onCerrar()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{caja ? 'Editar caja' : 'Nueva caja'}</DialogTitle>
        </DialogHeader>

        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="nombre-caja">Nombre</Label>
            <Input
              id="nombre-caja"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              placeholder="Mostrador"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="desc-caja">Descripción</Label>
            <Input
              id="desc-caja"
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
            />
          </div>

          <fieldset className="grid gap-1.5">
            {/* Ninguno tildado = todos. Se dice en la leyenda: un formulario con
                todo destildado se lee como "no acepta nada". */}
            <legend className="text-sm font-medium">Medios que acepta</legend>
            <p className="text-xs text-muted-foreground">
              Sin ninguno tildado, la caja acepta todos.
            </p>
            <div className="flex flex-wrap gap-3 pt-1">
              {medios.map((m) => (
                <label key={m.valor} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={elegidos.includes(m.valor)}
                    onChange={(e) =>
                      setElegidos((prev) =>
                        e.target.checked
                          ? [...prev, m.valor]
                          : prev.filter((x) => x !== m.valor),
                      )
                    }
                  />
                  {m.etiqueta}
                </label>
              ))}
            </div>
          </fieldset>

          {caja && (
            <label className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={activo}
                onChange={(e) => setActivo(e.target.checked)}
              />
              Activa
            </label>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onCerrar}>Cancelar</Button>
          <Button
            disabled={enviando || !nombre.trim()}
            onClick={async () => {
              setEnviando(true)
              try {
                if (caja) {
                  await api.editar(caja.id, {
                    nombre: nombre.trim(), descripcion: descripcion.trim(),
                    medios_pago: elegidos, activo,
                  })
                } else {
                  await api.crear({
                    nombre: nombre.trim(), descripcion: descripcion.trim(),
                    medios_pago: elegidos, sucursal_id: sucursalId,
                  })
                }
                onGuardada()
              } catch (e) {
                onError((e as Error).message)
              } finally {
                setEnviando(false)
              }
            }}
          >
            {enviando ? 'Guardando…' : 'Guardar'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
