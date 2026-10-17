/** El alta de un cliente desde el campo «Cliente» (`SelectCliente` de libra-ui, ADR-071): una sola implementación para toda pantalla de este
 *  producto donde se elige un cliente.
 *
 *  Pide teléfono y email además del nombre (los `campos` por defecto del componente): lo que el mostrador tiene a mano cuando alguien llama por
 *  primera vez. Es lo que ya hacía el viejo «Cliente nuevo» de la reserva. Documento, cuit y observaciones se completan después en Clientes.
 *
 *  🔑 Lo puede hacer un encargado (`staff`), igual que el ABM de Clientes: ver `construir_abm` en el backend. */
import { clientes as apiClientes, ErrorDeApi } from '@/lib/api'
import type { Cliente } from '@/lib/api'
import type { OpcionSelect } from '@/components/select-buscable'
import type { CampoDeAlta, ClienteNuevo } from 'libra-ui/SelectCliente'

/** Los campos que pide el alta, para pasarlos a `SelectCliente`. */
export const CAMPOS_DE_ALTA: CampoDeAlta[] = ['telefono', 'email']

/** La opción del desplegable para un cliente. Una sola, para que el recién creado se vea igual que los de la lista. */
export function opcionDeCliente(c: Pick<Cliente, 'id' | 'nombre' | 'telefono'>): OpcionSelect {
  return { value: String(c.id), label: c.nombre, hint: c.telefono ?? undefined }
}

/** Arma el `crear` de `SelectCliente`. `alCrear` recibe el cliente guardado para que la pantalla lo sume a su lista (el campo ya lo elige solo).
 *
 *  🔴 `SelectCliente` muestra el `detail` del error y, si no lo hay, «Error de conexión.». `ErrorDeApi` trae el texto del backend en `message`,
 *  así que se lo copia a `detail`: sin esto un 422 («nombre demasiado largo») se leería como si se hubiera caído la red. */
export function crearClienteParaSelect(alCrear?: (c: Cliente) => void) {
  return async (d: ClienteNuevo): Promise<OpcionSelect> => {
    try {
      const creado = await apiClientes.crear({ nombre: d.nombre, telefono: d.telefono || null, email: d.email || null })
      alCrear?.(creado)
      return opcionDeCliente(creado)
    } catch (err) {
      if (err instanceof ErrorDeApi) throw Object.assign(err, { detail: err.message })
      throw err
    }
  }
}
