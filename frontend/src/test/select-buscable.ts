// Atajos para los tests de las pantallas que usan `SelectBuscable` (ADR-039 de libra-ui).
//
// El campo es un `role="combobox"` y su lista **sólo existe en el DOM mientras está abierta**: no hay `<option>` que leer ni `selectOptions` que
// valga. Se abre con un click y se elige la opción por su nombre. Mismos helpers que los del kit (`test/helpers-pantallas`).
import { screen, within } from '@testing-library/react'
import type userEvent from '@testing-library/user-event'

type Usuario = ReturnType<typeof userEvent.setup>

/** Abre el campo y elige la opción de ese nombre (texto exacto o expresión regular: con `hint`, el nombre de la opción lo incluye). */
export async function elegirEnBuscable(user: Usuario, combobox: HTMLElement, texto: string | RegExp) {
  await user.click(combobox)
  await user.click(await screen.findByRole('option', { name: texto }))
}

/** Las etiquetas de las opciones: se abre, se lee y se cierra con Escape. */
export async function opcionesDe(user: Usuario, combobox: HTMLElement): Promise<string[]> {
  await user.click(combobox)
  const lista = await screen.findByRole('listbox')
  const textos = within(lista).queryAllByRole('option').map((o) => o.textContent ?? '')
  await user.keyboard('{Escape}')
  return textos
}
