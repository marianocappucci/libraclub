import { useCallback, useEffect, useMemo, useState } from 'react'
import { clientes as api } from '@/lib/api'
import type { Cliente } from '@/lib/api'
import { useAuth } from '@/context/AuthContext'
import { FormularioDeCliente } from '@/components/FormularioDeCliente'

export function Clientes() {
  const { user } = useAuth()
  const [filas, setFilas] = useState<Cliente[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editando, setEditando] = useState<Cliente | null>(null)
  const [abierto, setAbierto] = useState(false)
  const [busca, setBusca] = useState('')
  const [verInactivos, setVerInactivos] = useState(false)

  // 🔑 Clientes es el ÚNICO maestro que un encargado puede escribir. El backend
  // lo gatea con `require_staff` y no con `require_admin`: si pidiera admin, no
  // se le podría tomar la reserva a alguien que llama por primera vez.
  const puedeEscribir = user?.role === 'admin' || user?.role === 'staff'

  const recargar = useCallback(() => {
    api.listar().then(setFilas).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(recargar, [recargar])

  const visibles = useMemo(() => {
    const texto = busca.trim().toLowerCase()
    return filas
      .filter((c) => verInactivos || c.activo)
      .filter(
        (c) =>
          !texto ||
          c.nombre.toLowerCase().includes(texto) ||
          (c.telefono ?? '').toLowerCase().includes(texto) ||
          (c.documento ?? '').toLowerCase().includes(texto),
      )
  }, [filas, busca, verInactivos])

  async function borrar(cliente: Cliente) {
    if (!confirm(`¿Borrar a ${cliente.nombre}? Si tiene reservas no se va a poder.`)) return
    setError(null)
    try {
      await api.borrar(cliente.id)
      recargar()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Clientes</h1>
        {puedeEscribir && (
          <button
            onClick={() => {
              setEditando(null)
              setAbierto(true)
            }}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white"
          >
            Nuevo cliente
          </button>
        )}
      </div>

      {/* Un buscador y no paginación: en un complejo la lista crece a miles y lo
          que el encargado hace es teclear el nombre o el teléfono que le están
          dictando por el mostrador. */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          className="w-72 rounded-md border border-slate-300 px-3 py-2 text-sm"
          placeholder="Buscar por nombre, teléfono o documento"
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          aria-label="Buscar cliente"
        />
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={verInactivos}
            onChange={(e) => setVerInactivos(e.target.checked)}
          />
          Ver los dados de baja
        </label>
        <span className="text-sm text-slate-400">
          {visibles.length} de {filas.length}
        </span>
      </div>

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
            <th className="px-3 py-2">Teléfono</th>
            <th className="px-3 py-2">Documento</th>
            <th className="px-3 py-2">CUIT</th>
            {puedeEscribir && <th className="px-3 py-2" />}
          </tr>
        </thead>
        <tbody>
          {visibles.map((c) => (
            <tr
              key={c.id}
              className={`border-t border-slate-100 ${c.activo ? '' : 'text-slate-400'}`}
            >
              <td className="px-3 py-2 font-medium">
                {c.nombre}
                {!c.activo && <span className="ml-2 text-xs">(de baja)</span>}
              </td>
              <td className="px-3 py-2">{c.telefono ?? '—'}</td>
              <td className="px-3 py-2">{c.documento ?? '—'}</td>
              <td className="px-3 py-2">{c.cuit ?? '—'}</td>
              {puedeEscribir && (
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <button
                    onClick={() => {
                      setEditando(c)
                      setAbierto(true)
                    }}
                    className="rounded-md border border-slate-300 px-2 py-1 hover:bg-slate-100"
                  >
                    Editar
                  </button>
                  <button
                    onClick={() => borrar(c)}
                    className="ml-2 rounded-md border border-red-300 px-2 py-1 text-red-800 hover:bg-red-50"
                  >
                    Borrar
                  </button>
                </td>
              )}
            </tr>
          ))}
          {visibles.length === 0 && (
            <tr>
              <td colSpan={5} className="px-3 py-4 text-slate-500">
                {/* Se distingue "no hay clientes" de "la búsqueda no encontró".
                    Un listado vacío sin explicación se lee como un error. */}
                {filas.length === 0
                  ? 'Todavía no hay clientes cargados.'
                  : 'Ningún cliente coincide con la búsqueda.'}
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <FormularioDeCliente
        abierto={abierto}
        cliente={editando}
        onCerrar={() => setAbierto(false)}
        onGuardado={() => {
          setAbierto(false)
          recargar()
        }}
      />
    </div>
  )
}
