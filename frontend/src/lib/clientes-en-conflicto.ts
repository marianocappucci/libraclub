import { useEffect, useState } from 'react'

import { edicionesDeClientes } from '@/lib/api'
import type { CampoDeEdicionDeCliente } from '@/lib/api'

/** Aviso entre pantallas: se resolvió una edición, hay que volver a contar las que quedan. */
export const EVENTO_CAMBIO = 'clientes-en-conflicto:cambio'

export function avisarCambio(): void {
  window.dispatchEvent(new Event(EVENTO_CAMBIO))
}

export interface ResumenDeClientesParaRevisar {
  /** Todos los que esperan a alguien: los que chocan y los que ya no chocan. */
  total: number
  /** Hay que elegir cuál queda. */
  chocan: number
  /** Siguen esperando pero ya no hay nada para elegir: se aplican o se descartan. */
  yaNoChocan: number
}

const SIN_NADA: ResumenDeClientesParaRevisar = { total: 0, chocan: 0, yaNoChocan: 0 }

/** Cuántos clientes tienen cambios cargados en la PC del club para revisar (ADR-022, tercer y cuarto addendum), contando
 *  las dos clases. Alimenta el aviso de Clientes. Un conteo que no carga no tiene que tirar abajo la pantalla: queda en 0. */
export function useResumenDeClientesParaRevisar(): ResumenDeClientesParaRevisar {
  const [resumen, setResumen] = useState(SIN_NADA)
  useEffect(() => {
    let vivo = true
    const contar = () => {
      edicionesDeClientes
        .listar()
        .then((l) => {
          if (!vivo) return
          const lista = Array.isArray(l) ? l : []
          const yaNoChocan = lista.filter((e) => e.ya_no_choca === true).length
          setResumen({ total: lista.length, chocan: lista.length - yaNoChocan, yaNoChocan })
        })
        .catch(() => vivo && setResumen(SIN_NADA))
    }
    contar()
    window.addEventListener(EVENTO_CAMBIO, contar)
    return () => {
      vivo = false
      window.removeEventListener(EVENTO_CAMBIO, contar)
    }
  }, [])
  return resumen
}

/** Cuántos clientes esperan una revisión, de las dos clases: es el número del menú. */
export function useClientesParaRevisar(): number {
  return useResumenDeClientesParaRevisar().total
}

function clientes(n: number): string {
  return n === 1 ? '1 cliente' : `${n} clientes`
}

/** El aviso de la pantalla de Clientes: dice cuántos hay y de qué clase. */
export function textoDelAviso({ total, chocan, yaNoChocan }: ResumenDeClientesParaRevisar): string {
  if (yaNoChocan === 0) {
    return `Hay ${clientes(total)} con cambios de la PC del club que chocan con los de la web.`
  }
  if (chocan === 0) {
    return `Hay ${clientes(total)} con cambios de la PC del club que ya no ${total === 1 ? 'choca' : 'chocan'} con los de la web y se ${total === 1 ? 'puede' : 'pueden'} aplicar.`
  }
  return (
    `Hay ${clientes(total)} con cambios de la PC del club para revisar: ${chocan} ${chocan === 1 ? 'choca' : 'chocan'} ` +
    `con los de la web y ${yaNoChocan} ya no ${yaNoChocan === 1 ? 'choca' : 'chocan'} y se puede${yaNoChocan === 1 ? '' : 'n'} aplicar.`
  )
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
