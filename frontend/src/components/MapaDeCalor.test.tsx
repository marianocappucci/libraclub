import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MapaDeCalor } from './MapaDeCalor'

const FRANJAS = [
  { dia: 0, hora: 18, ocupacion_pct: 92 },
  { dia: 0, hora: 19, ocupacion_pct: 0 },
  { dia: 1, hora: 18, ocupacion_pct: 37.5 },
  // El martes a las 19 el complejo no abre: la celda no viene.
]

describe('MapaDeCalor', () => {
  it('es una grilla de 7 días por las horas que hay, con un encabezado por día y por hora', () => {
    render(<MapaDeCalor franjas={FRANJAS} etiqueta="Ocupación por día y hora" />)
    const tabla = screen.getByRole('table', { name: 'Ocupación por día y hora' })

    expect(within(tabla).getAllByRole('columnheader').map((c) => c.textContent)).toEqual(
      ['Hora', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'],
    )
    expect(within(tabla).getAllByRole('rowheader').map((c) => c.textContent)).toEqual(['18:00', '19:00'])
    expect(within(tabla).getAllByRole('cell')).toHaveLength(14)
  })

  it('cada celda dice su valor en el title y en el aria-label', () => {
    render(<MapaDeCalor franjas={FRANJAS} etiqueta="Mapa" />)

    const celda = screen.getByLabelText('Lunes 18:00 – 19:00: 92 % de ocupación')
    expect(celda).toHaveAttribute('title', 'Lunes 18:00 – 19:00: 92 % de ocupación')
    expect(celda).toHaveTextContent('92')
    expect(screen.getByLabelText('Martes 18:00 – 19:00: 37,5 % de ocupación')).toHaveTextContent('38')
  })

  it('🔑 una hora cerrada no es una hora en 0 %: se dibuja aparte y dice «cerrado»', () => {
    render(<MapaDeCalor franjas={FRANJAS} etiqueta="Mapa" />)

    const vacia = screen.getByLabelText('Lunes 19:00 – 20:00: 0 % de ocupación')
    const cerrada = screen.getByLabelText('Martes 19:00 – 20:00: cerrado')

    expect(vacia).toHaveAttribute('data-pct', '0')
    expect(cerrada).toHaveAttribute('data-estado', 'cerrado')
    expect(cerrada).not.toHaveAttribute('data-pct')
    // Los que ni figuran (miércoles a domingo) también son cerrados, no 0 %.
    expect(screen.getAllByRole('cell').filter((c) => c.getAttribute('data-estado') === 'cerrado')).toHaveLength(11)
  })

  it('el color sale de los tokens del tema, y crece con la ocupación', () => {
    render(<MapaDeCalor franjas={FRANJAS} etiqueta="Mapa" />)

    // El valor se lee del atributo `style` tal cual lo escribió React: jsdom descarta `color-mix` al normalizar.
    const fondo = (etiqueta: string) => screen.getByLabelText(etiqueta).getAttribute('style') ?? ''
    expect(fondo('Lunes 18:00 – 19:00: 92 % de ocupación')).toContain('var(--marca)')
    expect(fondo('Lunes 18:00 – 19:00: 92 % de ocupación')).toContain('var(--card)')
    expect(fondo('Lunes 18:00 – 19:00: 92 % de ocupación')).toContain('92%')
    expect(fondo('Martes 18:00 – 19:00: 37,5 % de ocupación')).toContain('37.5%')
    // Y no hay ningún color fijo escrito a mano en el fondo de una celda.
    expect(fondo('Lunes 18:00 – 19:00: 92 % de ocupación')).not.toMatch(/#[0-9a-f]{3,6}|rgb\(/i)
  })

  it('trae la leyenda', () => {
    const { container } = render(<MapaDeCalor franjas={FRANJAS} etiqueta="Mapa" />)
    expect(container.querySelector('[data-slot="leyenda-del-mapa"]')).toHaveTextContent('Cerrado')
  })
})
