import { useCallback, useEffect, useState } from 'react'
import { sucursales as api } from '@/lib/api'
import type { Sucursal } from '@/lib/api'
import { useSucursal } from '@/context/SucursalContext'
import { useAuth } from '@/context/AuthContext'
import { FormularioDeSucursal } from '@/components/FormularioDeSucursal'

export function Sucursales() {
  // 🔴 Esta pantalla pide su **propia** lista, completa, y no usa la del
  // contexto. La del contexto está filtrada a las activas porque alimenta el
  // selector del encabezado — y con esa lista, una sucursal dada de baja
  // desaparece de acá y **no hay forma de volver a activarla**. Encontrado
  // usándolo: se dio de baja la que se estaba viendo y dejó de existir para la
  // UI. El `recargar` del contexto se sigue llamando, para que el selector se
  // entere de los cambios.
  const { actual, recargar: recargarSelector } = useSucursal()
  const { user } = useAuth()
  const [filas, setFilas] = useState<Sucursal[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editando, setEditando] = useState<Sucursal | null>(null)
  const [abierto, setAbierto] = useState(false)

  const puedeEscribir = user?.role === 'admin'

  const recargar = useCallback(() => {
    api.listar().then(setFilas).catch((e: Error) => setError(e.message))
    recargarSelector()
  }, [recargarSelector])

  useEffect(recargar, [recargar])

  async function borrar(sucursal: Sucursal) {
    if (!confirm(`¿Borrar ${sucursal.nombre}? Si tiene canchas no se va a poder.`)) return
    setError(null)
    try {
      await api.borrar(sucursal.id)
      recargar()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Sucursales</h1>
        {puedeEscribir && (
          <button
            onClick={() => {
              setEditando(null)
              setAbierto(true)
            }}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white"
          >
            Nueva sucursal
          </button>
        )}
      </div>

      <p className="text-sm text-slate-500">
        Una sucursal no es un cliente aparte: comparten base, usuarios y
        reportes. Un complejo que factura con otro CUIT va en otra instancia.
      </p>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          {error}
        </p>
      )}

      <table className="w-full overflow-hidden rounded-lg border border-slate-200 bg-white text-sm">
        <thead className="bg-slate-100 text-left text-slate-600">
          <tr>
            <th className="px-3 py-2">Nombre</th>
            <th className="px-3 py-2">Localidad</th>
            <th className="px-3 py-2">Teléfono</th>
            <th className="px-3 py-2">Punto de venta</th>
            {puedeEscribir && <th className="px-3 py-2" />}
          </tr>
        </thead>
        <tbody>
          {filas.map((s) => (
            <tr
              key={s.id}
              className={`border-t border-slate-100 ${s.activa ? '' : 'text-slate-400'}`}
            >
              <td className="px-3 py-2 font-medium">
                {s.nombre}
                {s.id === actual && (
                  <span className="ml-2 text-xs text-slate-500">(la que estás viendo)</span>
                )}
                {!s.activa && <span className="ml-2 text-xs">(de baja)</span>}
              </td>
              <td className="px-3 py-2">{s.localidad ?? '—'}</td>
              <td className="px-3 py-2">{s.telefono ?? '—'}</td>
              <td className="px-3 py-2">
                {s.punto_venta_arca ?? (
                  // No es lo mismo "no tiene" que "tiene el 0": sin punto de
                  // venta la sucursal no puede facturar, y conviene que se vea.
                  <span className="text-amber-700">sin asignar</span>
                )}
              </td>
              {puedeEscribir && (
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <button
                    onClick={() => {
                      setEditando(s)
                      setAbierto(true)
                    }}
                    className="rounded-md border border-slate-300 px-2 py-1 hover:bg-slate-100"
                  >
                    Editar
                  </button>
                  <button
                    onClick={() => borrar(s)}
                    className="ml-2 rounded-md border border-red-300 px-2 py-1 text-red-800 hover:bg-red-50"
                  >
                    Borrar
                  </button>
                </td>
              )}
            </tr>
          ))}
          {filas.length === 0 && (
            <tr>
              <td colSpan={5} className="px-3 py-4 text-slate-500">
                No hay ninguna sucursal. Sin una, la agenda no tiene dónde vivir.
              </td>
            </tr>
          )}
        </tbody>
      </table>

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
