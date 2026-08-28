
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import Icons from 'unplugin-icons/vite'

// Proxy de API en dev: el front (localhost:5173) le habla al backend por el
// MISMO origen, así la cookie de sesión funciona sin pelear con CORS/SameSite.
// En producción no hace falta, porque el build lo sirve el propio proceso
// FastAPI (ver `app/asgi.py`).
//
// 🔴 La cookie de `libraauth` es `Secure`: sobre http el navegador la acepta
// pero no la reenvía. En dev anda igual porque `localhost` está exceptuado de
// esa regla; en cualquier otro host que no sea https, no.
//
// Las claves que empiezan con `^` las interpreta Vite como expresión regular.
// Estas rutas no tienen metacaracteres, así que se escriben tal cual.
const RUTAS_API = ['/auth', '/api', '/admin', '/salud']
// 🔴 8099, el puerto que publica `docker-compose.yml`. Estuvo en 8098 desde el
// commit fundacional hasta el 2026-08-20, dos commits despues de que el compose
// se moviera al 8099 porque **el 8098 ya lo usa `libracargo-suitrans`**. O sea
// que en una maquina con ese contenedor arriba, `npm run dev` no fallaba: le
// pegaba a OTRO producto, que contesta igual. Si este valor cambia, cambia con
// el del compose.
const BACKEND = 'http://localhost:8099'

export default defineConfig({
  plugins: [react(), tailwindcss(), Icons({ compiler: 'jsx', jsx: 'react' })],
  resolve: {
    alias: { '@': new URL('./src', import.meta.url).pathname },
  },
  server: {
    proxy: Object.fromEntries(
      RUTAS_API.map((ruta) => [
        `^${ruta}(?:/|$)`,
        { target: BACKEND, changeOrigin: true },
      ]),
    ),
  },
})
