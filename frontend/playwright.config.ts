import { defineConfig } from '@playwright/test'

// Smoke de navegador (F6.3). Corre contra la app REAL levantada por el workflow
// `smoke-navegador.yml`: uvicorn sirviendo `dist/` en localhost. `localhost` y
// no `127.0.0.1`: la cookie de sesión de libraauth es `Secure`, y Chromium sólo
// trata a `localhost` como contexto seguro sobre http. Los archivos son
// `*.smoke.ts` para que vitest, que colecta `src/**/*.test.*`, no los levante.
export default defineConfig({
  testDir: './e2e',
  testMatch: /.*\.smoke\.ts/,
  timeout: 30_000,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.SMOKE_BASE_URL ?? 'http://localhost:8000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
})
