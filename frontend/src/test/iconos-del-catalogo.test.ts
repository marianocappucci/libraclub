// El menú y los títulos de LibraClub usan el catálogo de íconos de identidad de la familia (`libra-ui/iconos-identidad`, ADR-035).
//
// 🔴 **Lee los FUENTES, no el DOM**, por lo mismo que `titulos-con-icono.test.ts`: el menú no se exporta y lo que hay que impedir no es que
// una pantalla se rompa sino que vuelvan a divergir los productos entre sí. El catálogo es uno, el mismo en los ocho productos; la tabla
// aprobada vive en el wiki (`catalogo-iconos-identidad-diseno`) y el kit la repite en su propio test.
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import * as lucide from 'lucide-react'
import { auditarMenuContraCatalogo, iconoDelTitulo, iconosDelNav } from 'libra-ui/auditoria-de-titulos'
import { ICONOS, type Concepto } from 'libra-ui/iconos-identidad'

const SRC = join(process.cwd(), 'src')
const leer = (ruta: string) => readFileSync(join(SRC, ruta), 'utf8')

/** Qué concepto del catálogo es cada entrada del menú que lo tiene. Las que no están (Turnos fijos, Torneos, Canchas, Buffet, Horario de
 *  atención, Devoluciones) son conceptos de este producto y no entran al catálogo (ver el wiki: «los conceptos que existen en un solo
 *  producto quedan como están, salvo que choquen con uno»). */
const MENU: Record<string, Concepto> = {
  '/agenda': 'agenda',
  '/caja': 'caja',
  '/cierre-diario': 'cierreDiario',
  '/cuenta-corriente': 'cuentaCorriente',
  '/clientes': 'clientes',
  '/tarifas': 'listasDePrecio',
  '/cajas': 'cajas',
  '/sucursales': 'sucursales',
  '/facturas': 'comprobantes',
  '/mp-bandeja': 'pagosMercadoPago',
  '/usuarios': 'usuarios',
  '/logs': 'logDeActividad',
  '/configuracion': 'configuracion',
}

/** Pantallas que cuelgan de una entrada del menú pero son OTRO concepto del catálogo: `titulos-con-icono.test.ts` las exime del «mismo ícono
 *  que el sidebar» (cuelgan de `/caja`, que es `Wallet`), y acá se afirma el ícono que sí les toca. */
const TITULOS: Record<string, Concepto> = {
  TurnosDeCaja: 'turnosDeCaja',
  TurnoDeCajaDetalle: 'turnosDeCaja',
  CajaPorMedio: 'cajaPorMedio',
  MovimientosDeCaja: 'caja',
  CuentaCorrienteDetalle: 'cuentaCorriente',
  FacturaNueva: 'comprobantes',
}

describe('el menú usa el catálogo de íconos de identidad', () => {
  it('🔴 cada entrada de un concepto del catálogo lleva el ícono del catálogo', () => {
    const r = auditarMenuContraCatalogo(leer('components/Layout.tsx'), MENU, 'libraclub')
    expect(r.mal).toEqual([])
    expect(r.faltan).toEqual([])
    // El control: un parser que no encuentra nada también deja `mal` vacío.
    expect(r.medidas).toBe(Object.keys(MENU).length)
  })

  it('🔴 ninguna entrada propia del producto usa el ícono de un concepto del catálogo', () => {
    // Las entradas que no son del catálogo (Turnos fijos, Torneos, Canchas, Buffet, Horario de atención, Devoluciones) no pueden repetir un
    // dibujo del catálogo: `Horario de atención` era `Clock`, que es del turno de caja.
    const delCatalogo = new Set(Object.values(ICONOS).map((i) => (i as { displayName?: string }).displayName))
    // `startsWith('/')`: el parser del kit lee `to: '…'` y también el `producto: 'libraclub'` del `createLayout` (termina en «to:»).
    const propias = [...iconosDelNav(leer('components/Layout.tsx'))].filter(([ruta]) => ruta.startsWith('/') && !(ruta in MENU))
    expect(propias.map(([ruta]) => ruta).sort()).toEqual(['/buffet', '/canchas', '/devoluciones', '/horarios', '/torneos', '/turnos-fijos'])
    const choques = propias.filter(([, icono]) => {
      const dn = (lucide as unknown as Record<string, { displayName?: string } | undefined>)[icono]?.displayName ?? icono
      return delCatalogo.has(dn)
    })
    expect(choques).toEqual([])
  })
})

describe('los títulos de las pantallas de otro concepto usan el catálogo', () => {
  it.each(Object.entries(TITULOS))('🔴 %s lleva ICONOS.%s', (pantalla, concepto) => {
    expect(iconoDelTitulo(leer(`pages/${pantalla}.tsx`)).icono).toBe(`ICONOS.${concepto}`)
  })
})
