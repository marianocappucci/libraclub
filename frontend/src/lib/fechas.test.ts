import { describe, expect, it } from 'vitest'
import { diaISO, fecha, fechaHora, hora, lunesDeLaSemana, nombreDelDia, pesos } from './fechas'

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
