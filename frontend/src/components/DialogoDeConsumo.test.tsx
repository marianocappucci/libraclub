import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * El diálogo de consumo, en sus dos modos.
 *
 * Nació cubriendo sólo el caso `reservaId`: cargar el consumo a la cancha **sin
 * cobrarlo**, que la pantalla de buffet no ejercitaba —ahí el diálogo se abría
 * siempre con `reservaId = null`— y por eso la mutación *"el consumo de una
 * cancha también manda medio de pago"* le sobrevivía.
 *
 * 🔑 **Y desde el 2026-08-28 cubre también el otro**, el de la venta suelta.
 * Esos tres tests estaban en `Buffet.test.tsx` y entraban por su botón
 * «Vender»; ese botón se retiró cuando la venta suelta se mudó a la Caja —*"todo
 * tiene que ir por el mismo lado"*—, así que se mudaron acá, montando el diálogo
 * directo. Borrarlos habría dejado sin cobertura el carrito, el stock a la vista
 * y el medio de pago de la venta que **sí** cobra.
 *
 * 🔴 **Y desde el 2026-09-08, el cobro por QR de esa venta suelta.** Elegir
 * «MercadoPago» anotaba un movimiento a mano, como una transferencia: el mismo
 * agujero que el detalle del turno tenía hasta el 2026-08-28. Los tests de ese
 * describe miden las dos mitades del reporte del humano —que el botón lleve al
 * QR, y que sin credenciales la pantalla **diga** por qué no— porque el bug
 * original fue justamente una pantalla que callaba.
 */

const productos = vi.fn()
const consumir = vi.fn()
const estadoDelQr = vi.fn()
const ponerEnElQr = vi.fn()
const bajarDelQr = vi.fn()
const consultarElQr = vi.fn()
const simulacionDisponible = vi.fn()
const simularElQr = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    buffet: { ...(real.buffet as object), productos, consumir },
    cobroQr: { ...(real.cobroQr as object), estado: estadoDelQr },
    cobroQrBuffet: {
      poner: ponerEnElQr,
      bajar: bajarDelQr,
      consultar: consultarElQr,
      simulacionDisponible,
      simular: simularElQr,
    },
  }
})

const { DialogoDeConsumo } = await import('./DialogoDeConsumo')

beforeEach(() => {
  productos.mockReset()
  consumir.mockReset()
  estadoDelQr.mockReset()
  ponerEnElQr.mockReset()
  bajarDelQr.mockReset()
  consultarElQr.mockReset()
  simulacionDisponible.mockReset()
  simularElQr.mockReset()
  // El default es «esta instancia puede cobrar por QR»: los tests que miden el
  // camino sin credenciales lo dicen explícitamente.
  estadoDelQr.mockResolvedValue({ disponible: true, auto_facturar: false })
  ponerEnElQr.mockResolvedValue({
    venta_id: 42, numero: 'BUF-000042', referencia: 'lc-buf-42-abc', monto: 3300,
  })
  bajarDelQr.mockResolvedValue(undefined)
  consultarElQr.mockResolvedValue({ estado: 'pendiente', payment_id: null, factura_id: null })
  simulacionDisponible.mockResolvedValue({ disponible: true })
  simularElQr.mockResolvedValue({ estado: 'aprobado', simulado: true })
  productos.mockResolvedValue([
    { item_id: 1, nombre: 'Gaseosa 500ml', precio: 1200, activo: true,
      stock: 24, stock_minimo: 6, bajo_minimo: false },
    { item_id: 2, nombre: 'Agua', precio: 900, activo: true,
      stock: 4, stock_minimo: 6, bajo_minimo: true },
  ])
  consumir.mockResolvedValue({ id: 1, numero: 'BUF-000001', total: 1200, reserva_id: 7 })
  // 🔴 **Los medios de pago vienen del backend, no de una constante.** Montado
  // directo, el diálogo no tiene quién le conteste `/api/caja/medios-pago` y su
  // selector queda vacío — con lo cual el modo que **sí** cobra viajaría sin
  // medio y el test lo leería como un cambio de comportamiento. Entrando por la
  // pantalla de Buffet esto no hacía falta: el stub estaba allá.
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(
    JSON.stringify([
      { valor: 'efectivo', etiqueta: 'Efectivo' },
      { valor: 'transferencia', etiqueta: 'Transferencia' },
      // 🔑 Va **último** a propósito: el default del selector es `medios[0]`, y
      // los tests de arriba fijan que sea «efectivo». Ponerlo primero cambiaría
      // el default y con él lo que mide todo este archivo.
      { valor: 'mercadopago', etiqueta: 'MercadoPago' },
    ]),
    { headers: { 'content-type': 'application/json' } },
  ))))
})

describe('cargar consumo a una cancha', () => {
  it('NO manda medio de pago: se cobra con el turno', async () => {
    render(
      <DialogoDeConsumo
        abierto
        sucursalId={1}
        reservaId={7}
        onCerrar={() => {}}
        onCargado={() => {}}
      />,
    )
    const dialogo = await screen.findByRole('dialog')
    await userEvent.click(within(dialogo).getByText('Gaseosa 500ml'))
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Cargar' }))

    await waitFor(() => expect(consumir).toHaveBeenCalled())
    const cuerpo = consumir.mock.calls[0][1]
    // 🔑 Si mandara medio de pago, el backend lo cobraría en el acto **y** otra
    // vez al facturar el turno. Es la diferencia entre fiar y cobrar dos veces.
    expect(cuerpo.medio_pago).toBeNull()
    expect(cuerpo.reserva_id).toBe(7)
  })

  it('no ofrece elegir cómo cobrar, y lo explica', async () => {
    render(
      <DialogoDeConsumo
        abierto
        sucursalId={1}
        reservaId={7}
        onCerrar={() => {}}
        onCargado={() => {}}
      />,
    )
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).queryByText('Cobrar con')).not.toBeInTheDocument()
    expect(within(dialogo).getByText(/se cobra y se factura junto con el turno/i))
      .toBeInTheDocument()
  })

  it('el botón dice Cargar y no Cobrar', async () => {
    render(
      <DialogoDeConsumo
        abierto
        sucursalId={1}
        reservaId={7}
        onCerrar={() => {}}
        onCargado={() => {}}
      />,
    )
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByRole('button', { name: 'Cargar' })).toBeInTheDocument()
    expect(within(dialogo).queryByRole('button', { name: 'Cobrar' })).not.toBeInTheDocument()
  })
})

describe('la venta suelta, que se cobra en el acto', () => {
  // 🔴 Estos tres entraban por el botón «Vender» de la pantalla de Buffet, que
  // se retiró: la venta suelta se hace desde la Caja. Se mudaron y no se
  // borraron porque son lo único que cubre el carrito y el cobro del modo que
  // **sí** mueve plata.
  function montar() {
    return render(
      <DialogoDeConsumo
        abierto
        sucursalId={1}
        reservaId={null}
        onCerrar={() => {}}
        onCargado={() => {}}
      />,
    )
  }

  it('el carrito suma por precio de lista y manda medio de pago', async () => {
    montar()
    const dialogo = await screen.findByRole('dialog')
    // Se espera a que los medios lleguen: el default se fija en un efecto,
    // y sin esperarlo el cobro saldría con el medio en blanco por carrera.
    await waitFor(() => expect(
      within(dialogo).getByLabelText('Cobrar con')).toHaveValue('efectivo'))
    // Dos gaseosas y un agua: 1200×2 + 900 = 3300.
    await userEvent.click(await within(dialogo).findByText('Gaseosa 500ml'))
    await userEvent.click(within(dialogo).getByLabelText('Agregar uno de Gaseosa 500ml'))
    await userEvent.click(within(dialogo).getByText('Agua'))

    expect(within(dialogo).getByText('$ 3.300,00')).toBeInTheDocument()

    await userEvent.click(within(dialogo).getByRole('button', { name: 'Cobrar' }))
    await waitFor(() => expect(consumir).toHaveBeenCalled())

    const [sucursalId, cuerpo] = consumir.mock.calls[0]
    expect(sucursalId).toBe(1)
    expect(cuerpo.lineas).toEqual([
      { item_id: 1, cantidad: '2' },
      { item_id: 2, cantidad: '1' },
    ])
    // 🔑 Venta suelta: se cobra en el acto, así que va el medio de pago. Es la
    // diferencia con el otro describe de este mismo archivo.
    expect(cuerpo.reserva_id).toBeNull()
    expect(cuerpo.medio_pago).toBe('efectivo')
  })

  it('el stock se ve al vender, no sólo en la tabla', async () => {
    montar()
    const dialogo = await screen.findByRole('dialog')
    // El encargado tiene que ver que quedan 4 antes de prometer 6.
    expect(await within(dialogo).findByText('4 en stock')).toBeInTheDocument()
  })

  it('quitar la última unidad saca la línea del carrito', async () => {
    montar()
    const dialogo = await screen.findByRole('dialog')
    await userEvent.click(await within(dialogo).findByText('Agua'))
    // El control de cantidad sólo existe si la línea está en el carrito. Se
    // asierta sobre él y no sobre el importe: `$ 900,00` aparece tres veces
    // —precio del producto, importe de la línea y total—, así que contarlo
    // haría un test que se rompe al agregar cualquier columna.
    expect(within(dialogo).getByLabelText('Quitar uno de Agua')).toBeInTheDocument()
    expect(within(dialogo).getByRole('button', { name: 'Cobrar' })).toBeEnabled()

    await userEvent.click(within(dialogo).getByLabelText('Quitar uno de Agua'))
    expect(within(dialogo).queryByLabelText('Quitar uno de Agua')).not.toBeInTheDocument()
    expect(within(dialogo).getByRole('button', { name: 'Cobrar' })).toBeDisabled()
  })
})

describe('cobrar la venta suelta con el QR de MercadoPago', () => {
  function montar(onCargado = () => {}, onCerrar = () => {}) {
    return render(
      <DialogoDeConsumo
        abierto
        sucursalId={1}
        reservaId={null}
        onCerrar={onCerrar}
        onCargado={onCargado}
      />,
    )
  }

  /** Elige MercadoPago y deja una gaseosa en el carrito. */
  async function elegirMercadoPago(dialogo: HTMLElement) {
    await waitFor(() => expect(
      within(dialogo).getByLabelText('Cobrar con')).toHaveValue('efectivo'))
    await userEvent.click(await within(dialogo).findByText('Gaseosa 500ml'))
    await userEvent.selectOptions(
      within(dialogo).getByLabelText('Cobrar con'), 'mercadopago')
  }

  it('🔴 el botón lleva al QR y NO anota un movimiento a mano', async () => {
    montar()
    const dialogo = await screen.findByRole('dialog')
    await elegirMercadoPago(dialogo)

    // Es la mitad visible del reporte del humano: el botón cambia de nombre.
    const boton = within(dialogo).getByRole('button', { name: /Cobrar con QR/i })
    expect(boton).toBeEnabled()
    expect(within(dialogo).queryByRole('button', { name: 'Cobrar' })).not.toBeInTheDocument()

    await userEvent.click(boton)
    await waitFor(() => expect(ponerEnElQr).toHaveBeenCalled())

    const [sucursalId, cuerpo] = ponerEnElQr.mock.calls[0]
    expect(sucursalId).toBe(1)
    expect(cuerpo.lineas).toEqual([{ item_id: 1, cantidad: '1' }])
    // 🔑 Y lo que NO pasa: `consumir` es el camino que descuenta stock y cobra
    // en el acto. Si se llamara igual, el QR sería decorativo y la venta
    // quedaría cobrada como si fuera efectivo.
    expect(consumir).not.toHaveBeenCalled()
  })

  it('mientras espera dice cuánto está cobrando el cartel', async () => {
    montar()
    const dialogo = await screen.findByRole('dialog')
    await elegirMercadoPago(dialogo)
    await userEvent.click(within(dialogo).getByRole('button', { name: /Cobrar con QR/i }))

    expect(await within(dialogo).findByText(/Esperando el pago/i)).toBeInTheDocument()
    // El monto lo decide el backend, y es el que la pantalla repite.
    expect(within(dialogo).getByText('$ 3.300,00')).toBeInTheDocument()
  })

  it('al acreditarse cierra la venta: avisa al llamador una sola vez', async () => {
    const cargado = vi.fn()
    consultarElQr.mockResolvedValue({
      estado: 'aprobado', payment_id: '778899', factura_id: null,
    })
    montar(cargado)
    const dialogo = await screen.findByRole('dialog')
    await elegirMercadoPago(dialogo)
    await userEvent.click(within(dialogo).getByRole('button', { name: /Cobrar con QR/i }))

    // El poll corre cada 3 segundos, así que se le da tiempo a un tick.
    await waitFor(() => expect(cargado).toHaveBeenCalledTimes(1), { timeout: 8000 })
    expect(consumir).not.toHaveBeenCalled()
  })

  it('🔴 cancelar el cobro BAJA el monto del QR', async () => {
    montar()
    const dialogo = await screen.findByRole('dialog')
    await elegirMercadoPago(dialogo)
    await userEvent.click(within(dialogo).getByRole('button', { name: /Cobrar con QR/i }))
    await within(dialogo).findByText(/Esperando el pago/i)

    await userEvent.click(
      within(dialogo).getByRole('button', { name: /Cancelar el cobro por QR/i }))
    // Sin esto el cartel sigue cobrando esa venta: el próximo que escanee paga
    // las gaseosas de otro.
    await waitFor(() => expect(bajarDelQr).toHaveBeenCalledWith(42))
  })

  it('🔴 y cerrar el diálogo mientras espera, también', async () => {
    const cerrar = vi.fn()
    montar(() => {}, cerrar)
    const dialogo = await screen.findByRole('dialog')
    await elegirMercadoPago(dialogo)
    await userEvent.click(within(dialogo).getByRole('button', { name: /Cobrar con QR/i }))
    await within(dialogo).findByText(/Esperando el pago/i)

    // Es la salida más probable del cajero que se arrepiente, y la que el
    // botón «Cancelar el cobro» no cubre. Mientras espera, la fila de botones
    // se reemplaza por el cartel, así que la salida es la ✕ del diálogo — que
    // es justamente el camino que hay que cubrir.
    await userEvent.click(within(dialogo).getByRole('button', { name: /close/i }))
    await waitFor(() => expect(bajarDelQr).toHaveBeenCalledWith(42))
    expect(cerrar).toHaveBeenCalled()
  })

  it('el pago rechazado lo dice y no cierra la venta', async () => {
    const cargado = vi.fn()
    consultarElQr.mockResolvedValue({
      estado: 'rechazado', payment_id: '778899', factura_id: null,
    })
    montar(cargado)
    const dialogo = await screen.findByRole('dialog')
    await elegirMercadoPago(dialogo)
    await userEvent.click(within(dialogo).getByRole('button', { name: /Cobrar con QR/i }))

    expect(await within(dialogo).findByText(/rechazado o cancelado/i, {}, { timeout: 8000 }))
      .toBeInTheDocument()
    expect(cargado).not.toHaveBeenCalled()
  })

  describe('sin credenciales de MercadoPago', () => {
    beforeEach(() => {
      estadoDelQr.mockResolvedValue({ disponible: false, auto_facturar: false })
    })

    it('🔴 la pantalla DICE por qué, en vez de callarse', async () => {
      // El bug del 2026-08-28 fue exactamente éste en el otro camino: un
      // `return null` dejaba la pantalla sin botón y sin motivo, y el humano lo
      // reportó como "no me dirige a ningún lado".
      montar()
      const dialogo = await screen.findByRole('dialog')
      await elegirMercadoPago(dialogo)

      expect(await within(dialogo).findByText(/faltan las credenciales de/i))
        .toBeInTheDocument()
      expect(within(dialogo).getByText(/Configuración → Mercado Pago/i)).toBeInTheDocument()
      // Y el botón no se ofrece habilitado: sólo podría fallar.
      expect(within(dialogo).getByRole('button', { name: /Cobrar con QR/i })).toBeDisabled()
    })

    it('fuera de producción ofrece simular el pago, y simula la venta entera',
      async () => {
        const cargado = vi.fn()
        montar(cargado)
        const dialogo = await screen.findByRole('dialog')
        await elegirMercadoPago(dialogo)

        const boton = await within(dialogo).findByRole(
          'button', { name: /Simular pago aprobado/i })
        await userEvent.click(boton)

        await waitFor(() => expect(simularElQr).toHaveBeenCalled())
        expect(simularElQr.mock.calls[0][1].lineas).toEqual([{ item_id: 1, cantidad: '1' }])
        await waitFor(() => expect(cargado).toHaveBeenCalled())
      })

    it('en producción no lo ofrece: la ruta del simulador no existe', async () => {
      // 🔑 Se le pregunta al servidor y no a una variable de build: el bundle es
      // el MISMO en dev y en producción. El 404 es la respuesta.
      simulacionDisponible.mockRejectedValue(new Error('404'))
      montar()
      const dialogo = await screen.findByRole('dialog')
      await elegirMercadoPago(dialogo)

      await within(dialogo).findByText(/faltan las credenciales de/i)
      expect(within(dialogo).queryByRole('button', { name: /Simular pago aprobado/i }))
        .not.toBeInTheDocument()
    })
  })

  it('con reserva no hay nada de QR: eso se cobra con el turno', async () => {
    // Control de todo el describe: si el bloque del QR se dibujara siempre,
    // los tests de arriba pasarían igual sin probar la distinción.
    render(
      <DialogoDeConsumo
        abierto
        sucursalId={1}
        reservaId={7}
        onCerrar={() => {}}
        onCargado={() => {}}
      />,
    )
    const dialogo = await screen.findByRole('dialog')
    await within(dialogo).findByText('Gaseosa 500ml')
    expect(within(dialogo).queryByRole('button', { name: /Cobrar con QR/i }))
      .not.toBeInTheDocument()
    expect(estadoDelQr).not.toHaveBeenCalled()
  })
})
