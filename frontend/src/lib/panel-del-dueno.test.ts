import { describe, expect, it } from 'vitest'
import type { SucursalDelPanel } from '@/lib/api'
import {
  clavesDeOrigen, horasDelMapa, porcentaje, rangoDeHora, sumarIngresos, turnosPerdidos, variacion,
} from './panel-del-dueno'

function sucursal(extra: Partial<SucursalDelPanel> = {}): SucursalDelPanel {
  return {
    sucursal_id: 1, sucursal: 'Centro', ocupacion_pct: 50, franjas: [], horas_abiertas: 10, horas_reservadas: 5,
    ingresos: { reservas: 100, senas: 20, buffet: 30, total: 150, total_periodo_anterior: 100 },
    canceladas: 0, ausentes: 0, reservas: 0,
    origen: { mostrador: 0, telefono: 0, whatsapp: 0, portal: 0, serie: 0 },
    ...extra,
  }
}

describe('porcentaje', () => {
  it('formatea con coma decimal y un decimal como máximo', () => {
    expect(porcentaje(63.5)).toBe('63,5 %')
    expect(porcentaje(100)).toBe('100 %')
    expect(porcentaje(0)).toBe('0 %')
  })

  it('🔑 null es «—» y no 0 %: no abrir no es no vender', () => {
    expect(porcentaje(null)).toBe('—')
    expect(porcentaje(undefined)).toBe('—')
  })
})

describe('variacion', () => {
  it('es el cambio porcentual contra el período anterior', () => {
    expect(variacion(150, 100)).toBe(50)
    expect(variacion(50, 100)).toBe(-50)
    expect(variacion(100, 100)).toBe(0)
  })

  it('🔴 sin período anterior no hay variación: +100 % sobre cero sería inventar una tendencia', () => {
    expect(variacion(500, 0)).toBeNull()
  })
})

describe('sumarIngresos', () => {
  it('suma las sucursales', () => {
    const t = sumarIngresos([
      sucursal(),
      sucursal({ sucursal_id: 2, ingresos: { reservas: 10, senas: 0, buffet: 5, total: 15, total_periodo_anterior: 20 } }),
    ])
    expect(t).toMatchObject({ reservas: 110, senas: 20, buffet: 35, total: 165, total_periodo_anterior: 120, medible: true })
  })

  it('🔴 si una sucursal no puede medir la plata el total deja de ser medible, no se calla', () => {
    const t = sumarIngresos([sucursal(), sucursal({ sucursal_id: 2, ingresos: null })])
    expect(t.medible).toBe(false)
  })

  it('sin sucursales no hay nada que medir', () => {
    expect(sumarIngresos([]).medible).toBe(false)
  })
})

describe('turnosPerdidos', () => {
  it('el ausente ya está en las reservas y el cancelado no: lo pedido es reservas + canceladas', () => {
    // 8 reservas (2 de ellas ausentes) y 2 canceladas: se pidieron 10, se perdieron 4.
    expect(turnosPerdidos(2, 2, 8)).toEqual({ perdidos: 4, pct: 40 })
  })

  it('sin pedidos no hay porcentaje', () => {
    expect(turnosPerdidos(0, 0, 0)).toEqual({ perdidos: 0, pct: null })
  })
})

describe('horasDelMapa', () => {
  const f = (hora: number) => ({ dia: 0, hora, ocupacion_pct: 0 })

  it('ordena de la mañana a la noche, sin repetir', () => {
    expect(horasDelMapa([f(20), f(9), f(20), f(14)])).toEqual([9, 14, 20])
  })

  it('🔑 las madrugadas de un complejo que cierra pasada la medianoche van después de la noche, no arriba de todo', () => {
    expect(horasDelMapa([f(1), f(23), f(18), f(0)])).toEqual([18, 23, 0, 1])
  })

  it('un complejo que sólo abre de madrugada no se reordena', () => {
    expect(horasDelMapa([f(3), f(1)])).toEqual([1, 3])
  })
})

describe('rangoDeHora', () => {
  it('es la hora y la siguiente, con la medianoche como 00', () => {
    expect(rangoDeHora(18)).toBe('18:00 – 19:00')
    expect(rangoDeHora(23)).toBe('23:00 – 00:00')
  })
})

describe('clavesDeOrigen', () => {
  it('trae las conocidas y, después, un valor nuevo del backend que la pantalla no sabe nombrar', () => {
    const claves = clavesDeOrigen([sucursal({ origen: { mostrador: 1, kiosco: 2 } })])
    expect(claves.slice(0, 5)).toEqual(['mostrador', 'telefono', 'whatsapp', 'portal', 'serie'])
    expect(claves).toContain('kiosco')
  })
})
