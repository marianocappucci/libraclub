import { useEffect, useMemo, useState } from 'react'
import { Modal } from '@/components/Modal'
import { agenda, clientes as apiClientes, ErrorDeApi } from '@/lib/api'
import type { Cancha, Cliente, Turno } from '@/lib/api'
import { fecha, hora, pesos } from '@/lib/fechas'

const ORIGENES = [
  { valor: 'mostrador', texto: 'Mostrador' },
  { valor: 'telefono', texto: 'Teléfono' },
  { valor: 'whatsapp', texto: 'WhatsApp' },
]

const ESTADOS = [
  { valor: 'confirmada', texto: 'Confirmada' },
  { valor: 'pendiente_pago', texto: 'Pendiente de pago' },
]

/** Cuántos turnos seguidos puede tomar una reserva desde la grilla. */
const MAX_TURNOS = 4

export function DialogoDeReserva({
  abierto,
  cancha,
  turno,
  onCerrar,
  onCreada,
}: {
  abierto: boolean
  cancha: Cancha | null
  turno: Turno | null
  onCerrar: () => void
  onCreada: () => void
}) {
  const [lista, setLista] = useState<Cliente[]>([])
  const [clienteId, setClienteId] = useState<string>('')
  const [nuevo, setNuevo] = useState(false)
  const [nombreNuevo, setNombreNuevo] = useState('')
  const [telefonoNuevo, setTelefonoNuevo] = useState('')
  const [turnos, setTurnos] = useState(1)
  const [origen, setOrigen] = useState('mostrador')
  const [estado, setEstado] = useState('confirmada')
  const [observaciones, setObservaciones] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    // Se resetea al abrir y no al cerrar: si quedaran los valores de la reserva
    // anterior, el operador que abre otro turno vería un cliente ya elegido y
    // podría confirmarlo sin mirar.
    setError(null)
    setTurnos(1)
    setNuevo(false)
    setNombreNuevo('')
    setTelefonoNuevo('')
    setObservaciones('')
    setOrigen('mostrador')
    setEstado('confirmada')
    apiClientes
      .listar()
      .then((filas) => {
        const activos = filas.filter((c) => (c as Cliente & { activo?: boolean }).activo !== false)
        setLista(activos)
        setClienteId(activos[0] ? String(activos[0].id) : '')
        // Sin clientes cargados, la única salida es dar uno de alta. Se abre ya
        // en ese modo en vez de mostrar un select vacío que no explica nada.
        if (activos.length === 0) setNuevo(true)
      })
      .catch((e: Error) => setError(e.message))
  }, [abierto])

  const minutos = (cancha?.duracion_turno_min ?? 90) * turnos

  /**
   * El precio que se va a cobrar, calculado **a la vista del operador**.
   *
   * La tarifa es por turno estándar y el backend no prorratea: para un turno la
   * resuelve él y no se manda nada. Para varios turnos seguidos se manda el
   * precio explícito —N × la tarifa del inicio— porque el backend, librado a sí
   * mismo, cobraría **un solo turno** por una reserva de tres horas. Multiplicar
   * en silencio del lado del servidor sería inventar una regla de negocio; acá
   * el número está en pantalla y alguien lo confirma.
   */
  const total = useMemo(() => {
    if (!turno?.precio) return null
    const unitario = Number(turno.precio)
    if (Number.isNaN(unitario)) return null
    return (unitario * turnos).toFixed(2)
  }, [turno, turnos])

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    if (!cancha || !turno) return
    setEnviando(true)
    setError(null)
    try {
      let id = Number(clienteId)
      if (nuevo) {
        if (!nombreNuevo.trim()) throw new Error('El cliente nuevo necesita un nombre.')
        const creado = await apiClientes.crear({
          nombre: nombreNuevo.trim(),
          telefono: telefonoNuevo.trim() || null,
        })
        id = creado.id
      }
      if (!id) throw new Error('Elegí un cliente o cargá uno nuevo.')

      await agenda.reservar({
        cancha_id: cancha.id,
        cliente_id: id,
        // Tal cual vino de la grilla, con su offset. Ver el comentario en `api.ts`.
        comienza_at: turno.comienza_at,
        duracion_min: minutos,
        estado,
        origen,
        // Sólo cuando son varios turnos. Con uno solo manda `undefined` y decide
        // el tarifario, que además es el único camino que calcula la seña.
        ...(turnos > 1 && total ? { precio: total } : {}),
        observaciones: observaciones.trim() || null,
      })
      onCreada()
    } catch (err) {
      const e = err as ErrorDeApi
      // 409 y 422 son los dos que el operador va a ver de verdad, y los dos
      // tienen arreglo del lado de él: alguien se le adelantó, o falta cargar la
      // tarifa de esa franja. El mensaje del backend ya lo dice; lo que se suma
      // acá es qué hacer.
      setError(
        e.status === 409
          ? `${e.message} Cerrá y recargá la grilla para ver cómo quedó.`
          : e.status === 422
            ? `${e.message} Cargala en Tarifas y volvé a intentar.`
            : e.message,
      )
    } finally {
      setEnviando(false)
    }
  }

  if (!cancha || !turno) return null

  return (
    <Modal abierto={abierto} titulo="Nueva reserva" onCerrar={onCerrar}>
      <form onSubmit={enviar} className="space-y-4">
        <div className="rounded-md bg-slate-100 px-3 py-2 text-sm">
          <div className="font-medium">{cancha.nombre}</div>
          <div className="text-slate-600">
            {fecha(turno.comienza_at)} · desde las {hora(turno.comienza_at)}
            {' · '}
            {minutos} min
          </div>
          <div className={total ? 'text-slate-900' : 'text-amber-700'}>
            {total ? (
              <>
                {pesos(total)}
                {turnos > 1 && (
                  // Un solo nodo de texto a propósito: partido en varios, la
                  // cuenta queda ilegible para un lector de pantalla y para
                  // cualquier test que la busque como frase.
                  <span className="text-slate-500">{` (${turnos} × ${pesos(turno.precio)})`}</span>
                )}
              </>
            ) : (
              'Sin tarifa cargada para esta franja'
            )}
          </div>
        </div>

        {!nuevo ? (
          <div className="space-y-1">
            {/* El botón va FUERA del `<label>`: adentro, su texto entra en el
                nombre accesible del select y el lector de pantalla anuncia
                "Cliente … Cliente nuevo" como si fuera una sola cosa. */}
            <label className="block space-y-1">
              <span className="text-sm text-slate-600">Cliente</span>
              <select
                className="w-full rounded-md border border-slate-300 px-3 py-2"
                value={clienteId}
                onChange={(e) => setClienteId(e.target.value)}
              >
                {lista.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nombre}
                    {c.telefono ? ` — ${c.telefono}` : ''}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="text-sm text-slate-600 underline"
              onClick={() => setNuevo(true)}
            >
              Cliente nuevo
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <label className="block space-y-1">
              <span className="text-sm text-slate-600">Nombre del cliente</span>
              <input
                className="w-full rounded-md border border-slate-300 px-3 py-2"
                value={nombreNuevo}
                onChange={(e) => setNombreNuevo(e.target.value)}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-sm text-slate-600">Teléfono</span>
              <input
                className="w-full rounded-md border border-slate-300 px-3 py-2"
                value={telefonoNuevo}
                onChange={(e) => setTelefonoNuevo(e.target.value)}
              />
            </label>
            {lista.length > 0 && (
              <button
                type="button"
                className="text-sm text-slate-600 underline"
                onClick={() => setNuevo(false)}
              >
                Elegir uno existente
              </button>
            )}
          </div>
        )}

        <div className="grid grid-cols-3 gap-2">
          <label className="space-y-1">
            <span className="text-sm text-slate-600">Turnos</span>
            <select
              className="w-full rounded-md border border-slate-300 px-2 py-2"
              value={turnos}
              onChange={(e) => setTurnos(Number(e.target.value))}
            >
              {Array.from({ length: MAX_TURNOS }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-sm text-slate-600">Origen</span>
            <select
              className="w-full rounded-md border border-slate-300 px-2 py-2"
              value={origen}
              onChange={(e) => setOrigen(e.target.value)}
            >
              {ORIGENES.map((o) => (
                <option key={o.valor} value={o.valor}>
                  {o.texto}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-sm text-slate-600">Estado</span>
            <select
              className="w-full rounded-md border border-slate-300 px-2 py-2"
              value={estado}
              onChange={(e) => setEstado(e.target.value)}
            >
              {ESTADOS.map((o) => (
                <option key={o.valor} value={o.valor}>
                  {o.texto}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="block space-y-1">
          <span className="text-sm text-slate-600">Observaciones</span>
          <input
            className="w-full rounded-md border border-slate-300 px-3 py-2"
            value={observaciones}
            onChange={(e) => setObservaciones(e.target.value)}
          />
        </label>

        {error && (
          <p
            role="alert"
            className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
          >
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCerrar}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-100"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={enviando}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {enviando ? 'Reservando…' : 'Reservar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
