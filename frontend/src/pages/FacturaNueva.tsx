/** Emitir una factura que no sale de un turno.
 *
 * El caso real: una clase particular, un alquiler de equipamiento, una cuota de
 * escuelita. La factura de una reserva se emite desde la Agenda y lleva el
 * alquiler y el consumo de buffet adentro — ver `servicios/facturacion.py`.
 *
 * 🔴 **NUNCA se manda `client_id`, y no es un olvido.** El motor lo resolvería
 * contra la tabla `clients` **de la base de LibraCore**, y los clientes de este
 * producto viven en la base del dominio: son dos tablas distintas con ids que se
 * pisan. Este producto además crea filas en la de LibraCore por cuenta
 * corriente, así que la colisión no es teórica.
 *
 * Mandar el id emitiría la factura **a nombre de otra persona**, y no fallaría:
 * saldría un comprobante fiscal correcto dirigido a quien no era. Por eso el
 * selector copia **nombre y CUIT** al formulario y el `client_id` no se toca. Hay
 * un test que lo fija.
 *
 * No hay buscador de productos como en Contalibra: este producto no tiene
 * catálogo para facturar —el del buffet es otra cosa, y se cobra por el turno—,
 * así que los ítems se escriben a mano.
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Receipt, Trash2 } from 'lucide-react'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { EncabezadoDePantalla } from 'libra-ui/acciones'

import { clientes as apiClientes, facturas as apiFacturas } from '@/lib/api'
import type { Cliente } from '@/lib/api'
import { pesos } from '@/lib/fechas'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Item = { description: string; qty: string; unit_price: string }

const ITEM_VACIO: Item = { description: '', qty: '1', unit_price: '' }

/** Hoy, en `aaaa-mm-dd`, sin pasar por UTC.
 *
 * 🔑 `new Date().toISOString()` da el día de UTC: después de las 21:00 en
 * Argentina eso es **mañana**, y la factura saldría con la fecha del día
 * siguiente. Un comprobante fiscal con la fecha corrida no se corrige editando.
 */
function hoyLocal(): string {
  const d = new Date()
  const mes = String(d.getMonth() + 1).padStart(2, '0')
  const dia = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mes}-${dia}`
}

export function FacturaNueva() {
  const navegar = useNavigate()
  const [tipos, setTipos] = useState<{ value: number; label: string }[]>([])
  const [condiciones, setCondiciones] = useState<string[]>([])
  const [puntoVenta, setPuntoVenta] = useState(1)
  const [listaDeClientes, setListaDeClientes] = useState<Cliente[]>([])

  const [tipo, setTipo] = useState<string>('')
  const [fecha, setFecha] = useState(hoyLocal())
  const [condicion, setCondicion] = useState('Contado')
  const [nombre, setNombre] = useState('')
  const [cuit, setCuit] = useState('')
  const [observaciones, setObservaciones] = useState('')
  const [items, setItems] = useState<Item[]>([{ ...ITEM_VACIO }])

  const [emitiendo, setEmitiendo] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiFacturas
      .tipos()
      .then((d) => {
        setTipos(d.tipos)
        setCondiciones(d.condiciones_venta)
        setPuntoVenta(d.punto_venta)
        // El tipo lo decide la condición de IVA del emisor: un monotributista
        // emite C y nada más. Se elige el primero que el backend ofrece en vez
        // de hardcodear uno.
        if (d.tipos.length > 0) setTipo(String(d.tipos[0].value))
      })
      .catch((e: Error) => setError(e.message))

    // Los clientes son de ESTE producto, no de LibraCore. Sólo se usan para
    // copiar nombre y CUIT — ver la nota de arriba.
    apiClientes.listar().then((cs) => setListaDeClientes(cs.filter((c) => c.activo))).catch(() => {})
  }, [])

  const total = useMemo(
    () => items.reduce((suma, i) => suma + (Number(i.qty) || 0) * (Number(i.unit_price) || 0), 0),
    [items],
  )

  function cambiarItem(indice: number, campo: keyof Item, valor: string) {
    setItems((filas) => filas.map((f, i) => (i === indice ? { ...f, [campo]: valor } : f)))
  }

  function elegirCliente(id: string) {
    const c = listaDeClientes.find((x) => String(x.id) === id)
    if (!c) return
    // Se copian los datos, NO el id.
    setNombre(c.nombre)
    setCuit(c.cuit ?? '')
  }

  function cuerpo() {
    return {
      tipo: Number(tipo),
      punto_venta: puntoVenta,
      fecha,
      condicion_venta: condicion,
      client_name: nombre.trim(),
      client_cuit: cuit.trim(),
      observations: observaciones.trim(),
      items: items
        .filter((i) => i.description.trim())
        .map((i) => ({
          description: i.description.trim(),
          qty: Number(i.qty) || 0,
          unit_price: Number(i.unit_price) || 0,
        })),
    }
  }

  async function emitir() {
    setError(null)
    if (!nombre.trim()) {
      setError('Poné a nombre de quién se emite.')
      return
    }
    if (cuerpo().items.length === 0) {
      setError('Agregá al menos un ítem con descripción.')
      return
    }
    setEmitiendo(true)
    try {
      const factura = await apiFacturas.crear(cuerpo())
      navegar(`/facturas/${factura.id}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setEmitiendo(false)
    }
  }

  return (
    <div className="grid gap-4">
      <EncabezadoDePantalla titulo={<TituloPantalla icono={Receipt}>Nueva factura</TituloPantalla>}>
        {/* El borrador abre en una pestaña: es para mirar el comprobante ANTES
            de quemarle un número a la numeración fiscal, que no se devuelve. */}
        <Button
          variant="outline"
          onClick={async () => {
            const r = await fetch('/api/facturas/borrador-pdf', {
              method: 'POST',
              credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(cuerpo()),
            })
            if (!r.ok) {
              setError('No se pudo generar el borrador.')
              return
            }
            window.open(URL.createObjectURL(await r.blob()), '_blank')
          }}
        >
          Ver borrador
        </Button>
        <Button disabled={emitiendo} onClick={emitir}>
          {emitiendo ? 'Emitiendo…' : 'Emitir'}
        </Button>
      </EncabezadoDePantalla>

      <AvisoDeError mensaje={error} />

      <Card>
        <CardContent className="grid gap-4 py-4">
          <div className="flex flex-wrap gap-4">
            <div className="grid gap-2">
              <Label>Tipo</Label>
              <select
                className="h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs w-48"
                aria-label="Tipo de comprobante"
                value={tipo}
                onChange={(e) => setTipo(e.target.value)}
              >
                {tipos.map((t) => (
                  <option key={t.value} value={String(t.value)}>{t.label}</option>
                ))}
              </select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="fecha">Fecha</Label>
              {/* `type="date"` maneja ISO; el `dd-mm-aaaa` es de la presentación. */}
              <Input id="fecha" type="date" className="w-44" value={fecha} onChange={(e) => setFecha(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label>Condición de venta</Label>
              <select
                className="h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs w-52"
                aria-label="Condición de venta"
                value={condicion}
                onChange={(e) => setCondicion(e.target.value)}
              >
                {condiciones.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>

          <div className="flex flex-wrap gap-4">
            <div className="grid gap-2">
              <Label>Cliente del complejo</Label>
              <select
                className="h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs w-64"
                aria-label="Elegir un cliente del complejo"
                defaultValue=""
                onChange={(e) => elegirCliente(e.target.value)}
              >
                <option value="">Copiar datos de…</option>
                {listaDeClientes.map((c) => (
                  <option key={c.id} value={String(c.id)}>{c.nombre}</option>
                ))}
              </select>
            </div>
            <div className="grid flex-1 gap-2">
              <Label htmlFor="nombre">Se emite a nombre de</Label>
              <Input id="nombre" value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Consumidor Final" />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="cuit">CUIT / DNI</Label>
              <Input id="cuit" className="w-44" value={cuit} onChange={(e) => setCuit(e.target.value)} />
            </div>
          </div>

          <div className="grid gap-2">
            <Label>Ítems</Label>
            {items.map((item, i) => (
              <div key={i} className="flex flex-wrap items-end gap-2">
                <Input
                  className="min-w-48 flex-1"
                  aria-label={`Descripción del ítem ${i + 1}`}
                  value={item.description}
                  onChange={(e) => cambiarItem(i, 'description', e.target.value)}
                />
                <Input
                  className="w-24" type="number" min="0" step="0.01"
                  aria-label={`Cantidad del ítem ${i + 1}`}
                  value={item.qty}
                  onChange={(e) => cambiarItem(i, 'qty', e.target.value)}
                />
                <Input
                  className="w-36" type="number" min="0" step="0.01"
                  aria-label={`Precio unitario del ítem ${i + 1}`}
                  value={item.unit_price}
                  onChange={(e) => cambiarItem(i, 'unit_price', e.target.value)}
                />
                {items.length > 1 && (
                  <Button
                    variant="ghost" size="icon"
                    aria-label={`Quitar el ítem ${i + 1}`}
                    onClick={() => setItems((f) => f.filter((_, j) => j !== i))}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                )}
              </div>
            ))}
            <div className="flex items-center justify-between">
              <Button variant="outline" size="sm" onClick={() => setItems((f) => [...f, { ...ITEM_VACIO }])}>
                <Plus className="size-4" />Agregar ítem
              </Button>
              <span className="text-sm">
                Total: <strong className="tabular-nums">{pesos(total)}</strong>
              </span>
            </div>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="obs">Observaciones</Label>
            <Input id="obs" value={observaciones} onChange={(e) => setObservaciones(e.target.value)} />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
