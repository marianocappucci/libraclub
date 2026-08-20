// Config de tests aparte del `vite.config.ts`, y no un bloque `test` adentro de
// él: así el build de producción no arrastra tipos ni opciones de Vitest. Se
// reusa la config de Vite —con su alias `@`— vía `mergeConfig`, para que los
// tests resuelvan los imports igual que la app.
//
// 🔴 `mergeConfig` de `vitest/config` y no `defineConfig` de `vitest/config` con
// los plugins repetidos: Vitest trae su propia copia de Vite, y declarar el
// plugin de React en los dos lados hace que `tsc` compare dos tipos `Plugin`
// distintos y falle el build entero con un error que no habla de eso.
import { defineConfig, mergeConfig } from 'vitest/config'

import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      // 🔴 Zona fija. Sin esto, todo test que compare una fecha depende de la
      // zona de la máquina: el CI y WSL vienen en UTC, y a las 22:00 de
      // Argentina eso ya es mañana. Se pone la zona real de los usuarios, que
      // además es la única en la que corre este producto.
      env: { TZ: 'America/Argentina/Buenos_Aires' },
      include: ['src/**/*.test.{ts,tsx}'],
    },
  }),
)
