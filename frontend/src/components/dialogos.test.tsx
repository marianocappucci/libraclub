import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { FormularioDeCancha } from './FormularioDeCancha'
import { DetalleDeReserva } from './DetalleDeReserva'

/**
 * Los diálogos, después de pasar del `<dialog>` nativo al `Dialog` de shadcn.
 *
 * El dibujo lo pone shadcn/Radix. Lo que se fija acá es **el cambio de
 * comportamiento** que trajo la migración y que ningún test existente notaba:
 * los 20 tests de formularios pasaban igual antes y después, porque todos
 * renderizan con `abierto` y buscan en `document.body`.
 *
 * 🔑 **Cerrado ahora significa NO renderizado.** El `<dialog>` nativo dejaba
 * todo su contenido en el DOM y lo escondía por CSS: los campos se alcanzaban
 * con el tabulador y un lector de pantalla los anunciaba si la clase no llegaba
 * a aplicarse. Radix lo desmonta. Es la misma razón por la que el login de
 * `libra-ui` no usa `hidden` para plegar su formulario.
 *
 * Se midió antes de escribir esto: cerrado daba **0** campos de texto con
 * shadcn y los dejaba en el DOM con el `<dialog>`; abierto da 3.
 */

// `DetalleDeReserva` pasó a mostrar la factura de la reserva, y para eso mira el
// rol con `useAuth`. En la aplicación siempre hay `AuthProvider` —el diálogo
// cuelga del Layout— pero acá el componente se monta solo, así que se mockea el
// hook en vez de armar el provider entero: lo que estos tests miden es el
// diálogo, no la sesión.
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'admin', name: 'Admin', role: 'admin' }, loading: false }),
}))

// Y el pedido de la factura, que si no sale por `fetch` de verdad.
vi.mock('libra-ui/api-client', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    api: { get: vi.fn().mockResolvedValue(null), post: vi.fn(), put: vi.fn(), del: vi.fn() },
  }
})

const TURNO = {
  comienza_at: '2026-08-20T18:00:00-03:00',
  termina_at: '2026-08-20T19:30:00-03:00',
  libre: false,
  precio: '14000.00',
  reserva_id: 5,
  estado: 'confirmada',
  cliente: 'Ana Gomez',
  motivo: null,
}
const CANCHA = {
  id: 1, sucursal_id: 1, nombre: 'Cancha 1', deporte: 'padel',
  duracion_turno_min: 90, techada: true, iluminacion: true, superficie: null,
  orden: 1, activa: true, observaciones: null,
}

describe('un diálogo cerrado no está en el DOM', () => {
  it('el formulario de cancha, cerrado, no aporta ni un campo', () => {
    render(
      <FormularioDeCancha
        abierto={false} cancha={null} sucursalId={1}
        onCerrar={vi.fn()} onGuardada={vi.fn()}
      />,
    )
    expect(screen.queryAllByRole('textbox')).toHaveLength(0)
    // El control positivo va en el test de abajo: sin él, este cero podría
    // deberse a que el componente no renderiza nunca.
  })

  it('y abierto sí — el control positivo del test de arriba', () => {
    render(
      <FormularioDeCancha
        abierto cancha={null} sucursalId={1}
        onCerrar={vi.fn()} onGuardada={vi.fn()}
      />,
    )
    expect(screen.queryAllByRole('textbox').length).toBeGreaterThan(0)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})

describe('el título del diálogo', () => {
  it('nombra la acción, y en edición nombra la fila', () => {
    const { unmount } = render(
      <FormularioDeCancha
        abierto cancha={null} sucursalId={1}
        onCerrar={vi.fn()} onGuardada={vi.fn()}
      />,
    )
    // 🔑 Es un `heading` de verdad, no un `<span>` en negrita: `DialogTitle` es
    // lo que Radix usa para el nombre accesible del diálogo. Sin él, un lector
    // de pantalla anuncia "diálogo" y nada más.
    expect(screen.getByRole('heading', { name: 'Nueva cancha' })).toBeInTheDocument()
    unmount()

    render(
      <FormularioDeCancha
        abierto cancha={CANCHA} sucursalId={1}
        onCerrar={vi.fn()} onGuardada={vi.fn()}
      />,
    )
    expect(screen.getByRole('heading', { name: 'Editar Cancha 1' })).toBeInTheDocument()
  })

  it('el detalle de reserva distingue una reserva de un bloqueo', () => {
    const { unmount } = render(
      <DetalleDeReserva
        abierto turno={TURNO} cancha={CANCHA}
        onCerrar={vi.fn()} onCambiada={vi.fn()}
      />,
    )
    expect(screen.getByRole('heading', { name: 'Reserva' })).toBeInTheDocument()
    unmount()

    render(
      <DetalleDeReserva
        abierto turno={{ ...TURNO, estado: 'bloqueo', cliente: null, motivo: 'Mantenimiento' }}
        cancha={CANCHA} onCerrar={vi.fn()} onCambiada={vi.fn()}
      />,
    )
    expect(screen.getByRole('heading', { name: 'Bloqueo' })).toBeInTheDocument()
  })
})

describe('cómo se cierra', () => {
  it('🔑 Escape cierra de verdad: la cadena entera, no sólo el callback', async () => {
    // Se monta un padre CONTROLADO, como el real: `onCerrar` baja `abierto` y
    // eso desmonta el diálogo. Un test que sólo asierta que el `vi.fn()` se
    // llamó deja sin probar el tramo que importa —que el producto reaccione— y
    // pasaría igual con un `onCerrar` que no hace nada.
    function Padre() {
      const [abierto, setAbierto] = useState(true)
      return (
        <FormularioDeCancha
          abierto={abierto} cancha={null} sucursalId={1}
          onCerrar={() => setAbierto(false)} onGuardada={vi.fn()}
        />
      )
    }
    render(<Padre />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  // ⚠️ **Esto NO está verificado en un navegador de verdad.** Se intentó el
  // 2026-08-20 y el panel no tenía foco: se instaló un testigo de `keydown` y
  // llegaron **cero** eventos, así que la prueba no medía el diálogo sino el
  // arnés. Lo de acá arriba es jsdom, donde el `Escape` lo sintetiza
  // `userEvent`. Si alguna vez importa de verdad —foco atrapado, orden del
  // tabulador— se mide en un navegador con la ventana enfocada.

  // ⚠️ **El `if (!o)` del adaptador de `onOpenChange` NO está cubierto, y no se
  // puede cubrir con estos componentes.** Se escribió un test que decía
  // "abrirlo no dispara onCerrar" y se lo mutó sacando el `if`: siguió pasando.
  //
  // El motivo es que Radix llama a `onOpenChange` sólo ante un cambio que
  // origina el usuario, no al montar con `open` ya en `true`. Y como ninguno de
  // estos seis diálogos tiene `DialogTrigger` —los abre el estado del padre—,
  // `onOpenChange` nunca llega con `true`. O sea que sacar el `if` **no cambia
  // el comportamiento hoy**: el guard es defensivo, para el día que alguno
  // agregue un trigger propio.
  //
  // Se deja escrito acá en vez de dejar el test verde: un test que pasa con y
  // sin el mecanismo no prueba el mecanismo, prueba que el archivo compila.

  it('el botón de cerrar del kit también avisa', async () => {
    const onCerrar = vi.fn()
    render(
      <FormularioDeCancha
        abierto cancha={null} sucursalId={1}
        onCerrar={onCerrar} onGuardada={vi.fn()}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(onCerrar).toHaveBeenCalled()
  })
})
