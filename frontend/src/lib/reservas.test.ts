import { describe, expect, it } from 'vitest'

import { numeroDeReserva } from './reservas'

describe('numeroDeReserva', () => {
  it('una reserva del central se nombra por su número', () => {
    expect(numeroDeReserva(41)).toBe('#41')
    // El `origen_id` de la cola viene en texto.
    expect(numeroDeReserva('41')).toBe('#41')
  })

  it('🔴 un id negativo (dada en el nodo, sin subir) no es un número de reserva', () => {
    expect(numeroDeReserva(-48213)).toBe('sin número todavía')
    expect(numeroDeReserva('-48213')).toBe('sin número todavía')
  })

  it('sin id no inventa uno', () => {
    expect(numeroDeReserva(null)).toBe('—')
    expect(numeroDeReserva(undefined)).toBe('—')
    expect(numeroDeReserva('')).toBe('—')
  })
})
