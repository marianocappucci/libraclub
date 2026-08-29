/**
 * El cobro con QR del mostrador, desde el detalle de un turno.
 *
 * Lo que se prueba acá es el **cableado de la pantalla**: cuándo se ofrece el
 * botón, qué se llama al apretarlo, y qué pasa mientras se espera. Las reglas
 * del cobro —el monto que va al QR, la caja, la factura— tienen sus tests del
 * lado del backend (`tests/test_cobro_qr.py`).
 *
 * 🔑 **No hay ninguna imagen de QR que buscar.** Es el cartel impreso de la
 * caja: lo único que la pantalla hace es decir cuánto está cobrando.
 *
 * ⚠️ Se stubea `fetch` y no `libra-ui/api-client`: el cliente HTTP de este
 * producto es **propio** (`lib/api.ts`, sobre `fetch` pelado), no el del kit.
 * Mockear el del kit deja pasar todas las llamadas de verdad y el test falla
 * con un "no encontré el botón" que no dice nada de eso.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DetalleDeReserva } from './DetalleDeReserva'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', name: 'Ana', role: 'staff' }, loading: false }),
}))

const llamadas: { metodo: string; ruta: string }[] = []
const config = {
  disponible: true,
  autoFacturar: false,
  //: Lo que contesta `mp-status`. Los tests lo mueven a 'aprobado'.
  resultado: 'pendiente' as string,
  //: Si esta instancia monta el simulador. `false` = producción, y la sonda
  //  contesta 404 igual que allá.
  puedeSimular: true,
  //: Con qué falla el simulador, si falla. `null` = sale bien.
  fallaAlSimular: null as { status: number; detail: string } | null,
}

function json(cuerpo: unknown) {
  return new Response(JSON.stringify(cuerpo), {
    status: 200, headers: { 'content-type': 'application/json' },
  })
}

/** Un error con la forma que devuelve FastAPI, que es la que `lib/api.ts` lee. */
function error(status: number, detail: string) {
  return new Response(JSON.stringify({ detail }), {
    status, headers: { 'content-type': 'application/json' },
  })
}

function montarRed() {
  vi.stubGlobal('fetch', vi.fn((ruta: string, init?: RequestInit) => {
    const u = String(ruta)
    llamadas.push({ metodo: init?.method ?? 'GET', ruta: u })

    if (u.includes('/mp/estado')) {
      return Promise.resolve(json({
        disponible: config.disponible, auto_facturar: config.autoFacturar,
      }))
    }
    if (u.includes('/mp-status')) {
      return Promise.resolve(json({
        estado: config.resultado,
        payment_id: config.resultado === 'aprobado' ? '112233' : null,
        factura_id: null,
      }))
    }
    // 🔴 Estas dos van ANTES del `/mp-qr` de abajo: ese `includes` matchea las
    // tres rutas, y si quedaran después el simulador contestaría un QrPuesto.
    if (u.includes('/mp-qr/simulacion')) {
      // El 404 no es un error del servidor: es cómo se dice "acá no hay
      // simulador". La ruta vive adentro del router que no se monta.
      return config.puedeSimular
        ? Promise.resolve(json({ disponible: true }))
        : Promise.resolve(error(404, 'Not Found'))
    }
    if (u.includes('/mp-qr/simular')) {
      return config.fallaAlSimular
        ? Promise.resolve(error(config.fallaAlSimular.status, config.fallaAlSimular.detail))
        : Promise.resolve(json({ estado: 'aprobado', simulado: true, monto: 14000 }))
    }
    if (u.includes('/mp-qr')) {
      return Promise.resolve(json({ referencia: 'lc-5-abc123', monto: 14000 }))
    }
    if (u.includes('/consumos')) return Promise.resolve(json({ total: 0, lineas: [] }))
    if (u.includes('/productos')) return Promise.resolve(json([]))
    return Promise.resolve(json(null))
  }))
}

const CANCHA = {
  id: 1, sucursal_id: 1, nombre: 'Cancha 1', deporte: 'padel',
  duracion_turno_min: 90, techada: true, iluminacion: true, superficie: null,
  orden: 1, activa: true, observaciones: null,
}

function turno(estado: string) {
  return {
    comienza_at: '2026-08-20T18:00:00-03:00',
    termina_at: '2026-08-20T19:30:00-03:00',
    libre: false,
    precio: '14000.00',
    reserva_id: 5,
    estado,
    cliente: 'Ana Gomez',
    motivo: null, cobrado: false,
  }
}

function montar(estado = 'confirmada', onCambiada = vi.fn()) {
  return render(
    <DetalleDeReserva
      abierto cancha={CANCHA} turno={turno(estado)}
      onCerrar={vi.fn()} onCambiada={onCambiada}
    />,
  )
}

beforeEach(() => {
  llamadas.length = 0
  config.disponible = true
  config.autoFacturar = false
  config.resultado = 'pendiente'
  config.puedeSimular = true
  config.fallaAlSimular = null
  montarRed()
})

describe('cuándo se ofrece el cobro con QR', () => {
  it('con la instancia configurada y el turno confirmado', async () => {
    montar('confirmada')
    expect(await screen.findByRole('button', { name: /Cobrar con QR/ })).toBeInTheDocument()
  })

  it('también sobre un turno jugado, que es cuando el grupo suele pagar', async () => {
    montar('jugada')
    expect(await screen.findByRole('button', { name: /Cobrar con QR/ })).toBeInTheDocument()
  })

  it('no sobre un turno cancelado', async () => {
    montar('cancelada')
    // Control positivo del selector: el diálogo SÍ está abierto. Sin esto, un
    // "no encontré nada" porque el componente no renderizó pasaría igual.
    expect(await screen.findByText(/Cancha 1/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cobrar con QR/ })).toBeNull()
  })

  it('🔴 sin MercadoPago configurado no hay botón, y SE DICE POR QUÉ', async () => {
    // 🔑 **Este test asertaba sólo la ausencia del botón, y por eso el defecto
    // le pasaba por al lado.** Hasta el 2026-08-28 el componente hacía
    // `return null` en este caso: el detalle del turno no mostraba **nada** —ni
    // el botón ni el motivo— y el test, que sólo pedía que el botón no
    // estuviera, seguía en verde. Es el cero esperado sin su positivo.
    //
    // Lo reportó el humano: *"pongo pagar con MercadoPago y no me dirige a
    // ningún lado"*. Tenía razón literal — la pantalla callaba.
    config.disponible = false
    montar('confirmada')
    expect(await screen.findByText(/Cancha 1/)).toBeInTheDocument()
    await waitFor(() =>
      expect(llamadas.some((l) => l.ruta.includes('/mp/estado'))).toBe(true),
    )
    expect(screen.queryByRole('button', { name: /Cobrar con QR/ })).toBeNull()
    // Lo que faltaba: el motivo, y dónde se arregla.
    expect(await screen.findByText(/faltan las credenciales de\s+MercadoPago/i))
      .toBeInTheDocument()
    expect(screen.getByText(/Configuración . Mercado Pago/i)).toBeInTheDocument()
  })

  it('🔑 y sobre un turno cancelado NO dice nada, ni siquiera eso', async () => {
    // El control del control. Sin esto, el arreglo de arriba se puede hacer
    // poniendo el cartel siempre — y entonces cada turno cancelado del día
    // llevaría un aviso sobre un cobro que nunca va a existir.
    config.disponible = false
    montar('cancelada')
    expect(await screen.findByText(/Cancha 1/)).toBeInTheDocument()
    expect(screen.queryByText(/faltan las credenciales/i)).toBeNull()
  })
})

describe('el cobro', () => {
  it('pone el monto en el QR y avisa que el cliente lo escanee', async () => {
    const user = userEvent.setup()
    montar()

    await user.click(await screen.findByRole('button', { name: /Cobrar con QR/ }))

    await waitFor(() => {
      expect(llamadas.some((l) => l.metodo === 'POST' && l.ruta === '/api/reservas/5/mp-qr'))
        .toBe(true)
    })
    expect(await screen.findByText(/Pedile al cliente que lo escanee/)).toBeInTheDocument()
  })

  it('al acreditarse avisa que se cobró y refresca la agenda', async () => {
    const user = userEvent.setup()
    const onCambiada = vi.fn()
    montar('confirmada', onCambiada)

    await user.click(await screen.findByRole('button', { name: /Cobrar con QR/ }))
    await screen.findByText(/Pedile al cliente que lo escanee/)

    config.resultado = 'aprobado'

    expect(await screen.findByText(/Cobrado por QR/, {}, { timeout: 8000 }))
      .toBeInTheDocument()
    expect(onCambiada).toHaveBeenCalled()
  }, 12000)

  it('cancelar baja el monto del QR', async () => {
    // 🔴 Una orden que queda puesta le cobra ese monto al próximo que escanee.
    const user = userEvent.setup()
    montar()

    await user.click(await screen.findByRole('button', { name: /Cobrar con QR/ }))
    await screen.findByText(/Pedile al cliente que lo escanee/)
    await user.click(screen.getByRole('button', { name: /Cancelar el cobro por QR/ }))

    await waitFor(() => {
      expect(llamadas.some((l) => l.metodo === 'DELETE' && l.ruta === '/api/reservas/5/mp-qr'))
        .toBe(true)
    })
  })

  it('avisa que la factura sale sola sólo si la instancia lo tiene prendido', async () => {
    config.autoFacturar = true
    const { unmount } = montar()
    expect(await screen.findByText(/factura solo al acreditarse/)).toBeInTheDocument()
    unmount()

    // Control negativo: con la automática apagada, la promesa no aparece. Sin
    // esto, un texto fijo pasaría el test de arriba.
    config.autoFacturar = false
    montar()
    await screen.findByRole('button', { name: /Cobrar con QR/ })
    expect(screen.queryByText(/factura solo al acreditarse/)).toBeNull()
  })
})

describe('la campanita del cobro acreditado', () => {
  // 📋 Es lo que hace [[contalibra]], que el humano probó y da por bueno: en un
  // mostrador el operador **escucha** que el pago entró, sin tener que mirar la
  // pantalla mientras atiende al que sigue.
  //
  // 🔴 jsdom no trae `AudioContext`, así que sin este doble el código toma la
  // rama del `catch` y no suena nada — y un test que no lo stubea pasa en verde
  // sobre un componente que perdió la campanita.
  let creados: number
  let osciladores: number

  function stubearAudio() {
    creados = 0
    osciladores = 0
    class AudioFalso {
      state = 'running'
      currentTime = 0
      destination = {}
      constructor() { creados += 1 }
      resume() {}
      createOscillator() {
        osciladores += 1
        return {
          type: '', frequency: { value: 0 },
          connect: () => ({ connect: () => {} }),
          start: () => {}, stop: () => {},
        }
      }
      createGain() {
        return {
          gain: {
            setValueAtTime: () => {},
            exponentialRampToValueAtTime: () => {},
          },
          connect: () => ({ connect: () => {} }),
        }
      }
    }
    vi.stubGlobal('AudioContext', AudioFalso)
  }

  it('🔴 el AudioContext se abre con el CLICK, no al acreditarse', async () => {
    // 🔑 **Es el detalle que hace que no suene nunca, y en silencio.** Los
    // navegadores bloquean el audio que no nace de un gesto del usuario, y la
    // acreditación llega desde un `setInterval` — que no cuenta como gesto.
    // Crearlo en el lugar obvio, cuando suena, es exactamente lo que lo rompe.
    stubearAudio()
    montar('confirmada')
    const boton = await screen.findByRole('button', { name: /Cobrar con QR/ })
    expect(creados).toBe(0)   // el control: antes del click no se abrió nada

    await userEvent.click(boton)
    await waitFor(() => expect(creados).toBe(1))
    // Y todavía no sonó: sólo se abrió el contexto.
    expect(osciladores).toBe(0)
  })

  it('🔴 al acreditarse suena, con sus dos notas', async () => {
    stubearAudio()
    montar('confirmada')
    await userEvent.click(await screen.findByRole('button', { name: /Cobrar con QR/ }))
    await screen.findByText(/Pedile al cliente que lo escanee/i)

    config.resultado = 'aprobado'
    await screen.findByText(/Cobrado por QR/i, {}, { timeout: 5000 })
    // Dos osciladores: mi6 y la6. Uno solo sería media campanita.
    expect(osciladores).toBe(2)
  })

  it('🔑 y si el navegador no tiene audio, el cobro igual funciona', async () => {
    // El control de que la campanita es un adorno del cobro y no una condición:
    // sin `AudioContext` ---jsdom puro, o un navegador viejo--- el circuito
    // tiene que llegar a «Cobrado» lo mismo.
    vi.stubGlobal('AudioContext', undefined)
    montar('confirmada')
    await userEvent.click(await screen.findByRole('button', { name: /Cobrar con QR/ }))
    config.resultado = 'aprobado'
    expect(await screen.findByText(/Cobrado por QR/i, {}, { timeout: 5000 }))
      .toBeInTheDocument()
  })
})

describe('el simulador, sin credenciales de MercadoPago', () => {
  // Existe porque sin credenciales NO SE PUEDE probar el circuito: poner la
  // orden falla al llamar a MercadoPago, así que no llega a existir el pago que
  // después habría que sellar. El humano no tiene credenciales todavía —el
  // producto no se vendió— y usar las suyas de Contalibra mandaría pagos de
  // prueba a su cuenta real.

  it('en una instancia de prueba se ofrece simular, y se dice que lo es', async () => {
    config.disponible = false
    montar('confirmada')

    expect(await screen.findByRole('button', { name: /Simular pago aprobado/ }))
      .toBeInTheDocument()
    // La misma redacción que el botón del portal, que es el que el humano usó.
    expect(screen.getByText(/Instancia de prueba/i)).toBeInTheDocument()
    // Y el motivo sigue estando: el botón no reemplaza al cartel, lo acompaña.
    expect(screen.getByText(/faltan las credenciales de\s+MercadoPago/i))
      .toBeInTheDocument()
  })

  it('🔴 en producción NO se ofrece, y quien lo decide es el servidor', async () => {
    // El test que más importa de este archivo. El bundle es el MISMO en dev y
    // en producción: lo único que separa una instancia de un complejo de tener
    // un botón que cierra turnos gratis es que la sonda conteste 404.
    config.disponible = false
    config.puedeSimular = false
    montar('confirmada')

    // Control positivo: la sección SÍ renderizó y la sonda SÍ se preguntó. Sin
    // esto, un "no encontré el botón" porque el componente no llegó a montarse
    // pasaría igual —y el test estaría midiendo la nada—.
    expect(await screen.findByText(/faltan las credenciales de\s+MercadoPago/i))
      .toBeInTheDocument()
    await waitFor(() =>
      expect(llamadas.some((l) => l.ruta.includes('/mp-qr/simulacion'))).toBe(true),
    )
    expect(screen.queryByRole('button', { name: /Simular pago aprobado/ })).toBeNull()
    expect(screen.queryByText(/Instancia de prueba/i)).toBeNull()
  })

  it('🔑 con las credenciales cargadas ni siquiera se pregunta', async () => {
    // Con MercadoPago configurado el botón no se ofrece nunca, así que sondear
    // sería un 404 por cada turno que se abre en TODA instancia de producción.
    // La sonda está encadenada al estado justamente para no hacerlo.
    config.disponible = true
    montar('confirmada')

    expect(await screen.findByRole('button', { name: /Cobrar con QR/ }))
      .toBeInTheDocument()
    expect(llamadas.some((l) => l.ruta.includes('/mp-qr/simulacion'))).toBe(false)
  })

  it('al simular llama al MISMO endpoint del cobro y avisa que se cobró', async () => {
    const user = userEvent.setup()
    const onCambiada = vi.fn()
    config.disponible = false
    montar('confirmada', onCambiada)

    await user.click(await screen.findByRole('button', { name: /Simular pago aprobado/ }))

    await waitFor(() => {
      expect(llamadas.some((l) =>
        l.metodo === 'POST' && l.ruta === '/api/reservas/5/mp-qr/simular')).toBe(true)
    })
    // 🔴 Que el POST salga no alcanza: hasta que el aviso de cobrado se movió
    // arriba del cartel de las credenciales, apretar el botón dejaba la
    // pantalla IDÉNTICA. Es el mismo reporte que ya hizo el humano con el QR.
    expect(await screen.findByText(/Cobrado por QR/)).toBeInTheDocument()
    // Y la agenda se refresca, como cuando acredita de verdad.
    expect(onCambiada).toHaveBeenCalled()
  })

  it('si el cobro simulado falla, lo dice y no miente que cobró', async () => {
    // El 409 de "no hay caja abierta" es el mismo que devuelve el cobro real, y
    // es justamente uno de los casos que se quiere poder recorrer.
    const user = userEvent.setup()
    config.disponible = false
    config.fallaAlSimular = { status: 409, detail: 'no hay un turno de caja abierto' }
    montar('confirmada')

    await user.click(await screen.findByRole('button', { name: /Simular pago aprobado/ }))

    expect(await screen.findByText(/no hay un turno de caja abierto/)).toBeInTheDocument()
    expect(screen.queryByText(/Cobrado por QR/)).toBeNull()
  })
})
