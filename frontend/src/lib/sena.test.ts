import { describe, expect, it } from 'vitest'

import { textoCortoDeSena, textoDelPlazoDeSena } from './sena'

const VENCE = '2026-09-01T10:00:00-03:00'

describe('el plazo de la seña de una reserva del mostrador', () => {
  it('dice hasta cuándo tiene para pagar, con fecha y hora de Argentina', () => {
    expect(textoDelPlazoDeSena('pendiente_pago', VENCE)).toBe(
      'Tiene hasta el 01-09-2026 10:00 para pagar la seña: después el turno se libera solo.',
    )
  })

  it('🔴 una pendiente de pago SIN vencimiento lo dice: es de antes del plazo y no se libera sola', () => {
    expect(textoDelPlazoDeSena('pendiente_pago', null)).toMatch(/^Sin vencimiento/)
    expect(textoDelPlazoDeSena('pendiente_pago', undefined)).toMatch(/hay que confirmarla o cancelarla a mano/)
  })

  it.each(['confirmada', 'provisoria', 'jugada', 'cancelada', 'bloqueo', null])(
    'no dice nada de la seña de una reserva %s',
    (estado) => {
      expect(textoDelPlazoDeSena(estado, VENCE)).toBeNull()
      expect(textoCortoDeSena(estado, VENCE)).toBeNull()
    },
  )

  it('el casillero de la agenda lo dice corto, sin el año', () => {
    expect(textoCortoDeSena('pendiente_pago', VENCE)).toBe('seña hasta 01-09 10:00')
    expect(textoCortoDeSena('pendiente_pago', null)).toBe('sin vencimiento')
  })
})
