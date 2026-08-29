import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { EncabezadoDePantalla } from 'libra-ui/acciones'
import { MapPin, Plus } from 'lucide-react'

import { sucursales as api } from '@/lib/api'
import type { Sucursal } from '@/lib/api'
import { useSucursal } from '@/context/SucursalContext'
import { useAuth } from '@/context/AuthContext'
import { FormularioDeSucursal } from '@/components/FormularioDeSucursal'
import { AvisoDeError, columnaDeAcciones, filaInactiva } from '@/components/listado'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

export function Sucursales() {
  // 🔴 Esta pantalla pide su **propia** lista, completa, y no usa la del
  // contexto. La del contexto está filtrada a las activas porque alimenta el
  // selector del menú — y con esa lista, una sucursal dada de baja desaparece
  // de acá y **no hay forma de volver a activarla**. Encontrado usándolo: se
  // dio de baja la que se estaba viendo y dejó de existir para la UI. El
  // `recargar` del contexto se sigue llamando, para que el selector se entere
  // de los cambios.
  const { actual, recargar: recargarSelector } = useSucursal()
  const { user } = useAuth()
  const [filas, setFilas] = useState<Sucursal[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editando, setEditando] = useState<Sucursal | null>(null)
  const [abierto, setAbierto] = useState(false)
  const [avisando, setAvisando] = useState(false)

  const puedeEscribir = user?.role === 'admin'

  const recargar = useCallback(() => {
    api.listar().then(setFilas).catch((e: Error) => setError(e.message))
    recargarSelector()
  }, [recargarSelector])

  useEffect(recargar, [recargar])

  const borrar = useCallback(
    async (sucursal: Sucursal) => {
      if (!confirm(`¿Borrar ${sucursal.nombre}? Si tiene canchas no se va a poder.`)) return
      setError(null)
      try {
        await api.borrar(sucursal.id)
        recargar()
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [recargar],
  )

  const columnas = useMemo<ColumnDef<Sucursal, unknown>[]>(() => {
    const base: ColumnDef<Sucursal, unknown>[] = [
      {
        accessorKey: 'nombre',
        header: sortableHeader('Nombre'),
        cell: ({ row }) => (
          <span className="font-medium">
            {row.original.nombre}
            {row.original.id === actual && (
              <span className="ml-2 text-xs text-muted-foreground">(la que estás viendo)</span>
            )}
            {!row.original.activa && (
              <span className="ml-2 text-xs text-muted-foreground">(de baja)</span>
            )}
          </span>
        ),
      },
      {
        accessorKey: 'localidad',
        header: sortableHeader('Localidad'),
        cell: ({ row }) => row.original.localidad ?? '—',
      },
      {
        accessorKey: 'telefono',
        header: 'Teléfono',
        cell: ({ row }) => row.original.telefono ?? '—',
      },
      {
        accessorKey: 'punto_venta_arca',
        header: 'Punto de venta',
        cell: ({ row }) =>
          row.original.punto_venta_arca ?? (
            // No es lo mismo "no tiene" que "tiene el 0": sin punto de venta la
            // sucursal no puede facturar, y conviene que se vea.
            <span className="text-amber-700 dark:text-amber-500">sin asignar</span>
          ),
      },
    ]
    if (!puedeEscribir) return base
    return [
      ...base,
      columnaDeAcciones<Sucursal>({
        onEditar: (s) => {
          setEditando(s)
          setAbierto(true)
        },
        onBorrar: borrar,
        nombreDe: (s) => s.nombre,
      }),
    ]
  }, [puedeEscribir, borrar, actual])

  // 🔑 **La pantalla se nombra por lo que hay.** Decidido con el humano el
  // 2026-08-28: la instancia comercial de un cliente es **un complejo**, así que
  // llamar «Sucursales» a una pantalla con una sola fila sugiere una estructura
  // que ese cliente no tiene — y encima invita a crear la segunda sin saber qué
  // implica. Con dos o más el plural es el correcto y vuelve solo.
  const unaSola = filas.length <= 1
  const titulo = unaSola ? 'Mi complejo' : 'Sucursales'

  return (
    <div className="space-y-3">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={MapPin}>{titulo}</TituloPantalla>}>
        {puedeEscribir && (
          <Button
            onClick={() => {
              setEditando(null)
              // 🔴 **La segunda pasa por el aviso; la primera no.** Sin una
              // sucursal la agenda no tiene dónde vivir, así que ahí crear es
              // obligatorio y frenarlo con un cartel sería estorbar. Es pasar de
              // una a dos lo que cambia el modelo mental, y es exactamente
              // donde alguien puede creer que está separando dos negocios.
              if (filas.length === 1) setAvisando(true)
              else setAbierto(true)
            }}
          >
            <Plus className="size-4" />
            {unaSola ? 'Agregar otra sucursal' : 'Nueva sucursal'}
          </Button>
        )}
      </EncabezadoDePantalla>

      <p className="text-sm text-muted-foreground">
        Una sucursal no es un cliente aparte: comparten base, usuarios y
        reportes. Un complejo que factura con otro CUIT va en otra instancia.
      </p>

      <Dialog open={avisando} onOpenChange={setAvisando}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Agregar una segunda sucursal</DialogTitle>
          </DialogHeader>
          {/* 🔴 **Dice las dos listas, no una.** Un aviso que sólo enumera
              riesgos se lee como «no lo hagas» y el operador lo saltea sin
              leerlo. Lo que hace falta es que entienda **qué separa y qué no**,
              porque las dos mitades son decisiones de negocio: dos complejos del
              mismo dueño y el mismo CUIT comparten personal y stock a propósito,
              y eso acá funciona. */}
          <div className="space-y-3 text-sm">
            <p>
              Las dos sucursales van a vivir en <strong>esta misma instancia</strong>.
            </p>
            <div>
              <p className="font-medium">Cada una tiene lo suyo:</p>
              <ul className="ml-4 list-disc text-muted-foreground">
                <li>sus canchas, sus horarios y sus tarifas</li>
                <li>su caja y su arqueo</li>
                <li><strong>su punto de venta de ARCA</strong>, que no se puede repetir</li>
              </ul>
            </div>
            <div>
              <p className="font-medium">Y esto se comparte:</p>
              <ul className="ml-4 list-disc text-muted-foreground">
                <li>los clientes y su cuenta corriente</li>
                <li>los usuarios del sistema y sus permisos</li>
                <li>el stock del buffet</li>
              </ul>
            </div>
            <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2">
              🔴 <strong>No hay aislamiento entre las dos.</strong> Si son de
              dueños distintos, o facturan con otro CUIT, va cada una en su
              propia instancia — no acá.
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setAvisando(false)}>
              Cancelar
            </Button>
            <Button
              onClick={() => {
                setAvisando(false)
                setAbierto(true)
              }}
            >
              Entendido, agregarla
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <AvisoDeError mensaje={error} />

      <DataTable
        columns={columnas}
        data={filas}
        getRowClassName={(s) => filaInactiva(s.activa)}
        emptyMessage="No hay ninguna sucursal. Sin una, la agenda no tiene dónde vivir."
        search={{
          campos: (s) => [s.nombre, s.localidad, s.telefono, s.punto_venta_arca],
          placeholder: 'Buscar por nombre, localidad o teléfono',
          ariaLabel: 'Buscar sucursal',
        }}
      />

      <FormularioDeSucursal
        abierto={abierto}
        sucursal={editando}
        onCerrar={() => setAbierto(false)}
        onGuardada={() => {
          setAbierto(false)
          recargar()
        }}
      />
    </div>
  )
}
