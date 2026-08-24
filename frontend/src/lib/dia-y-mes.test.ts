// `diaYMes`: la cabecera de la grilla semanal.
//
// 🔴 El separador es el GUION. LibraClub es el producto que sirve de modelo del
// helper unico y aun asi esta cabecera armaba `22/08` a mano, con barra: el
// formato corto se habia escapado de la convencion justo en la referencia.
import { describe, expect, it } from 'vitest'

import { diaYMes } from '../lib/fechas'

describe('diaYMes()', () => {
  it('da `dd-mm`, con guion', () => {
    expect(diaYMes('2026-08-22')).toBe('22-08')
  })

  it('nunca sale con barra', () => {
    for (const iso of ['2026-08-22', '2026-01-09', '2026-12-31']) {
      expect(diaYMes(iso)).not.toContain('/')
    }
  })

  it('no confunde el dia con el mes', () => {
    // Con `2026-01-01` las dos lecturas dan el mismo texto: hace falta una
    // fecha donde `dd-mm` y `mm-dd` se distingan.
    expect(diaYMes('2026-03-11')).toBe('11-03')
  })

  it('lo que no es una fecha vuelve como vino', () => {
    expect(diaYMes('')).toBe('')
    expect(diaYMes('2026-08')).toBe('2026-08')
  })
})
