import { useEffect, useState } from 'react'

import { edicionesDeClientes } from '@/lib/api'
import type { CampoDeEdicionDeCliente } from '@/lib/api'

/** Aviso entre pantallas: se resolvió una edición, hay que volver a contar las que quedan. */
export const EVENTO_CAMBIO = 'clientes-en-conflicto:cambio'

export function avisarCambio(): void {
  window.dispatchEvent(new Event(EVENTO_CAMBIO))
}

/** Cuántos clientes tienen cambios cargados en la PC del club que chocan con la web (ADR-022). Alimenta el aviso de
 *  Clientes y el número del menú. Un conteo que no carga no tiene que tirar abajo la pantalla: queda en 0. */
export function useClientesParaRevisar(): number {
  const [cantidad, setCantidad] = useState(0)
  useEffect(() => {
    let vivo = true
    const contar = () => {
      edicionesDeClientes
        .listar()
        .then((l) => vivo && setCantidad(Array.isArray(l) ? l.length : 0))
        .catch(() => vivo && setCantidad(0))
    }
    contar()
    window.addEventListener(EVENTO_CAMBIO, contar)
    return () => {
      vivo = false
      window.removeEventListener(EVENTO_CAMBIO, contar)
    }
  }, [])
  return cantidad
}

/** Un valor de un dato del cliente, como se lee en la pantalla. */
export function textoDelValor(campo: Pick<CampoDeEdicionDeCliente, 'campo'>, valor: string | boolean | null): string {
  if (valor === null || valor === '') return '(vacío)'
  if (typeof valor === 'boolean') {
    if (campo.campo === 'activo') return valor ? 'Activo' : 'De baja'
    return valor ? 'Sí' : 'No'
  }
  return valor
}
