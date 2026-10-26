/** El texto del aviso de Clientes cuenta las dos clases de cambios por revisar (ADR-022, cuarto addendum). */
import { describe, expect, it } from 'vitest'

import { textoDelAviso } from './clientes-en-conflicto'

describe('texto del aviso de clientes por revisar', () => {
  it('sólo los que chocan', () => {
    expect(textoDelAviso({ total: 1, chocan: 1, yaNoChocan: 0 })).toBe(
      'Hay 1 cliente con cambios de la PC del club que chocan con los de la web.',
    )
    expect(textoDelAviso({ total: 3, chocan: 3, yaNoChocan: 0 })).toBe(
      'Hay 3 clientes con cambios de la PC del club que chocan con los de la web.',
    )
  })

  it('sólo los que ya no chocan', () => {
    expect(textoDelAviso({ total: 1, chocan: 0, yaNoChocan: 1 })).toBe(
      'Hay 1 cliente con cambios de la PC del club que ya no choca con los de la web y se puede aplicar.',
    )
    expect(textoDelAviso({ total: 2, chocan: 0, yaNoChocan: 2 })).toBe(
      'Hay 2 clientes con cambios de la PC del club que ya no chocan con los de la web y se pueden aplicar.',
    )
  })

  it('de las dos clases, suma y desglosa', () => {
    expect(textoDelAviso({ total: 3, chocan: 2, yaNoChocan: 1 })).toBe(
      'Hay 3 clientes con cambios de la PC del club para revisar: 2 chocan con los de la web y 1 ya no choca y se puede aplicar.',
    )
  })
})
