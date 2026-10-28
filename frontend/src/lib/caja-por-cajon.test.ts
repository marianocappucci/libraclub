import { describe, expect, it } from 'vitest'

import { partirMediosDelCierre, partirPorCajon } from './caja-por-cajon'

describe('partirPorCajon', () => {
  it('separa el efectivo de lo que no está en el cajón', () => {
    const r = partirPorCajon({
      efectivo: 12000, transferencia: 8000, mercadopago: 3000, tarjeta_debito: 5000,
    })
    expect(r.efectivo).toBe(12000)
    expect(r.fuera.map((l) => l.medio)).toEqual(['transferencia', 'tarjeta_debito', 'mercadopago'])
    expect(r.totalFuera).toBe(16000)
    expect(r.totalCobrado).toBe(28000)
  })

  it('🔑 el efectivo NO entra en lo de afuera: si entrara, el esperado del cajón no se explicaría', () => {
    const r = partirPorCajon({ efectivo: 500, transferencia: 100 })
    expect(r.fuera.some((l) => l.medio === 'efectivo')).toBe(false)
    expect(r.totalFuera).toBe(100)
  })

  it('un turno sin movimientos de efectivo tiene efectivo en cero, no indefinido', () => {
    expect(partirPorCajon({ transferencia: 700 }).efectivo).toBe(0)
    expect(partirPorCajon({}).totalCobrado).toBe(0)
    expect(partirPorCajon(null).fuera).toEqual([])
  })

  it('los medios que quedaron en cero (un egreso que los compensó) no ocupan un renglón', () => {
    const r = partirPorCajon({ efectivo: 100, transferencia: 0 })
    expect(r.fuera).toEqual([])
  })

  it('suma sin arrastrar el error de los decimales', () => {
    const r = partirPorCajon({ transferencia: 0.1, mercadopago: 0.2 })
    expect(r.totalFuera).toBe(0.3)
  })

  it('un medio sin especificar sigue visible como de afuera', () => {
    const r = partirPorCajon({ efectivo: 10, sin_medio: 40 })
    expect(r.fuera).toEqual([{ medio: 'sin_medio', total: 40 }])
  })
})

describe('partirMediosDelCierre', () => {
  it('parte la lista del cierre diario por el mismo criterio', () => {
    const r = partirMediosDelCierre([
      { medio_pago: 'efectivo', neto: 9000 },
      { medio_pago: 'transferencia', neto: 4000 },
      { medio_pago: 'mercadopago', neto: 1000 },
    ])
    expect(r.efectivo).toBe(9000)
    expect(r.totalFuera).toBe(5000)
    expect(r.totalCobrado).toBe(14000)
  })

  it('una lista vacía no rompe', () => {
    expect(partirMediosDelCierre([]).totalCobrado).toBe(0)
    expect(partirMediosDelCierre(undefined).efectivo).toBe(0)
  })
})
