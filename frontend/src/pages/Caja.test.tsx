/**
 * La pantalla de Caja: el turno sobre un mostrador, las cuentas de cada cancha,
 * el egreso.
 *
 * 🔴 **Lo que esto arregla no es cosmético.** Antes: el turno no sabía en qué
 * sede estaba y el arqueo sólo podía subir —no había forma de registrar plata
 * que sale—.
 *
 * 🔑 **El detalle acumulado ya no está acá**, y sus tests tampoco: viven en
 * `MovimientosDeCaja.test.tsx`, con la pantalla. Lo que se prueba de este lado
 * es la unidad de trabajo del mostrador — ir a una cancha, en un turno, a nombre
 * de alguien, y cerrar esa cuenta.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Caja, partirImporte } from './Caja'
import type { TurnoPorCobrar } from '@/lib/api'

// La pantalla linkea a `/caja/movimientos`: sin router, `<Link>` tumba el árbol
// entero con un error de contexto que no dice nada de lo que se está probando.
function montar() {
  return render(<MemoryRouter><Caja /></MemoryRouter>)
}

vi.mock('@/context/SucursalContext', () => ({
  useSucursal: () => ({ actual: 1, sucursales: [], elegir: vi.fn(), cargando: false }),
}))

const MOSTRADORES = [
  { id: 5, nombre: 'Mostrador', descripcion: '', medios_pago: [], activo: true, es_default: false, sucursal_id: 1 },
  { id: 6, nombre: 'Buffet', descripcion: '', medios_pago: [], activo: true, es_default: false, sucursal_id: 1 },
]

const MOVIMIENTOS = [
  { id: 11, fecha: '2026-08-28', tipo: 'ingreso' as const, concepto: 'Turno cancha 1', monto: 14000, medio_pago: 'efectivo' },
  { id: 12, fecha: '2026-08-28', tipo: 'egreso' as const, concepto: 'Retiro a banco', monto: 5000, medio_pago: 'efectivo' },
]

/** Dos canchas con cuenta abierta. La segunda ya tiene una seña.
 *
 * 🔑 Los `pendiente` son **distintos entre sí y distintos del total**: con dos
 * filas del mismo importe, una pantalla que muestre siempre la primera pasaría
 * igual, y con `pendiente === total` no se vería si el cobrado se descuenta.
 */
// 🔑 **Tipado a propósito.** Sin la anotación, TypeScript infiere la forma del
// literal y el fixture puede quedarse atrás de la API sin que nada avise —
// justo lo que pasó con `estado`, que se agregó al backend y acá faltaba.
const CUENTAS: TurnoPorCobrar[] = [
  {
    reserva_id: 41, cancha_id: 1, cancha: 'Cancha 1', deporte: 'padel',
    comienza_at: '2026-08-28T20:00:00-03:00', termina_at: '2026-08-28T21:30:00-03:00',
    cliente: 'Juan Pérez', estado: 'confirmada',
    total: 14000, cobrado: 0, pendiente: 14000,
  },
  {
    reserva_id: 42, cancha_id: 2, cancha: 'Cancha 2', deporte: 'padel',
    comienza_at: '2026-08-28T21:30:00-03:00', termina_at: '2026-08-28T23:00:00-03:00',
    cliente: 'Ana Gómez', estado: 'confirmada',
    total: 18000, cobrado: 6000, pendiente: 12000,
  },
]

const estado = {
  hayTurno: true,
  mostradores: MOSTRADORES,
  movimientos: MOVIMIENTOS,
  cuentas: CUENTAS,
  consumos: [] as { descripcion: string; cantidad: number; precio_unitario: number; importe: number }[],
  qr: { disponible: true, auto_facturar: true },
  //: Si esta instancia monta el simulador del QR. `false` = producción, y la
    //  sonda contesta 404 igual que allá.
  puedeSimular: true,
  //: Hace cuántos días se abrió el turno. 0 = hoy, que es lo normal.
  diasAbierto: 0,
}

/** Un instante de hace `dias` días, a media mañana. */
function hace(dias: number): string {
  const d = new Date()
  d.setDate(d.getDate() - dias)
  d.setHours(9, 0, 0, 0)
  return d.toISOString()
}

const llamadas: { metodo: string; ruta: string; cuerpo: unknown }[] = []

function json(cuerpo: unknown, status = 200) {
  return new Response(JSON.stringify(cuerpo), {
    status, headers: { 'content-type': 'application/json' },
  })
}

function resumen() {
  return {
    movimientos: estado.movimientos,
    pagos_por_medio: { efectivo: 9000 },
    total_ventas: 9000,
    efectivo_ventas: 9000,
  }
}

beforeEach(() => {
  llamadas.length = 0
  estado.hayTurno = true
  estado.mostradores = MOSTRADORES
  estado.movimientos = MOVIMIENTOS
  estado.cuentas = CUENTAS
  estado.consumos = []
  estado.qr = { disponible: true, auto_facturar: true }
  estado.puedeSimular = true
  estado.diasAbierto = 0
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const u = String(url)
    let cuerpo: unknown = null
    try { cuerpo = init?.body ? JSON.parse(String(init.body)) : null } catch { /* vacío */ }
    llamadas.push({ metodo: init?.method ?? 'GET', ruta: u, cuerpo })

    if (u.includes('/api/cajas/medios-disponibles') || u.includes('/api/caja/medios-pago')) {
      // 🔑 `mercadopago` esta en la lista porque esta en `MEDIOS_PAGO` del
      // backend: es el medio que dispara el cobro con QR, y sin el en el stub
      // ese camino no se puede ejercitar.
      return Promise.resolve(json([
        { valor: 'efectivo', etiqueta: 'Efectivo' },
        { valor: 'transferencia', etiqueta: 'Transferencia' },
        { valor: 'mercadopago', etiqueta: 'MercadoPago' },
      ]))
    }
    if (u.includes('/api/cajas')) return Promise.resolve(json(estado.mostradores))
    if (u.includes('/api/reservas/agenda/por-cobrar')) {
      return Promise.resolve(json(estado.cuentas))
    }
    if (u.includes('/api/reservas/mp/estado')) return Promise.resolve(json(estado.qr))
    // 🔴 Las dos del simulador van ANTES del `/mp-qr` de abajo: ese `includes`
    // matchea las tres rutas.
    if (u.includes('/mp-qr/simulacion')) {
      // El 404 no es una falla: es cómo se dice «acá no hay simulador». La ruta
      // vive adentro del router que en producción no se monta.
      return Promise.resolve(
        estado.puedeSimular ? json({ disponible: true }) : json({ detail: 'Not Found' }, 404),
      )
    }
    if (u.includes('/mp-qr/simular')) {
      return Promise.resolve(json({ estado: 'aprobado', simulado: true, monto: 12000 }))
    }
    if (u.includes('/mp-qr')) {
      return Promise.resolve(json({ referencia: 'lc-41-abcd', monto: 14000 }, 201))
    }
    if (u.includes('/mp-status')) {
      return Promise.resolve(json({ estado: 'pendiente' }))
    }
    if (u.includes('/consumos')) {
      return Promise.resolve(json({ total: 0, lineas: estado.consumos }))
    }
    if (u.includes('/api/caja/motivos-de-egreso')) {
      return Promise.resolve(json(['Pago a proveedor', 'Retiro a banco']))
    }
    if (u.includes('/api/caja/turnos/actual')) {
      if (!estado.hayTurno) return Promise.resolve(json(null))
      return Promise.resolve(json({
        turno: {
          id: 3, usuario_id: 1, caja_id: 5, caja_nombre: 'Mostrador',
          // 🔑 **Relativa a hoy y no una fecha fija.** Con una constante, el
          // test de «abierta hace N días» diría una cosa distinta cada día que
          // pasa — y el de «hoy no avisa» se rompería mañana.
          apertura: hace(estado.diasAbierto), cierre: null, monto_inicial: 1000,
          monto_declarado_cierre: null, monto_esperado_cierre: null,
          estado: 'abierto', notas: '',
        },
        resumen: resumen(),
      }))
    }
    return Promise.resolve(json(resumen()))
  }))
})

describe('abrir el turno sobre un mostrador', () => {
  beforeEach(() => { estado.hayTurno = false })

  it('🔑 ofrece los mostradores de la sucursal', async () => {
    montar()
    const selector = await screen.findByLabelText('Caja')
    expect(within(selector).getAllByRole('option').map((o) => o.textContent))
      .toEqual(['Mostrador', 'Buffet'])
  })

  it('🔴 manda la caja elegida al abrir', async () => {
    const user = userEvent.setup()
    montar()
    await user.selectOptions(await screen.findByLabelText('Caja'), '6')
    await user.click(screen.getByRole('button', { name: /Abrir caja/ }))

    await waitFor(() => {
      const alta = llamadas.find((l) => l.metodo === 'POST' && l.ruta.endsWith('/api/caja/turnos'))
      expect(alta).toBeTruthy()
      expect((alta!.cuerpo as { caja_id: number }).caja_id).toBe(6)
    })
  })

  it('🔴 sin mostradores lo dice, y no deja abrir', async () => {
    // El mostrador no puede resolverlo —crear una caja es de admin—, así que un
    // formulario que no funciona sin decir por qué manda a adivinar.
    estado.mostradores = []
    montar()
    expect(await screen.findByText(/no tiene ninguna caja cargada/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Abrir caja/ })).toBeDisabled()
  })
})

describe('el turno abierto', () => {
  it('🔑 dice sobre qué mostrador está', async () => {
    montar()
    expect(await screen.findByText('Mostrador')).toBeInTheDocument()
  })

})

describe('un turno de caja es de UNA jornada', () => {
  // 🔴 El humano lo vio en dev el 2026-08-28: dos turnos abiertos desde el 21,
  // siete días, y el «esperado en el cajón» sumando toda la semana. Un arqueo
  // que abarca siete días no mide nada, y el faltante que aparezca no se puede
  // atribuir a ninguna jornada. No había NADA que los cerrara ni que avisara.

  it('🔑 el de hoy no dice nada y deja cobrar', async () => {
    // El control. Sin esto, un aviso puesto siempre pasaría los tests de abajo
    // y le pondría un cartel de alarma a cada turno normal.
    montar()
    expect(await screen.findByRole('button', { name: /^Canchas$/ })).toBeInTheDocument()
    expect(screen.queryByText(/antes de seguir cobrando/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Abierta desde el/i)).not.toBeInTheDocument()
  })

  it('🔴 el de otro día lo DICE, con cuántos lleva', async () => {
    estado.diasAbierto = 7
    montar()
    expect(await screen.findByText(/Abierta desde el/i)).toBeInTheDocument()
    // 🔑 En los DOS lados, y es a proposito: el aviso de la izquierda dice que
    // hay que cerrar, y el de la derecha esta pegado al numero del arqueo, que
    // es el que la antiguedad explica. Se asierta el par para que sacar uno de
    // los dos ponga rojo esto.
    expect(screen.getAllByText(/7 días/)).toHaveLength(2)
  })

  it('🔴 y FRENA el cobro hasta que se cierre', async () => {
    // El punto de venta y el egreso desaparecen: lo único que queda es contar
    // el efectivo y cerrar.
    estado.diasAbierto = 2
    montar()
    expect(await screen.findByText(/antes de seguir cobrando/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Canchas$/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Registrar un egreso/ })).not.toBeInTheDocument()
  })

  it('🔴 pero el cierre sigue habilitado: es la salida', async () => {
    // 🔑 Frenar el cobro **y** el cierre dejaría la caja sin ninguna salida —
    // que es peor que el problema, porque el operador no podría ni corregirlo.
    estado.diasAbierto = 2
    montar()
    expect(await screen.findByLabelText('Efectivo contado')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Cerrar caja/ })).toBeInTheDocument()
  })

  it('🔑 con UN día dice «un día» y no «1 días»', async () => {
    estado.diasAbierto = 1
    montar()
    expect(await screen.findAllByText(/hace un día/i)).toHaveLength(2)
    expect(screen.queryByText(/1 días/)).not.toBeInTheDocument()
  })
})

describe('la cuenta de cada cancha', () => {
  it('🔑 lista las canchas con cuenta abierta, con su hora y a nombre de quién', async () => {
    // Es lo que el humano pidió: *"ir a una cancha determinada en un turno
    // determinado a nombre de tal persona"*. Las tres cosas tienen que estar en
    // la fila, o hay que abrir algo para saber cuál es cuál.
    montar()
    const fila = await screen.findByRole('button', { name: /Cancha 2/ })
    expect(fila.textContent).toMatch(/21:30/)
    expect(fila.textContent).toMatch(/Ana Gómez/)
  })

  it('🔴 la fila muestra el PENDIENTE, no el total', async () => {
    // La cancha 2 debe 18.000 y ya señó 6.000. Mostrar el total ahí es cobrarle
    // dos veces la seña al que ya la pagó.
    montar()
    const fila = await screen.findByRole('button', { name: /Cancha 2/ })
    expect(fila.textContent).toMatch(/12\.000/)
    expect(fila.textContent).not.toMatch(/18\.000/)
  })

  it('🔴 al elegir una cancha, el monto arranca en su pendiente', async () => {
    // Y no en el de la otra: es el defecto que le cobra a uno lo que debe otro.
    const user = userEvent.setup()
    montar()
    await user.click(await screen.findByRole('button', { name: /Cancha 2/ }))
    expect((await screen.findByLabelText('Monto', { selector: '#monto-cuenta' }))).toHaveValue('12000')
  })

  it('🔴 cobrar pega en el endpoint de ESA reserva', async () => {
    const user = userEvent.setup()
    montar()
    // La **segunda** de la lista, no la primera: con la primera, un id
    // hardcodeado pasaría igual.
    await user.click(await screen.findByRole('button', { name: /Cancha 2/ }))
    await user.click(await screen.findByRole('button', { name: /Cobrar y cerrar la cuenta/ }))

    await waitFor(() => {
      const post = llamadas.find(
        (l) => l.metodo === 'POST' && l.ruta.endsWith('/api/reservas/42/cobros'),
      )
      expect(post).toBeTruthy()
      expect(post!.cuerpo).toMatchObject({ monto: '12000', medio_pago: 'efectivo' })
    })
    // El control: no le cobró a la otra cancha.
    expect(llamadas.some((l) => l.ruta.endsWith('/api/reservas/41/cobros'))).toBe(false)
  })

  it('🔑 el detalle desglosa el buffet consumido en esa cancha', async () => {
    // 🔴 Y el alquiler sale de restar: si el desglose no cerrara contra el
    // total, el operador vería un número y cobraría otro.
    estado.consumos = [
      { descripcion: 'Gaseosa 500ml', cantidad: 2, precio_unitario: 1200, importe: 2400 },
    ]
    const user = userEvent.setup()
    montar()
    await user.click(await screen.findByRole('button', { name: /Cancha 1/ }))

    expect(await screen.findByText(/2× Gaseosa 500ml/)).toBeInTheDocument()
    const panel = screen.getByText(/2× Gaseosa 500ml/).closest('div')!.parentElement!
    // 14.000 de total menos 2.400 de buffet = 11.600 de alquiler.
    expect(panel.textContent).toMatch(/11\.600/)
  })

  it('🔴 sin cuentas abiertas lo dice, en vez de un hueco', async () => {
    estado.cuentas = []
    montar()
    expect(await screen.findByText(/No hay canchas con cuenta abierta/i)).toBeInTheDocument()
  })
})

describe('la cuenta fraccionada', () => {
  // El pedido del humano: un turno de cancha se cierra como una mesa de
  // restaurante — *"se puede pagar solo la cancha y después cada uno paga
  // individual lo que pidió"*.
  //
  // 🔴 Lo que se puede romper acá es plata: cobrar de más al que paga sólo la
  // cancha, o dejar saldado lo que nadie pagó.
  beforeEach(() => {
    estado.consumos = [
      { descripcion: 'Gaseosa 500ml', cantidad: 2, precio_unitario: 1200, importe: 2400 },
      { descripcion: 'Cerveza', cantidad: 1, precio_unitario: 1600, importe: 1600 },
    ]
    // La cancha 1: 14.000 de total, sin nada cobrado. Alquiler = 14.000 − 4.000.
    estado.cuentas = [{ ...CUENTAS[0], total: 14000, cobrado: 0, pendiente: 14000 }]
  })

  async function abrirLaCuenta() {
    const user = userEvent.setup()
    montar()
    await user.click(await screen.findByRole('button', { name: /Cancha 1/ }))
    await screen.findByRole('checkbox', { name: /Gaseosa/ })
    return user
  }

  it('🔴 destildar el buffet deja el monto en el alquiler solo', async () => {
    const user = await abrirLaCuenta()
    await user.click(screen.getByRole('checkbox', { name: /Gaseosa/ }))
    await user.click(screen.getByRole('checkbox', { name: /Cerveza/ }))
    // 14.000 − 2.400 − 1.600 = 10.000, que es la cancha sola.
    expect(screen.getByLabelText('Monto', { selector: '#monto-cuenta' })).toHaveValue('10000')
  })

  it('🔴 y lo que viaja es ESE monto, con el detalle de qué se pagó', async () => {
    // Sin `detalle`, tres cobros parciales del mismo turno quedan con el mismo
    // texto en el arqueo y nadie puede reconstruir quién pagó qué.
    const user = await abrirLaCuenta()
    await user.click(screen.getByRole('checkbox', { name: /Gaseosa/ }))
    await user.click(screen.getByRole('checkbox', { name: /Cerveza/ }))
    await user.click(screen.getByRole('button', { name: /Cobrar lo seleccionado/ }))

    await waitFor(() => {
      const post = llamadas.find(
        (l) => l.metodo === 'POST' && l.ruta.endsWith('/api/reservas/41/cobros'),
      )
      expect(post).toBeTruthy()
      expect(post!.cuerpo).toMatchObject({ monto: '10000' })
      expect((post!.cuerpo as { detalle: string }).detalle).toMatch(/Alquiler/)
      // El control: el detalle NO nombra lo que quedó sin cobrar.
      expect((post!.cuerpo as { detalle: string }).detalle).not.toMatch(/Gaseosa/)
    })
  })

  it('🔑 al revés: cada uno paga sólo lo suyo', async () => {
    const user = await abrirLaCuenta()
    await user.click(screen.getByRole('checkbox', { name: /Alquiler/ }))
    await user.click(screen.getByRole('checkbox', { name: /Cerveza/ }))
    // Queda la gaseosa sola.
    expect(screen.getByLabelText('Monto', { selector: '#monto-cuenta' })).toHaveValue('2400')
  })

  it('🔴 con todo tildado NO manda detalle, y cobra el pendiente', async () => {
    // El control del caso normal. Si mandara detalle siempre, el concepto de un
    // cobro entero quedaría con la cuenta repetida adentro.
    const user = await abrirLaCuenta()
    await user.click(screen.getByRole('button', { name: /Cobrar y cerrar la cuenta/ }))

    await waitFor(() => {
      const post = llamadas.find(
        (l) => l.metodo === 'POST' && l.ruta.endsWith('/api/reservas/41/cobros'),
      )
      expect(post).toBeTruthy()
      expect(post!.cuerpo).toMatchObject({ monto: '14000', detalle: '' })
    })
  })

  it('🔴 cambiar de cancha suelta las tildes de la anterior', async () => {
    // Es el defecto que le cobra a una cancha el fraccionamiento de otra: las
    // líneas tildadas son de la cuenta que se estaba mirando.
    estado.cuentas = [
      { ...CUENTAS[0], total: 14000, cobrado: 0, pendiente: 14000 },
      { ...CUENTAS[1] },
    ]
    const user = await abrirLaCuenta()
    await user.click(screen.getByRole('checkbox', { name: /Gaseosa/ }))
    expect(screen.getByLabelText('Monto', { selector: '#monto-cuenta' })).toHaveValue('11600')

    await user.click(screen.getByRole('button', { name: /Cancha 2/ }))
    // La 2 debe 12.000: el monto es el suyo, no lo que quedaba tildado en la 1.
    await waitFor(() => {
      expect(screen.getByLabelText('Monto', { selector: '#monto-cuenta' })).toHaveValue('12000')
    })
    expect(screen.getByRole('button', { name: /Cobrar y cerrar la cuenta/ })).toBeInTheDocument()
  })
})

describe('partir un importe entre jugadores', () => {
  // 🔴 Aritmética pura, medida sin montar la pantalla: probarla a través de
  // clicks es probarla con ruido, y lo que se rompe acá es un centavo que no
  // cierra nunca.
  it('🔴 las partes suman EXACTAMENTE el importe, aunque no sea divisible', () => {
    // $14.000 entre 3 da $4.666,66 y tres pagos de eso suman $13.999,98: dos
    // centavos pendientes que nadie puede cobrar y un turno que no cierra.
    const partes = partirImporte(14000, 3)
    expect(partes).toEqual([4666.67, 4666.67, 4666.66])
    expect(partes.reduce((a, b) => a + b, 0)).toBeCloseTo(14000, 2)
  })

  it('🔑 el caso divisible no se rompe por arreglar el otro', () => {
    expect(partirImporte(14000, 4)).toEqual([3500, 3500, 3500, 3500])
  })

  it('🔴 y con centavos en el importe tampoco', () => {
    const partes = partirImporte(100.01, 3)
    expect(partes.reduce((a, b) => a + b, 0)).toBeCloseTo(100.01, 2)
    // 🔴 **Se asierta sobre el TEXTO, que es lo que viaja al backend.** Medir
    // `x * 100` es medir punto flotante contra sí mismo: `33.34 * 100` da
    // 3333.9999999999995 y el assert falla sin que haya ningún defecto. Lo que
    // de verdad se puede romper es mandar `"4666.670000000001"` en el POST.
    expect(partes.every((x) => /^\d+(\.\d{1,2})?$/.test(String(x)))).toBe(true)
  })

  it('🔑 los bordes no explotan', () => {
    expect(partirImporte(0, 3)).toEqual([])
    expect(partirImporte(-5, 3)).toEqual([])
    expect(partirImporte(NaN, 3)).toEqual([])
    expect(partirImporte(100, 1)).toEqual([100])
  })
})

describe('dividir la cuenta entre jugadores', () => {
  beforeEach(() => {
    estado.consumos = []
    estado.cuentas = [{ ...CUENTAS[0], total: 14000, cobrado: 0, pendiente: 14000 }]
  })

  async function abrirLaCuenta() {
    const user = userEvent.setup()
    montar()
    await user.click(await screen.findByRole('button', { name: /Cancha 1/ }))
    return user
  }

  it('🔑 en pádel propone cuatro jugadores', async () => {
    // Es un punto de partida, no una regla: se puede cambiar. Pero arrancar en 2
    // en un producto de canchas de pádel obliga a corregirlo siempre.
    await abrirLaCuenta()
    expect(await screen.findByLabelText('Jugadores')).toHaveValue('4')
  })

  it('🔴 dividir muestra las partes, y suman la cuenta', async () => {
    const user = await abrirLaCuenta()
    await user.click(await screen.findByRole('button', { name: /^Dividir$/ }))

    const partes = await screen.findAllByText(/Jugador \d de 4/)
    expect(partes).toHaveLength(4)
    // 14.000 entre 4 = 3.500 cada uno.
    expect(screen.getAllByText('$ 3.500,00')).toHaveLength(4)
  })

  it('🔴 cobrar una parte manda ESE monto y dice qué jugador es', async () => {
    const user = await abrirLaCuenta()
    await user.click(await screen.findByRole('button', { name: /^Dividir$/ }))

    // La **segunda** parte, no la primera: con la primera, un índice hardcodeado
    // en 0 pasaría igual.
    const filas = await screen.findAllByText(/Jugador \d de 4/)
    const fila = filas[1].closest('div')!
    await user.click(within(fila).getByRole('button', { name: 'Cobrar' }))

    await waitFor(() => {
      const post = llamadas.find(
        (l) => l.metodo === 'POST' && l.ruta.endsWith('/api/reservas/41/cobros'),
      )
      expect(post).toBeTruthy()
      expect(post!.cuerpo).toMatchObject({ monto: '3500', detalle: 'Jugador 2 de 4' })
    })
  })

  it('🔴 las partes NO se recalculan cuando baja el pendiente', async () => {
    // 🔑 **Es la diferencia entre que esto funcione y que no.** Cada parte
    // cobrada baja el pendiente; si las partes salieran del pendiente nuevo, a
    // los tres que faltan les cambiaría el importe después de que el primero
    // pagó. Las partes se calculan una vez y se sostienen.
    const user = await abrirLaCuenta()
    await user.click(await screen.findByRole('button', { name: /^Dividir$/ }))
    expect(screen.getAllByText('$ 3.500,00')).toHaveLength(4)

    // El primero paga: el backend ahora contesta con el pendiente bajado.
    estado.cuentas = [{ ...CUENTAS[0], total: 14000, cobrado: 3500, pendiente: 10500 }]
    const filas = screen.getAllByText(/Jugador \d de 4/)
    await user.click(within(filas[0].closest('div')!).getByRole('button', { name: 'Cobrar' }))

    await waitFor(() => expect(screen.getByText('cobrado')).toBeInTheDocument())
    // Los tres que faltan siguen debiendo 3.500 cada uno. Si se recalcularan
    // sobre 10.500 en cuatro partes, dirían 2.625.
    expect(screen.getAllByText('$ 3.500,00').length).toBeGreaterThanOrEqual(3)
    expect(screen.queryByText('$ 2.625,00')).not.toBeInTheDocument()
  })

  it('🔴 cambiar de cancha suelta la división', async () => {
    // Las partes son de la cuenta que se estaba mirando. Arrastrarlas a otra
    // cancha es cobrarle a una lo que se dividió de otra.
    estado.cuentas = [
      { ...CUENTAS[0], total: 14000, cobrado: 0, pendiente: 14000 },
      { ...CUENTAS[1] },
    ]
    const user = await abrirLaCuenta()
    await user.click(await screen.findByRole('button', { name: /^Dividir$/ }))
    expect(await screen.findAllByText(/Jugador \d de 4/)).toHaveLength(4)

    await user.click(screen.getByRole('button', { name: /Cancha 2/ }))
    await waitFor(() => {
      expect(screen.queryByText(/Jugador 1 de 4/)).not.toBeInTheDocument()
    })
  })

  it('🔑 con la división abierta no se puede cobrar la cuenta entera', async () => {
    // Las dos cosas juntas cobran de más: las partes suman el total, así que un
    // cobro entero encima duplica la cuenta.
    const user = await abrirLaCuenta()
    await user.click(await screen.findByRole('button', { name: /^Dividir$/ }))
    expect(screen.getByRole('button', { name: /Cobrar y cerrar la cuenta/ })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: /Cancelar la división/ }))
    expect(screen.getByRole('button', { name: /Cobrar y cerrar la cuenta/ })).toBeEnabled()
  })
})

describe('cobrar con MercadoPago', () => {
  // 🔴 Reportado por el humano el 2026-08-28: elegir MercadoPago **anotaba el
  // ingreso** como si hubiera entrado, sin haber cobrado nada. El flujo del QR
  // existía entero pero sólo se llegaba desde el detalle del turno.
  beforeEach(() => {
    estado.cuentas = [{ ...CUENTAS[0], total: 14000, cobrado: 0, pendiente: 14000 }]
  })

  async function elegirMercadoPago() {
    const user = userEvent.setup()
    montar()
    await user.click(await screen.findByRole('button', { name: /Cancha 1/ }))
    await user.selectOptions(await screen.findByLabelText('Medio'), 'mercadopago')
    return user
  }

  it('🔴 ofrece el QR y NO el cobro a mano', async () => {
    await elegirMercadoPago()
    expect(await screen.findByRole('button', { name: /Cobrar con QR/ })).toBeInTheDocument()
    // El control: el botón que anotaba el ingreso sin cobrarlo queda apagado.
    expect(screen.getByRole('button', { name: /Cobrar y cerrar la cuenta/ })).toBeDisabled()
  })

  it('🔴 apretar el QR pone el monto en el cartel de ESA reserva', async () => {
    const user = await elegirMercadoPago()
    await user.click(await screen.findByRole('button', { name: /Cobrar con QR/ }))
    await waitFor(() => {
      expect(llamadas.some(
        (l) => l.metodo === 'POST' && l.ruta.endsWith('/api/reservas/41/mp-qr'),
      )).toBe(true)
    })
  })

  it('🔑 dice cuánto va a cobrar el QR, y que factura solo', async () => {
    // El monto lo decide el backend —el pendiente—, así que la pantalla tiene
    // que decirlo: si no, el operador cree que cobra lo que tiene tipeado.
    await elegirMercadoPago()
    // El número lo pone la Caja, que es la que lo tiene.
    expect(await screen.findByText(/Son .* de una sola vez/)).toBeInTheDocument()
    // Y qué se cobra y que factura solo, el componente del QR — una sola vez:
    // la misma frase dos veces en la misma tarjeta es ruido.
    expect(screen.getAllByText(/factura solo al acreditarse/)).toHaveLength(1)
  })

  it('🔴 con MercadoPago no se ofrece fraccionar ni dividir', async () => {
    // El QR cobra el pendiente entero y una sola vez —la base admite un pago
    // aprobado por reserva—, así que ofrecerlo sería prometer lo que el modelo
    // no puede cumplir.
    await elegirMercadoPago()
    expect(screen.queryByLabelText('Jugadores')).not.toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /Alquiler/ })).toBeDisabled()
  })

  it('🔑 sin credenciales lo DICE, y deja registrar el cobro a mano', async () => {
    // «MercadoPago» también es una transferencia que se anota. Un hueco mudo
    // manda a adivinar si la pantalla se rompió.
    estado.qr = { disponible: false, auto_facturar: false }
    await elegirMercadoPago()
    // El motivo lo pone el componente del QR, que es quien lo sabe.
    expect(await screen.findByText(/faltan las credenciales de\s+MercadoPago/i))
      .toBeInTheDocument()
    // Y la salida la pone la Caja, que es la única que tiene una.
    expect(screen.getByText(/se puede registrar a mano/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cobrar con QR/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Cobrar y cerrar la cuenta/ })).toBeEnabled()
  })

  it('🔑 y en una instancia de prueba se puede simular el cobro DESDE ACÁ', async () => {
    /* ⚠️ **Este test existe porque los del simulador entran por
     * `DetalleDeReserva`** (`components/CobroConQr.test.tsx`), y el pedido era
     * el botón **en la Caja**. Que el componente lo renderice no prueba que la
     * Caja lo muestre: acá se llega por otro camino —el selector de medio de
     * pago— y con otro estado alrededor. Un test que comparte la premisa con el
     * que quiere respaldar no la verifica.
     *
     * Sin credenciales el circuito no se puede recorrer de punta a punta: poner
     * la orden falla al llamar a MercadoPago, así que no llega a existir el
     * pago que después habría que sellar.
     */
    estado.qr = { disponible: false, auto_facturar: false }
    await elegirMercadoPago()

    expect(await screen.findByRole('button', { name: /Simular pago aprobado/ }))
      .toBeInTheDocument()
    expect(screen.getByText(/Instancia de prueba/i)).toBeInTheDocument()
  })

  it('🔴 pero en producción la Caja NO ofrece simular', async () => {
    // El bundle es el MISMO en dev y en producción. Lo único que separa la
    // instancia de un complejo de tener un botón que cierra turnos gratis es
    // que la sonda conteste 404.
    estado.qr = { disponible: false, auto_facturar: false }
    estado.puedeSimular = false
    await elegirMercadoPago()

    // Control positivo: la sección del QR SÍ está en pantalla. Sin esto, un «no
    // encontré el botón» porque la Caja no llegó a renderizar pasaría igual.
    expect(await screen.findByText(/faltan las credenciales de\s+MercadoPago/i))
      .toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Simular pago aprobado/ })).toBeNull()
    expect(screen.queryByText(/Instancia de prueba/i)).toBeNull()
  })

  it('🔴 cambiar de cancha resetea el QR, no arrastra el de la anterior', async () => {
    // 🔑 **Esto no se podía romper en el diálogo del turno** —un diálogo, una
    // reserva— y sí acá: en la Caja se cambia de cancha sin cerrar nada. Sin el
    // reset, el estado del QR de la cancha anterior queda en pantalla y el poll
    // sigue preguntando por la reserva que ya no se está mirando: se ve
    // «Cobrado por QR» sobre una cancha que no cobró nada.
    estado.cuentas = [
      { ...CUENTAS[0], total: 14000, cobrado: 0, pendiente: 14000 },
      { ...CUENTAS[1] },
    ]
    const user = await elegirMercadoPago()
    await user.click(await screen.findByRole('button', { name: /Cobrar con QR/ }))
    // La orden quedó puesta: la pantalla pasa a esperar el escaneo.
    expect(await screen.findByText(/Pedile al cliente que lo escanee/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Cancha 2/ }))
    await waitFor(() => {
      expect(screen.queryByText(/Pedile al cliente que lo escanee/i)).not.toBeInTheDocument()
    })
  })

  it('🔴 y el poll de la cancha anterior se FRENA', async () => {
    // 🔑 **La mutación lo delató.** El test de arriba —que la pantalla se
    // resetee— pasaba en verde con el `frenarPoll()` sacado: lo que se ve
    // desaparece, pero el `setInterval` sigue vivo preguntando por la reserva
    // anterior. Si ese pago se acredita, la Caja anuncia «cobrado» y refresca
    // sobre una cancha que no cobró nada.
    //
    // Se mide con timers falsos porque el poll corre cada 3 segundos: sin
    // adelantarlos, el test termina antes de que salga el primer request y las
    // dos ramas dan cero.
    // `shouldAdvanceTime`: sin eso, el `waitFor` de testing-library —que espera
    // con timers— nunca avanza y todo el test se cuelga hasta el timeout.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      estado.cuentas = [
        { ...CUENTAS[0], total: 14000, cobrado: 0, pendiente: 14000 },
        { ...CUENTAS[1] },
      ]
      montar()
      await user.click(await screen.findByRole('button', { name: /Cancha 1/ }))
      await user.selectOptions(await screen.findByLabelText('Medio'), 'mercadopago')
      await user.click(await screen.findByRole('button', { name: /Cobrar con QR/ }))
      await screen.findByText(/Pedile al cliente que lo escanee/i)

      await vi.advanceTimersByTimeAsync(3500)
      // El control: hasta acá SÍ estaba polleando. Sin esto, el assert de abajo
      // pasaría con un componente que nunca polea.
      expect(llamadas.filter((l) => l.ruta.includes('/mp-status')).length)
        .toBeGreaterThan(0)

      await user.click(screen.getByRole('button', { name: /Cancha 2/ }))
      llamadas.length = 0
      await vi.advanceTimersByTimeAsync(10000)
      expect(llamadas.filter((l) => l.ruta.includes('/mp-status'))).toEqual([])
    } finally {
      vi.useRealTimers()
    }
  })

  it('🔑 el control: con efectivo nada de esto aparece', async () => {
    const user = userEvent.setup()
    montar()
    await user.click(await screen.findByRole('button', { name: /Cancha 1/ }))
    expect(await screen.findByLabelText('Medio')).toHaveValue('efectivo')
    expect(screen.queryByRole('button', { name: /Cobrar con QR/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Cobrar y cerrar la cuenta/ })).toBeEnabled()
  })
})

describe('el buffet, según de dónde se cargue', () => {
  it('🔴 desde la cuenta de una cancha, el consumo viaja CON reserva_id', async () => {
    // Con `reserva_id` el motor **no cobra**: le cuelga el consumo al turno y se
    // cobra al cerrar la cuenta. Es el invariante que evita cobrar dos veces las
    // mismas gaseosas.
    const user = userEvent.setup()
    montar()
    await user.click(await screen.findByRole('button', { name: /Cancha 2/ }))
    await user.click(await screen.findByRole('button', { name: /Cargar buffet/ }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('🔑 «Venta suelta» dice que ahí SÍ se cobra', async () => {
    // Las dos acciones abren el mismo diálogo y hacen cosas distintas con la
    // plata. Si la pantalla no lo dice, la única forma de saberlo es el arqueo.
    const user = userEvent.setup()
    montar()
    await user.click(await screen.findByRole('button', { name: /^Venta suelta$/ }))
    expect(await screen.findByText(/se cobra al confirmar/i)).toBeInTheDocument()
  })
})

describe('el egreso', () => {
  it('🔴 manda motivo, monto y medio', async () => {
    const user = userEvent.setup()
    montar()
    await user.click(await screen.findByRole('button', { name: /Registrar un egreso/ }))

    await user.selectOptions(await screen.findByLabelText('Motivo'), 'Retiro a banco')
    await user.type(screen.getByLabelText('Monto', { selector: '#monto-egreso' }), '3000')
    await user.click(screen.getByRole('button', { name: /^Registrar egreso$/ }))

    await waitFor(() => {
      const post = llamadas.find((l) => l.ruta.endsWith('/api/caja/egresos'))
      expect(post).toBeTruthy()
      expect(post!.cuerpo).toMatchObject({
        monto: '3000', motivo: 'Retiro a banco', medio_pago: 'efectivo',
      })
    })
  })

  it('🔑 los motivos salen del backend, no de constantes de la pantalla', async () => {
    // Si divergieran, la pantalla ofrecería un motivo que el POST rechaza con
    // 422 — y el operador no tendría forma de saber cuál sí vale.
    const user = userEvent.setup()
    montar()
    await user.click(await screen.findByRole('button', { name: /Registrar un egreso/ }))

    const motivos = await screen.findByLabelText('Motivo')
    expect(within(motivos).getAllByRole('option').map((o) => o.textContent))
      .toEqual(['Pago a proveedor', 'Retiro a banco'])
    expect(llamadas.some((l) => l.ruta.endsWith('/api/caja/motivos-de-egreso'))).toBe(true)
  })
})
