import { useEffect, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

import { FORMATOS, torneos as api } from '@/lib/api'
import type { Evento, FormatoTorneo, Torneo, TorneoEntrada } from '@/lib/api'
import { AvisoDeError } from '@/components/listado'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { DEPORTES_DE_SETS, MODALIDADES_DE_PARTIDO } from '@/components/torneo'
import { diaISO, fecha } from '@/lib/fechas'

/** Las categorías que se piden más seguido, como sugerencia. El campo es de texto
 *  libre: cada club arma las suyas («Caballeros 5ta», «Damas A», «Mixto»). */
const CATEGORIAS_SUGERIDAS = [
  'Caballeros 3ra', 'Caballeros 4ta', 'Caballeros 5ta', 'Caballeros 6ta',
  'Caballeros 7ma', 'Caballeros 8va', 'Damas 4ta', 'Damas 5ta', 'Damas 6ta',
  'Damas 7ma', 'Mixto',
]

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

function vacio(sucursalId: number, evento?: Evento | null): TorneoEntrada {
  return {
    sucursal_id: evento?.sucursal_id ?? sucursalId,
    nombre: '',
    deporte: 'padel',
    formato: 'eliminacion',
    // Las fechas de una categoría las pone el evento.
    desde: evento?.desde ?? diaISO(new Date()),
    hasta: evento ? evento.hasta : null,
    sets_para_ganar: 2,
    // Pádel: al mejor de 3 sets a 6 games, que es lo habitual.
    games_por_set: 6,
    cantidad_zonas: null,
    clasifican_por_zona: null,
    termina_en_zonas: false,
    categoria: null,
    evento_id: evento?.id ?? null,
    observaciones: null,
  }
}

/** El nombre que se propone para una categoría de un evento. */
function nombreDeCategoria(evento: Evento, categoria: string): string {
  return categoria.trim() ? `${evento.nombre} — ${categoria.trim()}` : ''
}

/** Alta de un torneo, o de una categoría de un evento si viene `evento`.
 *
 * 🔴 **El formato se elige acá y no se puede cambiar después.** Cambiarlo con
 * el torneo sorteado no es editar un campo: es tirar el fixture, y con él los
 * partidos jugados. Por eso el formulario lo explica antes y no después.
 */
export function FormularioDeTorneo({
  abierto,
  sucursalId,
  evento = null,
  onCerrar,
  onCreado,
}: {
  abierto: boolean
  sucursalId: number
  /** Si viene, el torneo es una categoría de ese evento: hereda sus fechas. */
  evento?: Evento | null
  onCerrar: () => void
  onCreado: (torneo: Torneo) => void
}) {
  const [datos, setDatos] = useState<TorneoEntrada>(() => vacio(sucursalId, evento))
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  // Mientras el nombre no se toque a mano, sigue a la categoría.
  const [nombreAMano, setNombreAMano] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setError(null)
    setNombreAMano(false)
    setDatos(vacio(sucursalId, evento))
  }, [abierto, sucursalId, evento])

  function set<K extends keyof TorneoEntrada>(campo: K, valor: TorneoEntrada[K]) {
    setDatos((d) => ({ ...d, [campo]: valor }))
  }

  function elegirCategoria(categoria: string) {
    setDatos((d) => ({
      ...d,
      categoria,
      nombre: evento && !nombreAMano ? nombreDeCategoria(evento, categoria) : d.nombre,
    }))
  }

  function elegirDeporte(deporte: string) {
    // 🔑 Al cambiar de deporte se vuelve al default de ese deporte: los games por
    // set son sólo de pádel y de tenis, y el backend rechaza un fútbol que los
    // traiga pegados del click anterior.
    const conSets = DEPORTES_DE_SETS.includes(deporte)
    setDatos((d) => ({
      ...d,
      deporte,
      sets_para_ganar: SETS_POR_DEPORTE[deporte] ?? 1,
      games_por_set: conSets ? 6 : null,
    }))
  }

  const conSets = DEPORTES_DE_SETS.includes(datos.deporte)
  const modalidad = MODALIDADES_DE_PARTIDO.find(
    (m) =>
      m.sets_para_ganar === datos.sets_para_ganar &&
      m.games_por_set === datos.games_por_set,
  )

  function elegirFormato(formato: FormatoTorneo) {
    // 🔴 Los parámetros de zona **se limpian** al salir del formato que los usa:
    // el backend rechaza un torneo de eliminación que los traiga —y con razón,
    // son números que no significarían nada—, pero si quedaran pegados del
    // click anterior el operador vería un 422 sin entender qué mandó.
    setDatos((d) => ({
      ...d,
      formato,
      cantidad_zonas: formato === 'zonas' ? (d.cantidad_zonas ?? 2) : null,
      clasifican_por_zona:
        formato === 'zonas' && !d.termina_en_zonas ? (d.clasifican_por_zona ?? 2) : null,
      termina_en_zonas: formato === 'zonas' ? d.termina_en_zonas : false,
    }))
  }

  /** Qué pasa después de las zonas: pasan a llaves o termina ahí. */
  function elegirFinal(terminaEnZonas: boolean) {
    setDatos((d) => ({
      ...d,
      termina_en_zonas: terminaEnZonas,
      clasifican_por_zona: terminaEnZonas ? null : (d.clasifican_por_zona ?? 2),
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
          <DialogTitle>
            {evento ? `Nueva categoría de ${evento.nombre}` : 'Nuevo torneo'}
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={enviar} className="space-y-3 text-sm">
          <label className="block space-y-1">
            <span className="font-medium">Nombre</span>
            <Input
              autoFocus={!evento}
              value={datos.nombre}
              onChange={(e) => {
                setNombreAMano(true)
                set('nombre', e.target.value)
              }}
              placeholder={evento ? `${evento.nombre} — Caballeros 5ta` : 'Americano de primavera'}
            />
          </label>

          <label className="block space-y-1">
            <span className="font-medium">
              Categoría{' '}
              {!evento && <span className="text-muted-foreground">(opcional)</span>}
            </span>
            <Input
              autoFocus={!!evento}
              list="categorias-sugeridas"
              value={datos.categoria ?? ''}
              onChange={(e) => elegirCategoria(e.target.value)}
              placeholder="Caballeros 5ta, Damas, Mixto…"
              maxLength={60}
            />
            <datalist id="categorias-sugeridas">
              {CATEGORIAS_SUGERIDAS.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </label>

          <label className="block space-y-1">
            <span className="font-medium">Deporte</span>
            {/* select-cerrado: los 7 deportes de la constante DEPORTES (el backend los valida igual) */}
            <select
              className="h-9 w-full rounded-md border bg-transparent px-3"
              value={datos.deporte}
              onChange={(e) => elegirDeporte(e.target.value)}
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
            <div className="space-y-2">
              <label className="block space-y-1">
                <span className="font-medium">Zonas</span>
                <Input
                  type="number"
                  min={2}
                  value={datos.cantidad_zonas ?? 2}
                  onChange={(e) => set('cantidad_zonas', Number(e.target.value))}
                />
                <span className="text-xs text-muted-foreground">
                  Las parejas se reparten en zonas y juegan todas contra todas
                  dentro de la suya.
                </span>
              </label>

              <fieldset className="space-y-1">
                <legend className="font-medium">Después de las zonas</legend>
                <div className="space-y-2 pt-1">
                  <label className="flex cursor-pointer items-start gap-2 rounded-md border bg-card p-2">
                    <input
                      type="radio"
                      name="despues-de-las-zonas"
                      className="mt-1"
                      checked={!datos.termina_en_zonas}
                      onChange={() => elegirFinal(false)}
                    />
                    <span className="flex-1">
                      <span className="block font-medium">Pasan a llaves</span>
                      <span className="block text-xs text-muted-foreground">
                        Los primeros de cada zona juegan una llave de eliminación.
                      </span>
                      {!datos.termina_en_zonas && (
                        <select
                          aria-label="Cuántos pasan por zona"
                          className="mt-1 h-9 w-full rounded-md border bg-transparent px-3"
                          value={datos.clasifican_por_zona ?? 2}
                          onChange={(e) => set('clasifican_por_zona', Number(e.target.value))}
                        >
                          {/* Sólo 1 o 2: con tres o más, la regla que evita que
                              dos de la misma zona se crucen en el playoff deja
                              de ser una rotación y depende del reglamento. Ver
                              `fixture.orden_de_clasificados`. */}
                          <option value={1}>Sólo el primero</option>
                          <option value={2}>Los dos primeros</option>
                        </select>
                      )}
                    </span>
                  </label>
                  <label className="flex cursor-pointer items-start gap-2 rounded-md border bg-card p-2">
                    <input
                      type="radio"
                      name="despues-de-las-zonas"
                      className="mt-1"
                      checked={datos.termina_en_zonas === true}
                      onChange={() => elegirFinal(true)}
                    />
                    <span>
                      <span className="block font-medium">Termina en las zonas</span>
                      <span className="block text-xs text-muted-foreground">
                        Sin llaves: el primero de cada zona es el campeón de su zona.
                      </span>
                    </span>
                  </label>
                </div>
              </fieldset>
            </div>
          )}

          {evento ? (
            <p className="rounded-md border bg-card p-2 text-xs text-muted-foreground">
              Fechas del evento: {fecha(evento.desde)}
              {evento.hasta ? ` al ${fecha(evento.hasta)}` : ''}. Todas las categorías
              juegan los mismos días.
            </p>
          ) : (
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
          )}

          {conSets ? (
            <fieldset className="space-y-1">
              <legend className="font-medium">Cómo se juega cada partido</legend>
              <div className="space-y-2 pt-1">
                {MODALIDADES_DE_PARTIDO.map((m) => (
                  <label
                    key={m.clave}
                    className="flex cursor-pointer items-start gap-2 rounded-md border bg-card p-2"
                  >
                    <input
                      type="radio"
                      name="modalidad"
                      className="mt-1"
                      checked={modalidad?.clave === m.clave}
                      onChange={() =>
                        setDatos((d) => ({
                          ...d,
                          sets_para_ganar: m.sets_para_ganar,
                          games_por_set: m.games_por_set,
                        }))
                      }
                    />
                    <span>
                      <span className="block font-medium">{m.nombre}</span>
                      <span className="block text-xs text-muted-foreground">{m.ayuda}</span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          ) : (
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
          )}

          <AvisoDeError mensaje={error} />

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onCerrar}>
              Cancelar
            </Button>
            <Button
              type="submit"
              disabled={
                enviando || !datos.nombre.trim() || (!!evento && !datos.categoria?.trim())
              }
            >
              {enviando ? 'Creando…' : evento ? 'Crear categoría' : 'Crear torneo'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
