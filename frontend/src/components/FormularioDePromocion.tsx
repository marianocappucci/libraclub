import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { promociones as api } from '@/lib/api'
import type { Cancha, Promocion, PromocionEntrada } from '@/lib/api'
import { Input } from '@/components/ui/input'
import { buttonVariants } from '@/components/ui/button'
import { SelectBuscable } from '@/components/select-buscable'
import { AvisoDeError } from '@/components/listado'

/** Lunes primero, como el backend (0 = lunes … 6 = domingo). */
export const DIAS_CORTOS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']

function vacia(sucursalId: number): PromocionEntrada {
  return {
    sucursal_id: sucursalId,
    cancha_id: null,
    nombre: '',
    descuento_porcentaje: 20,
    dias_semana: null,
    hora_desde: '14:00',
    hora_hasta: '17:00',
    vigente_desde: null,
    vigente_hasta: null,
    aplica_en_feriados: false,
    activa: true,
  }
}

export function FormularioDePromocion({
  abierto,
  promocion,
  canchas,
  sucursalId,
  onCerrar,
  onGuardada,
}: {
  abierto: boolean
  /** `null` = alta. */
  promocion: Promocion | null
  canchas: Cancha[]
  sucursalId: number
  onCerrar: () => void
  onGuardada: () => void
}) {
  const [datos, setDatos] = useState<PromocionEntrada>(() => vacia(sucursalId))
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    setDatos(
      promocion
        ? {
            sucursal_id: promocion.sucursal_id,
            cancha_id: promocion.cancha_id,
            nombre: promocion.nombre,
            descuento_porcentaje: promocion.descuento_porcentaje,
            dias_semana: promocion.dias_semana,
            // `HH:MM:SS` del backend; un `<input type="time">` sólo acepta `HH:MM`.
            hora_desde: promocion.hora_desde.slice(0, 5),
            hora_hasta: promocion.hora_hasta.slice(0, 5),
            vigente_desde: promocion.vigente_desde,
            vigente_hasta: promocion.vigente_hasta,
            aplica_en_feriados: promocion.aplica_en_feriados,
            activa: promocion.activa,
          }
        : vacia(sucursalId),
    )
  }, [abierto, promocion, sucursalId])

  function set<K extends keyof PromocionEntrada>(campo: K, valor: PromocionEntrada[K]) {
    setDatos((d) => ({ ...d, [campo]: valor }))
  }

  /** Marca o desmarca un día. **Ninguno marcado = todos los días** (`null`), nunca una lista
   *  vacía: el backend la rechaza porque sería «no aplica ningún día». */
  function alternarDia(dia: number) {
    setDatos((d) => {
      const actuales = new Set(d.dias_semana ?? [])
      if (actuales.has(dia)) actuales.delete(dia)
      else actuales.add(dia)
      return { ...d, dias_semana: actuales.size ? [...actuales].sort((a, b) => a - b) : null }
    })
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      if (!datos.nombre.trim()) throw new Error('La promoción necesita un nombre.')
      if (!Number.isInteger(datos.descuento_porcentaje)
        || datos.descuento_porcentaje < 1 || datos.descuento_porcentaje > 99)
        throw new Error('El descuento va de 1 a 99%.')
      if (datos.hora_hasta <= datos.hora_desde)
        throw new Error('La franja tiene que terminar después de empezar.')
      if (datos.vigente_desde && datos.vigente_hasta && datos.vigente_hasta < datos.vigente_desde)
        throw new Error('La vigencia tiene que terminar después de empezar.')

      const cuerpo: PromocionEntrada = { ...datos, nombre: datos.nombre.trim() }
      if (promocion) await api.editar(promocion.id, cuerpo)
      else await api.crear(cuerpo)
      onGuardada()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Dialog open={abierto} onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {promocion ? `Editar ${promocion.nombre}` : 'Nueva promoción'}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={enviar} noValidate className="space-y-3">
          <div className="grid grid-cols-[1fr_7rem] gap-2">
            <label className="space-y-1">
              <span className="text-sm font-medium">Nombre</span>
              <Input
                placeholder="Hora valle"
                value={datos.nombre}
                onChange={(e) => set('nombre', e.target.value)}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm font-medium">Descuento %</span>
              <Input
                type="number"
                min={1}
                max={99}
                value={datos.descuento_porcentaje}
                onChange={(e) => set('descuento_porcentaje', Number(e.target.value))}
              />
            </label>
          </div>

          <div className="block space-y-1">
            <label htmlFor="promocion-cancha" className="block text-sm font-medium">Cancha</label>
            <SelectBuscable
              id="promocion-cancha"
              value={datos.cancha_id === null ? '' : String(datos.cancha_id)}
              onChange={(v) => set('cancha_id', v ? Number(v) : null)}
              opciones={[
                { value: '', label: 'Toda la sucursal' },
                ...canchas.map((c) => ({ value: String(c.id), label: c.nombre })),
              ]}
              placeholder="Buscar cancha…"
            />
          </div>

          <fieldset className="space-y-1">
            <legend className="text-sm font-medium">Días</legend>
            <div className="flex flex-wrap gap-1.5">
              {DIAS_CORTOS.map((nombre, i) => {
                const marcado = datos.dias_semana?.includes(i) ?? false
                return (
                  <label
                    key={nombre}
                    className={`cursor-pointer rounded-md border px-2.5 py-1 text-sm ${
                      marcado ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={marcado}
                      onChange={() => alternarDia(i)}
                    />
                    {nombre}
                  </label>
                )
              })}
            </div>
            <p className="text-xs text-muted-foreground">
              {datos.dias_semana === null
                ? 'Sin elegir ninguno, aplica todos los días.'
                : 'Sólo los días marcados.'}
            </p>
          </fieldset>

          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="text-sm font-medium">Desde la hora</span>
              <Input
                type="time"
                value={datos.hora_desde}
                onChange={(e) => set('hora_desde', e.target.value)}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm font-medium">Hasta la hora</span>
              <Input
                type="time"
                value={datos.hora_hasta}
                onChange={(e) => set('hora_hasta', e.target.value)}
              />
            </label>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="text-sm font-medium">Vigente desde</span>
              <Input
                type="date"
                value={datos.vigente_desde ?? ''}
                onChange={(e) => set('vigente_desde', e.target.value || null)}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm font-medium">Vigente hasta</span>
              <Input
                type="date"
                value={datos.vigente_hasta ?? ''}
                onChange={(e) => set('vigente_hasta', e.target.value || null)}
              />
            </label>
          </div>
          <p className="-mt-1 text-xs text-muted-foreground">
            Sin fechas, rige siempre. Los dos días extremos incluidos.
          </p>

          <p className="text-xs text-muted-foreground">
            Se descuenta de la tarifa que corresponda a cada turno y la seña se calcula sobre
            el precio ya rebajado. Si varias promociones coinciden, gana la que más descuenta;
            no se suman.
          </p>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={datos.aplica_en_feriados}
              onChange={(e) => set('aplica_en_feriados', e.target.checked)}
            />
            También en feriados
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={datos.activa}
              onChange={(e) => set('activa', e.target.checked)}
            />
            Activa
          </label>

          <AvisoDeError mensaje={error} />

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onCerrar}
              className={buttonVariants({ variant: 'outline' })}
            >
              Cancelar
            </button>
            <button type="submit" disabled={enviando} className={buttonVariants()}>
              {enviando ? 'Guardando…' : 'Guardar'}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
