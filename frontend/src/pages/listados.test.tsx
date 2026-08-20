import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Los listados, después de pasar a `libra-ui/data-table`.
 *
 * La tabla la dibuja el kit y la prueba el kit. Lo que se fija acá es lo que
 * **decide este producto** y que la migración cambió de forma:
 *
 * - que la columna de acciones exista **sólo** si el rol puede escribir (antes
 *   era un `{puedeEscribir && <th>}`, ahora es una columna que se agrega o no);
 * - que el buscador busque sobre **lo que se ve** y no sobre el dato crudo —el
 *   caso de Tarifas, donde la columna Cancha guarda un id y muestra un nombre;
 * - que un listado vacío diga **por qué** lo está, que en Clientes son tres
 *   motivos distintos.
 */

const tarifasListar = vi.fn()
const canchasListar = vi.fn()
const clientesListar = vi.fn()

vi.mock('@/lib/api', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    tarifas: { ...(real.tarifas as object), listar: tarifasListar },
    canchas: { ...(real.canchas as object), listar: canchasListar },
    clientes: { ...(real.clientes as object), listar: clientesListar },
  }
})

const rol = { actual: 'admin' as string | undefined }

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'u', name: 'U', role: rol.actual }, loading: false }),
}))

vi.mock('@/context/SucursalContext', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    useSucursal: () => ({
      sucursales: [], actual: 1, elegir: () => {}, recargar: () => {}, cargando: false,
    }),
  }
})

const { Tarifas } = await import('./Tarifas')
const { Clientes } = await import('./Clientes')

const CANCHA = {
  id: 7, sucursal_id: 1, nombre: 'Cancha Techada', deporte: 'padel',
  duracion_turno_min: 90, techada: true, iluminacion: true, superficie: null,
  orden: 1, activa: true, observaciones: null,
}
const TARIFA = {
  id: 1, sucursal_id: 1, cancha_id: 7, nombre: 'Nocturna',
  alcance_dia: 'todos' as const, dia_semana: null, hora_desde: '18:00:00',
  hora_hasta: '23:00:00', precio: '14000.00', sena_porcentaje: 50,
  vigente_desde: null, vigente_hasta: null, prioridad: 10, activa: true,
}
const OTRA_TARIFA = { ...TARIFA, id: 2, nombre: 'Diurna', cancha_id: null, precio: '9000.00' }

const CLIENTE = {
  id: 1, nombre: 'Ana Perez', telefono: '2226-401234', email: null,
  documento: '30111222', cuit: null, activo: true, observaciones: null,
}

beforeEach(() => {
  rol.actual = 'admin'
  tarifasListar.mockReset().mockResolvedValue([TARIFA, OTRA_TARIFA])
  canchasListar.mockReset().mockResolvedValue([CANCHA])
  clientesListar.mockReset().mockResolvedValue([CLIENTE])
})

describe('tarifas', () => {
  it('muestra el nombre de la cancha, no su id', async () => {
    render(<Tarifas />)
    // Acotado a la tabla: lo que se afirma es que el nombre esta en la CELDA,
    // no en cualquier lado de la pantalla.
    //
    // Hasta el 2026-08-20 acotarlo era ademas obligatorio: "Cancha Techada"
    // aparecia tambien en el <option> del formulario de alta, que el `<dialog>`
    // nativo dejaba en el DOM aunque estuviera cerrado, y la query fallaba por
    // ambiguedad. Con el `Dialog` de shadcn el contenido cerrado se desmonta y
    // esa segunda aparicion ya no existe — ver `dialogos.test.tsx`.
    const tabla = await screen.findByRole('table')
    expect(await within(tabla).findByText('Cancha Techada')).toBeInTheDocument()
    // La que no tiene cancha aplica a la sucursal entera.
    expect(within(tabla).getByText('Toda la sucursal')).toBeInTheDocument()
  })

  it('🔑 el buscador busca por el nombre de la cancha, que es lo que se ve', async () => {
    render(<Tarifas />)
    expect(await screen.findByText('Nocturna')).toBeInTheDocument()
    expect(screen.getByText('Diurna')).toBeInTheDocument()

    // "Techada" NO está en ningún campo de la tarifa: sale de resolver
    // `cancha_id: 7` contra la lista de canchas. Un buscador sobre el dato
    // crudo no encontraría nada acá, y la tabla quedaría vacía.
    await userEvent.type(screen.getByLabelText('Buscar tarifa'), 'techada')
    await waitFor(() => expect(screen.queryByText('Diurna')).not.toBeInTheDocument())
    expect(screen.getByText('Nocturna')).toBeInTheDocument()
  })

  it('a un encargado no le ofrece editar ni borrar', async () => {
    rol.actual = 'staff'
    render(<Tarifas />)
    // Se espera a que la tabla tenga datos ANTES de afirmar la ausencia: sin
    // esto el assert pasaría por no haber renderizado todavía.
    expect(await screen.findByText('Nocturna')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Editar/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Borrar/ })).not.toBeInTheDocument()
  })

  it('a un admin sí, y el botón dice a qué fila pertenece', async () => {
    render(<Tarifas />)
    expect(await screen.findByRole('button', { name: 'Editar Nocturna' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Borrar Diurna' })).toBeInTheDocument()
  })
})

describe('clientes: por qué está vacía la lista', () => {
  it('sin ninguno cargado lo dice', async () => {
    clientesListar.mockResolvedValue([])
    render(<Clientes />)
    expect(await screen.findByText('Todavía no hay clientes cargados.')).toBeInTheDocument()
  })

  it('con todos de baja manda al interruptor, no a la búsqueda', async () => {
    clientesListar.mockResolvedValue([{ ...CLIENTE, activo: false }])
    render(<Clientes />)
    expect(
      await screen.findByText(/Todos los clientes están dados de baja/),
    ).toBeInTheDocument()
  })

  it('🔑 cuando vacía la búsqueda, el mensaje es el del kit y cita lo tecleado', async () => {
    render(<Clientes />)
    expect(await screen.findByText('Ana Perez')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Buscar cliente'), 'zzz')
    // `DataTable` pisa el `emptyMessage` de la pagina cuando hay busqueda
    // activa. Este test existe para fijar ESO: la pagina no tiene que escribir
    // su propio "no coincide", y de hecho la rama que lo hacia era codigo
    // muerto — la encontro este test.
    expect(await screen.findByText(/Sin resultados para/)).toBeInTheDocument()
    expect(
      screen.queryByText('Todavía no hay clientes cargados.'),
    ).not.toBeInTheDocument()
  })

  it('el interruptor de dados de baja los trae', async () => {
    clientesListar.mockResolvedValue([CLIENTE, { ...CLIENTE, id: 2, nombre: 'Baja Total', activo: false }])
    render(<Clientes />)
    expect(await screen.findByText('Ana Perez')).toBeInTheDocument()
    expect(screen.queryByText('Baja Total')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: /Ver los dados de baja/ }))
    expect(await screen.findByText('Baja Total')).toBeInTheDocument()
  })

  it('la fila dada de baja se ve atenuada', async () => {
    clientesListar.mockResolvedValue([{ ...CLIENTE, activo: false }])
    render(<Clientes />)
    await userEvent.click(screen.getByRole('checkbox', { name: /Ver los dados de baja/ }))
    const fila = (await screen.findByText('Ana Perez')).closest('tr')
    expect(fila).toHaveClass('opacity-50')
  })

  it('un encargado SÍ puede escribir clientes: es el único maestro así', async () => {
    rol.actual = 'staff'
    render(<Clientes />)
    expect(await screen.findByRole('button', { name: 'Editar Ana Perez' })).toBeInTheDocument()
  })
})

describe('la tabla se dibuja con el encabezado del kit', () => {
  it('las columnas de tarifas están, y en orden', async () => {
    render(<Tarifas />)
    const cabeceras = await screen.findAllByRole('columnheader')
    const textos = cabeceras.map((c) => within(c).queryByRole('button')?.textContent ?? c.textContent)
    expect(textos.slice(0, 7)).toEqual([
      'Nombre', 'Aplica', 'Cancha', 'Franja', 'Precio', 'Seña', 'Prioridad',
    ])
  })
})
