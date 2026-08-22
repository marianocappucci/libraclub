import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

import { FORMATOS, torneos as api } from '@/lib/api'
import type { FormatoTorneo, Torneo, TorneoEntrada } from '@/lib/api'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { diaISO } from '@/lib/fechas'

const DEPORTES = ['padel', 'tenis', 'futbol', 'basquet', 'voley', 'hockey', 'otro']

/** Cuántos parciales hay que ganar, por deporte.
 *
 * 🔑 Es un **default de carga**, no una regla: el campo queda editable. Un
 * fútbol se juega a un resultado y un pádel al mejor de tres, que es lo que
 * elige el 95 % de las veces, pero un torneo relámpago de pádel a un set existe
 * y no hay por qué prohibirlo.
 */
const SETS_POR_DEPORTE: Record<string, number> = {
  padel: 2, tenis: 2, futbol: 1, basquet: 1, voley: 2, hockey: 1, otro: 1,
}

function vacio(sucursalId: number): TorneoEntrada {
  return {
    sucursal_id: sucursalId,
    nombre: '',
    deporte: 'padel',
    formato: 'eliminacion',
    desde: diaISO(new Date()),
    hasta: null,
    sets_para_ganar: 2,
    cantidad_zonas: null,
    clasifican_por_zona: null,
    observaciones: null,
  }
}

/** Alta de un torneo.
 *
 * 🔴 **El formato se elige acá y no se puede cambiar después.** Cambiarlo con
 * el torneo sorteado no es editar un campo: es tirar el fixture, y con él los
 * partidos jugados. Por eso el formulario lo explica antes y no después.
 */
export function FormularioDeTorneo({
  abierto,
  sucursalId,
  onCerrar,
  onCreado,
}: {
  abierto: boolean
  sucursalId: number
  onCerrar: () => void
  onCreado: (torneo: Torneo) => void
}) {
  const [datos, setDatos] = useState<TorneoEntrada>(() => vacio(sucursalId))
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    setDatos(vacio(sucursalId))
  }, [abierto, sucursalId])

  function set<K extends keyof TorneoEntrada>(campo: K, valor: TorneoEntrada[K]) {
    setDatos((d) => ({ ...d, [campo]: valor }))
  }

  function elegirFormato(formato: FormatoTorneo) {
    // 🔴 Los parámetros de zona **se limpian** al salir del formato que los usa:
    // el backend rechaza un torneo de eliminación que los traiga —y con razón,
    // son números que no significarían nada—, pero si quedaran pegados del
    // click anterior el operador vería un 422 sin entender qué mandó.
    setDatos((d) => ({
      ...d,
      formato,
      cantidad_zonas: formato === 'zonas' ? (d.cantidad_zonas ?? 2) : null,
      clasifican_por_zona: formato === 'zonas' ? (d.clasifican_por_zona ?? 2) : null,
    }))
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setEnviando(true)
    try {
      onCreado(await api.crear(datos))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  if (!abierto) return null

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onCerrar() }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Nuevo torneo</DialogTitle>
        </DialogHeader>

        <form onSubmit={enviar} className="space-y-3 text-sm">
          <label className="block space-y-1">
            <span className="font-medium">Nombre</span>
            <Input
              autoFocus
              value={datos.nombre}
              onChange={(e) => set('nombre', e.target.value)}
              placeholder="Apertura de pádel 2026"
            />
          </label>

          <label className="block space-y-1">
            <span className="font-medium">Deporte</span>
            <select
              className="h-9 w-full rounded-md border bg-transparent px-3"
              value={datos.deporte}
              onChange={(e) => {
                set('deporte', e.target.value)
                set('sets_para_ganar', SETS_POR_DEPORTE[e.target.value] ?? 1)
              }}
            >
              {DEPORTES.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </label>

          <fieldset className="space-y-1">
            <legend className="font-medium">Formato</legend>
            <p className="text-xs text-muted-foreground">
              No se puede cambiar después de crear el torneo: el fixture se arma
              con esto.
            </p>
            <div className="space-y-2 pt-1">
              {FORMATOS.map((f) => (
                <label
                  key={f.valor}
                  className="flex cursor-pointer items-start gap-2 rounded-md border bg-card p-2"
                >
                  <input
                    type="radio"
                    name="formato"
                    className="mt-1"
                    checked={datos.formato === f.valor}
                    onChange={() => elegirFormato(f.valor)}
                  />
                  <span>
                    <span className="block font-medium">{f.nombre}</span>
                    <span className="block text-xs text-muted-foreground">{f.ayuda}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          {datos.formato === 'zonas' && (
            <div className="grid grid-cols-2 gap-2">
              <label className="block space-y-1">
                <span className="font-medium">Zonas</span>
                <Input
                  type="number"
                  min={2}
                  value={datos.cantidad_zonas ?? 2}
                  onChange={(e) => set('cantidad_zonas', Number(e.target.value))}
                />
              </label>
              <label className="block space-y-1">
                <span className="font-medium">Clasifican</span>
                <select
                  className="h-9 w-full rounded-md border bg-transparent px-3"
                  value={datos.clasifican_por_zona ?? 2}
                  onChange={(e) => set('clasifican_por_zona', Number(e.target.value))}
                >
                  {/* Sólo 1 o 2: con tres o más, la regla que evita que dos de
                      la misma zona se crucen en el playoff deja de ser una
                      rotación y depende del reglamento. Ver
                      `fixture.orden_de_clasificados`. */}
                  <option value={1}>Sólo el primero</option>
                  <option value={2}>Los dos primeros</option>
                </select>
              </label>
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <label className="block space-y-1">
              <span className="font-medium">Desde</span>
              <Input
                type="date"
                value={datos.desde}
                onChange={(e) => set('desde', e.target.value)}
              />
            </label>
            <label className="block space-y-1">
              <span className="font-medium">
                Hasta <span className="text-muted-foreground">(opcional)</span>
              </span>
              <Input
                type="date"
                value={datos.hasta ?? ''}
                onChange={(e) => set('hasta', e.target.value || null)}
              />
            </label>
          </div>

          <label className="block space-y-1">
            <span className="font-medium">Parciales para ganar un partido</span>
            <Input
              type="number"
              min={1}
              max={5}
              value={datos.sets_para_ganar}
              onChange={(e) => set('sets_para_ganar', Number(e.target.value))}
            />
            <span className="text-xs text-muted-foreground">
              {datos.sets_para_ganar === 1
                ? 'Un solo resultado por partido, como en fútbol. El empate vale en la fase de grupos.'
                : `Al mejor de ${datos.sets_para_ganar * 2 - 1} sets.`}
            </span>
          </label>

          <AvisoDeError mensaje={error} />

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onCerrar}>
              Cancelar
            </Button>
            <Button type="submit" disabled={enviando || !datos.nombre.trim()}>
              {enviando ? 'Creando…' : 'Crear torneo'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
