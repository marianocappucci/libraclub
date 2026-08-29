import { describe, expect, it } from 'vitest'
import { diaISO, fecha, fechaHora, hora, lunesDeLaSemana, nombreDelDia, pesos, diasDeDiferencia } from './fechas'

describe('formateo de fechas', () => {
  it('muestra dd-mm-aaaa, no el ISO ni el formato del navegador', () => {
    expect(fecha('2026-09-01T20:00:00-03:00')).toBe('01-09-2026')
  })

  it('usa reloj de 24 h', () => {
    expect(hora('2026-09-01T20:00:00-03:00')).toBe('20:00')
    expect(fechaHora('2026-09-01T20:00:00-03:00')).toBe('01-09-2026 20:00')
  })

  it('convierte a hora de Argentina lo que viene en UTC', () => {
    // Las 23:00 UTC son las 20:00 de Argentina, el mismo día.
    expect(fechaHora('2026-09-01T23:00:00Z')).toBe('01-09-2026 20:00')
  })

  it('🔴 no adelanta el día a la noche, que es cuando más se usa', () => {
    // 22:00 del 1 en Argentina = 01:00 UTC del 2. `toISOString().slice(0,10)`
    // devolvería `2026-09-02` y la agenda abriría en el día equivocado.
    const nocturno = '2026-09-01T22:00:00-03:00'
    expect(new Date(nocturno).toISOString().slice(0, 10)).toBe('2026-09-02')
    expect(diaISO(nocturno)).toBe('2026-09-01')
  })

  it('encuentra el lunes de la semana', () => {
    // 2026-09-01 es martes; su lunes es el 31 de agosto.
    expect(lunesDeLaSemana('2026-09-01T20:00:00-03:00')).toBe('2026-08-31')
    // Y un lunes se devuelve a sí mismo, no la semana anterior.
    expect(lunesDeLaSemana('2026-08-31T10:00:00-03:00')).toBe('2026-08-31')
    // Y un domingo pertenece a la semana que arrancó el lunes anterior.
    expect(lunesDeLaSemana('2026-09-06T10:00:00-03:00')).toBe('2026-08-31')
  })

  it('nombra el día en castellano y capitalizado', () => {
    expect(nombreDelDia('2026-09-01')).toBe('Martes')
    expect(nombreDelDia('2026-08-31')).toBe('Lunes')
  })

  it('muestra pesos argentinos y nunca euros', () => {
    const salida = pesos('12000.00')
    expect(salida).toContain('$')
    expect(salida).not.toContain('€')
    expect(salida).toContain('12.000')
  })

  it('no rompe con vacíos', () => {
    expect(fecha(null)).toBe('')
    expect(fechaHora(undefined)).toBe('')
    expect(pesos('')).toBe('')
    expect(pesos('no es un número')).toBe('')
  })
})

describe('🔴 las fechas sin hora no se corren un día', () => {
  it('un aaaa-mm-dd se muestra tal cual, sin convertir de zona', () => {
    // Es lo que serializa una columna `date`: el extracto de la cuenta
    // corriente, el `desde`/`hasta` de un torneo, el `materializada_hasta` de
    // una serie. `new Date('2026-08-22')` es medianoche UTC = 21:00 del 21 en
    // Argentina, así que convertirlo mostraba SIEMPRE el día anterior.
    expect(fecha('2026-08-22')).toBe('22-08-2026')
    expect(fecha('2026-01-01')).toBe('01-01-2026')
  })

  it('el control — con hora sí se convierte, que es lo que hay que conservar', () => {
    // Sin este caso, "no convertir nunca" pasaría el test de arriba y rompería
    // la agenda: un turno de las 22:00 de Argentina llega como 01:00 UTC del
    // día siguiente y tiene que mostrarse en el día del complejo.
    expect(fecha('2026-09-02T01:00:00Z')).toBe('01-09-2026')
  })
})

describe('diasDeDiferencia', () => {
  it('🔴 cuenta DÍAS de calendario, no tiempo transcurrido', () => {
    // Abierto ayer a las 23:00, mirado hoy a las 08:00: nueve horas, **un
    // día**. Lo que importa para una caja es que cambió la jornada.
    // Dividir la diferencia por 86.400.000 diría 0 y dejaría pasar justo el
    // caso que esto viene a detectar.
    expect(diasDeDiferencia('2026-08-27T23:00:00-03:00', new Date('2026-08-28T08:00:00-03:00')))
      .toBe(1)
  })

  it('🔑 el mismo día da cero, aunque hayan pasado horas', () => {
    // El control del de arriba: sin esto, un helper que siempre devuelve 1
    // pasaría igual.
    expect(diasDeDiferencia('2026-08-28T08:00:00-03:00', new Date('2026-08-28T23:30:00-03:00')))
      .toBe(0)
  })

  it('🔴 y la semana del turno que lo motivó da siete', () => {
    expect(diasDeDiferencia('2026-08-21T22:16:21-03:00', new Date('2026-08-28T15:00:00-03:00')))
      .toBe(7)
  })

  it('🔑 sin fecha no explota', () => {
    expect(diasDeDiferencia(null)).toBe(0)
    expect(diasDeDiferencia(undefined)).toBe(0)
  })
})
