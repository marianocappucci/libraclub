// El traductor automático del navegador no tiene que tocar la app. Con `lang="en"`, Chrome tomaba la página por inglesa y, en
// una PC con el castellano de idioma, la traducía sola: reescribe los nodos de texto por debajo de React y el próximo render
// se cae con «Failed to execute 'removeChild' on 'Node'» (pasó el 2026-10-23 en VentaLibra dev: el POS se cerraba al elegir un producto,
// y también Configuración y el detalle de venta). La app está en castellano y no se traduce.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const html = readFileSync(resolve(__dirname, '../../index.html'), 'utf8')

describe('index.html: sin traductor automático', () => {
  it('declara el castellano y pide no traducir', () => {
    expect(html).toMatch(/<html lang="es" translate="no">/)
    expect(html).toContain('<meta name="google" content="notranslate" />')
  })
})
