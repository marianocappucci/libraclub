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
    // 🔴 `@vitejs/plugin-react` no toca node_modules, asi que los .tsx de
    // `libra-ui` los transpila esbuild — y por default usa el runtime CLASICO,
    // que emite `React.createElement` sin que React este importado: "React is
    // not defined" al primer render. Con `automatic` usa el mismo runtime que
    // el resto de la app.
    esbuild: { jsx: 'automatic' },
    test: {
      environment: 'jsdom',
      globals: true,
      // 🔴 Zona fija. Sin esto, todo test que compare una fecha depende de la
      // zona de la máquina: el CI y WSL vienen en UTC, y a las 22:00 de
      // Argentina eso ya es mañana. Se pone la zona real de los usuarios, que
      // además es la única en la que corre este producto.
      env: { TZ: 'America/Argentina/Buenos_Aires' },
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      coverage: {
        provider: 'v8',
        // Trinquete, no meta. Se fija 2 puntos por debajo de lo que la suite
        // mide hoy (79.32% de lineas, medido el 2026-09-03), asi que pasa
        // holgado y lo unico que puede ponerlo en rojo es una regresion.
        // Sirve para que nadie borre tests, no para medir calidad.
        thresholds: { lines: 77 },
        reporter: ['text-summary', 'json-summary'],
        // Solo el codigo propio del producto: `libra-ui` tiene su propia
        // suite y su propio CI, medirlo aca contaria dos veces lo mismo.
        include: ['src/**/*.{ts,tsx}'],
        exclude: [
          'src/test/**',
          'src/**/*.d.ts',
          'src/main.tsx',
        ],
      },
    },
  }),
)
