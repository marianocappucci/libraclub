import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Lo que estas pantallas deciden, y que un test puede hacer fallar:
 *
 * 1. que un cruce **sin rivales definidos** no ofrezca cargar resultado ni dar
 *    cancha — un turno reservado para un partido que no se sabe quién juega es
 *    un turno tirado;
 * 2. que «sin cancha» se avise **sólo** en los partidos que se pueden jugar,
 *    porque marcar los que esperan un ganador inventa trabajo;
 * 3. que el horario se mande **sin offset**, que es lo que hace que las 20:00
 *    sean las 20:00 del complejo;
 * 4. que sortear **avise que es irreversible** antes de hacerlo;
 * 5. que el mostrador no vea los botones de admin;
 * 6. que la línea de corte de la tabla marque a los que clasifican.
 */

const ver = vi.fn()
const competidores = vi.fn()
const fixtureApi = vi.fn()
const posiciones = vi.fn()
const programar = vi.fn()
const cargarResultado = vi.fn()
const sortear = vi.fn()
const playoff = vi.fn()
const canchasListar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    torneos: {
      ...(real.torneos as object),
      ver, competidores, fixture: fixtureApi, posiciones, programar,
      cargarResultado, sortear, playoff,
      liberar: vi.fn(), borrarResultado: vi.fn(), bajar: vi.fn(), cancelar: vi.fn(),
    },
    canchas: { ...(real.canchas as object), listar: canchasListar },
  }
})

let ROL = 'admin'
vi.mock('@/context/AuthContext', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    useAuth: () => ({ user: { role: ROL, name: 'Quien sea' }, loading: false }),
  }
})

const { Torneo } = await import('./Torneo')

const TORNEO = {
  id: 1, sucursal_id: 1, nombre: 'Apertura', deporte: 'padel',
  formato: 'eliminacion' as const, estado: 'sorteado' as const,
  desde: '2026-09-05', hasta: null, sets_para_ganar: 2,
  cantidad_zonas: null, clasifican_por_zona: null, semilla: 4242,
  observaciones: null,
}

const PARTIDO = {
  id: 10, etapa: 'llaves' as const, zona_id: null, zona: null, ronda: 1, orden: 0,
  instancia: 'Semifinal',
  competidor_a_id: 1, competidor_a: 'Pérez / García',
  competidor_b_id: 2, competidor_b: 'López / Díaz',
  avanza_a_id: 12, avanza_a_slot: 'a',
  reserva_id: null, cancha: null, comienza_at: null, termina_at: null,
  ganador_id: null, finalizado: false, parciales: [],
}

/** La final, que todavía espera a los dos ganadores. */
const SIN_RIVALES = {
  ...PARTIDO, id: 12, orden: 0, ronda: 2, instancia: 'Final',
  competidor_a_id: null, competidor_a: null,
  competidor_b_id: null, competidor_b: null,
  avanza_a_id: null, avanza_a_slot: null,
}

function montar() {
  return render(
    <MemoryRouter initialEntries={['/torneos/1']}>
      <Routes>
        <Route path="/torneos/:id" element={<Torneo />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  ROL = 'admin'
  for (const espia of [ver, competidores, fixtureApi, posiciones, programar,
                       cargarResultado, sortear, playoff, canchasListar]) {
    espia.mockReset()
  }
  ver.mockResolvedValue(TORNEO)
  competidores.mockResolvedValue([])
  fixtureApi.mockResolvedValue({ rondas: 2, partidos: [PARTIDO, SIN_RIVALES] })
  posiciones.mockResolvedValue([])
  canchasListar.mockResolvedValue([
    { id: 7, sucursal_id: 1, nombre: 'Cancha 1', deporte: 'padel',
      duracion_turno_min: 90, techada: false, iluminacion: true, superficie: null,
      orden: 0, activa: true, observaciones: null },
  ])
  programar.mockResolvedValue(PARTIDO)
  cargarResultado.mockResolvedValue(PARTIDO)
})

describe('el fixture', () => {
  it('avisa «sin cancha» sólo en los partidos que se pueden jugar', async () => {
    // 🔑 El cruce que espera un ganador NO está sin programar: está esperando.
    // Marcarlo daría trabajo que no existe, y con un cuadro de 16 son ocho
    // avisos falsos.
    montar()
    await waitFor(() => expect(screen.getByText('Semifinal')).toBeInTheDocument())
    expect(screen.getAllByText('Sin cancha')).toHaveLength(1)
  })

  it('muestra «a definir» en el lugar que todavía no tiene dueño', async () => {
    // Un casillero en blanco se lee como un error de carga, y en un cuadro con
    // byes hay varios desde el minuto cero.
    montar()
    await waitFor(() => expect(screen.getAllByText('a definir')).toHaveLength(2))
  })

  it('marca al ganador de un partido jugado', async () => {
    fixtureApi.mockResolvedValue({
      rondas: 2,
      partidos: [
        { ...PARTIDO, finalizado: true, ganador_id: 1,
          parciales: [{ numero: 1, puntos_a: 6, puntos_b: 4 },
                      { numero: 2, puntos_a: 6, puntos_b: 3 }] },
        SIN_RIVALES,
      ],
    })
    montar()
    // Un espacio y no dos: testing-library normaliza los blancos del DOM. El
    // separador real del marcador son dos, para que se lea de lejos.
    await waitFor(() => expect(screen.getByText('6-4 6-3')).toBeInTheDocument())
  })
})

describe('el diálogo de un partido', () => {
  it('no ofrece cargar resultado si no se sabe quiénes juegan', async () => {
    // 🔴 El backend lo rechaza igual; lo que este test protege es que la
    // pantalla no ofrezca un botón que sólo puede dar error, y sobre todo que
    // no deje ocupar una cancha para un partido sin jugadores.
    montar()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^Final:/ })).toBeInTheDocument(),
    )
    await userEvent.click(screen.getByRole('button', { name: /^Final:/ }))

    const dialogo = await screen.findByRole('dialog')
    expect(
      within(dialogo).getByText(/Falta que se definan los ganadores/),
    ).toBeInTheDocument()
    expect(within(dialogo).queryByText('Dar cancha')).not.toBeInTheDocument()
    expect(within(dialogo).queryByText('Guardar resultado')).not.toBeInTheDocument()
  })

  it('sí lo ofrece cuando los dos rivales están definidos', async () => {
    // El control del test de arriba: sin esto, una pantalla que nunca ofrece
    // nada también pasaría.
    montar()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^Semifinal:/ })).toBeInTheDocument(),
    )
    await userEvent.click(screen.getByRole('button', { name: /^Semifinal:/ }))

    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByText('Dar cancha')).toBeInTheDocument()
    expect(within(dialogo).getByText('Guardar resultado')).toBeInTheDocument()
  })

  it('manda el horario sin offset, para que sean las 20:00 del complejo', async () => {
    // 🔴 Un ISO con la zona del navegador movería el partido si alguien carga
    // desde otro huso. El backend lee el naive como hora local del complejo.
    montar()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^Semifinal:/ })).toBeInTheDocument(),
    )
    await userEvent.click(screen.getByRole('button', { name: /^Semifinal:/ }))
    await userEvent.click(await screen.findByText('Dar cancha'))

    await waitFor(() => expect(programar).toHaveBeenCalled())
    const [, cuerpo] = programar.mock.calls[0]
    expect(cuerpo.comienza_at).toBe('2026-09-05T20:00:00')
    expect(cuerpo.comienza_at).not.toMatch(/Z|[+-]\d\d:\d\d$/)
    expect(cuerpo.cancha_id).toBe(7)
  })

  it('arranca con tantos parciales como haga falta ganar', async () => {
    montar()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^Semifinal:/ })).toBeInTheDocument(),
    )
    await userEvent.click(screen.getByRole('button', { name: /^Semifinal:/ }))
    const dialogo = await screen.findByRole('dialog')
    // Dos sets para un torneo al mejor de tres: dos campos por lado.
    expect(
      within(dialogo).getAllByLabelText(/Pérez \/ García, parcial/),
    ).toHaveLength(2)
  })

  it('no deja agregar más parciales de los que el partido puede durar', async () => {
    montar()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^Semifinal:/ })).toBeInTheDocument(),
    )
    await userEvent.click(screen.getByRole('button', { name: /^Semifinal:/ }))
    const dialogo = await screen.findByRole('dialog')

    // Al mejor de tres: se puede llegar a tres y ahí el botón desaparece.
    await userEvent.click(within(dialogo).getByText('Agregar parcial'))
    expect(
      within(dialogo).getAllByLabelText(/Pérez \/ García, parcial/),
    ).toHaveLength(3)
    expect(within(dialogo).queryByText('Agregar parcial')).not.toBeInTheDocument()
  })
})

describe('el sorteo', () => {
  it('avisa que después no se puede tocar la lista', async () => {
    ver.mockResolvedValue({ ...TORNEO, estado: 'armado', semilla: null })
    competidores.mockResolvedValue([
      { id: 1, nombre: 'A', siembra: null, zona_id: null, zona: null, integrantes: [] },
      { id: 2, nombre: 'B', siembra: null, zona_id: null, zona: null, integrantes: [] },
    ])
    fixtureApi.mockResolvedValue({ rondas: 0, partidos: [] })
    const avisar = vi.spyOn(window, 'confirm').mockReturnValue(false)

    montar()
    await waitFor(() => expect(screen.getByText('Sortear')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Sortear'))

    expect(avisar).toHaveBeenCalled()
    expect(avisar.mock.calls[0][0]).toMatch(/no se pueden agregar ni sacar/)
    // Dijo que no: no se sortea.
    expect(sortear).not.toHaveBeenCalled()
    avisar.mockRestore()
  })

  it('no se ofrece con menos de dos inscriptos', async () => {
    ver.mockResolvedValue({ ...TORNEO, estado: 'armado', semilla: null })
    competidores.mockResolvedValue([
      { id: 1, nombre: 'A', siembra: null, zona_id: null, zona: null, integrantes: [] },
    ])
    fixtureApi.mockResolvedValue({ rondas: 0, partidos: [] })
    montar()
    await waitFor(() => expect(screen.getByText('Sortear')).toBeInTheDocument())
    expect(screen.getByText('Sortear').closest('button')).toBeDisabled()
  })

  it('dice «En curso» en cuanto hay un partido jugado', async () => {
    // 🔑 No es un estado guardado: el backend dice `sorteado` y acá se deriva
    // de si ya hay resultados. Un estado más en la base habría que acordarse de
    // moverlo en cada carga, y el día que alguien se olvide diría «sorteado»
    // con media llave jugada.
    fixtureApi.mockResolvedValue({
      rondas: 2,
      partidos: [{ ...PARTIDO, finalizado: true, ganador_id: 1 }, SIN_RIVALES],
    })
    montar()
    expect(await screen.findByText('En curso')).toBeInTheDocument()
  })

  it('y «Sorteado» mientras no se jugó nada', async () => {
    // El control: un badge fijo en «En curso» pasaría el test de arriba.
    montar()
    expect(await screen.findByText('Sorteado')).toBeInTheDocument()
  })

  it('muestra la semilla, que es lo que hace auditable el sorteo', async () => {
    montar()
    await waitFor(() => expect(screen.getByText(/sorteo #4242/)).toBeInTheDocument())
  })
})

describe('el playoff', () => {
  const ZONAS = {
    ...TORNEO, formato: 'zonas' as const, cantidad_zonas: 2, clasifican_por_zona: 2,
  }
  const DE_GRUPOS = {
    ...PARTIDO, etapa: 'grupos' as const, zona_id: 1, zona: 'Zona A',
    instancia: 'Zona A · Fecha 1', avanza_a_id: null, avanza_a_slot: null,
  }

  it('no se ofrece con la fase de grupos sin terminar', async () => {
    ver.mockResolvedValue(ZONAS)
    fixtureApi.mockResolvedValue({ rondas: 0, partidos: [DE_GRUPOS] })
    montar()
    await waitFor(() => expect(screen.getByText('Zona A')).toBeInTheDocument())
    expect(screen.queryByText('Largar el playoff')).not.toBeInTheDocument()
  })

  it('se ofrece cuando terminaron todos los partidos de grupos', async () => {
    ver.mockResolvedValue(ZONAS)
    fixtureApi.mockResolvedValue({
      rondas: 0,
      partidos: [{ ...DE_GRUPOS, finalizado: true, ganador_id: 1 }],
    })
    montar()
    await waitFor(() =>
      expect(screen.getByText('Largar el playoff')).toBeInTheDocument(),
    )
  })

  it('no se ofrece dos veces: con llaves ya armadas desaparece', async () => {
    ver.mockResolvedValue(ZONAS)
    fixtureApi.mockResolvedValue({
      rondas: 1,
      partidos: [{ ...DE_GRUPOS, finalizado: true, ganador_id: 1 }, PARTIDO],
    })
    montar()
    await waitFor(() => expect(screen.getByText('Llaves')).toBeInTheDocument())
    expect(screen.queryByText('Largar el playoff')).not.toBeInTheDocument()
  })
})

describe('los roles', () => {
  it('el mostrador no ve sortear ni cancelar', async () => {
    ROL = 'staff'
    ver.mockResolvedValue({ ...TORNEO, estado: 'armado', semilla: null })
    competidores.mockResolvedValue([
      { id: 1, nombre: 'A', siembra: null, zona_id: null, zona: null, integrantes: [] },
      { id: 2, nombre: 'B', siembra: null, zona_id: null, zona: null, integrantes: [] },
    ])
    fixtureApi.mockResolvedValue({ rondas: 0, partidos: [] })
    montar()
    await waitFor(() => expect(screen.getByText('Inscribir')).toBeInTheDocument())
    expect(screen.queryByText('Sortear')).not.toBeInTheDocument()
    expect(screen.queryByText('Cancelar torneo')).not.toBeInTheDocument()
  })

  it('pero sí ve inscribir, que es lo suyo', async () => {
    // El control: cerrar TODA la pantalla al mostrador también pasaría el test
    // de arriba, y dejaría al encargado sin poder anotar a nadie.
    ROL = 'staff'
    ver.mockResolvedValue({ ...TORNEO, estado: 'armado', semilla: null })
    fixtureApi.mockResolvedValue({ rondas: 0, partidos: [] })
    montar()
    await waitFor(() => expect(screen.getByText('Inscribir')).toBeInTheDocument())
  })
})

describe('las posiciones', () => {
  const TABLA = {
    zona_id: 1,
    nombre: 'Zona A',
    filas: [
      { competidor_id: 1, nombre: 'Primero', jugados: 3, ganados: 3, empatados: 0,
        perdidos: 0, a_favor: 9, en_contra: 2, diferencia: 7, puntos: 9 },
      { competidor_id: 2, nombre: 'Segundo', jugados: 3, ganados: 2, empatados: 0,
        perdidos: 1, a_favor: 7, en_contra: 5, diferencia: 2, puntos: 6 },
      { competidor_id: 3, nombre: 'Tercero', jugados: 3, ganados: 0, empatados: 0,
        perdidos: 3, a_favor: 1, en_contra: 10, diferencia: -9, puntos: 0 },
    ],
  }

  it('la pestaña no aparece si no hay tabla que mirar', async () => {
    // Un cuadro de eliminación no tiene posiciones. Una pestaña vacía hace que
    // el encargado la abra buscando algo.
    montar()
    await waitFor(() => expect(screen.getByText('Fixture')).toBeInTheDocument())
    expect(screen.queryByText('Posiciones')).not.toBeInTheDocument()
  })

  it('aparece y muestra las filas cuando hay grupos', async () => {
    ver.mockResolvedValue({
      ...TORNEO, formato: 'zonas', cantidad_zonas: 2, clasifican_por_zona: 2,
    })
    posiciones.mockResolvedValue([TABLA])
    montar()
    await userEvent.click(await screen.findByText('Posiciones'))
    expect(await screen.findByText('Primero')).toBeInTheDocument()
    // La diferencia positiva lleva el signo: `+7` y no `7`.
    expect(screen.getByText('+7')).toBeInTheDocument()
    expect(screen.getByText('-9')).toBeInTheDocument()
  })
})
